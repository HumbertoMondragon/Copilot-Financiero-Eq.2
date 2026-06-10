import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import openai
except ImportError:
    openai = None  # type: ignore

from .forecast import ForecastResult, forecast_revenue
from .health_score import HealthScoreReport, calcular_health_score
from .integrator import integrate
from .kpis import KPIReport, calcular_kpis
from .macro import MacroFetcher, MacroIndices
from .parsers.parser_bd import parse_bd
from .parsers.parser_er import parse_er
from .shap_translator import SHAPNarrative, translate_shap
from ..ml.predictor import predict_and_explain
from ..ml.trainer import train

logger = logging.getLogger(__name__)

try:
    from ..ingestion.vector_store import VectorStore as _VectorStore
except Exception:
    _VectorStore = None  # type: ignore

_SYSTEM_INSTRUCTION = (
    "Eres un consultor financiero senior especializado en PyMEs mexicanas.\n"
    "Tu rol es narrar e integrar los datos proporcionados — no inventar información.\n"
    "Cada afirmación debe citar el valor numérico o el documento específico que la sustenta.\n"
    "Si los datos son insuficientes para una conclusión, indícalo explícitamente."
)

_OUTPUT_FORMAT = (
    'Responde ÚNICAMENTE con este JSON (sin markdown, sin preámbulo):\n'
    '{\n'
    '  "contexto_sectorial": {\n'
    '    "giro_detectado": "Sector o giro del negocio inferido de los documentos cualitativos y las categorías de SKUs (ej: restaurantes, manufactura, retail, clínicas). Si no hay documentos, infiere del nombre de categorías.",\n'
    '    "resumen": "Párrafo de 4-6 oraciones con el entorno macroeconómico específico del giro en México: reformas regulatorias recientes (laborales, fiscales, sanitarias), tendencias del sector, presiones de costos particulares del giro, y oportunidades u amenazas externas relevantes para el periodo analizado.",\n'
    '    "factores": [\n'
    '      {"tipo": "regulatorio|tendencia|riesgo|oportunidad", "descripcion": "Descripción concisa del factor sectorial y su impacto potencial en el negocio."}\n'
    '    ]\n'
    '  },\n'
    '  "recomendaciones": [\n'
    '    {\n'
    '      "id": "REC-001",\n'
    '      "area": "rentabilidad|costos|sucursales|mix_productos|macro|operaciones",\n'
    '      "prioridad": "alta|media|baja",\n'
    '      "titulo": "Título concreto y específico (10-15 palabras)",\n'
    '      "descripcion": "Análisis detallado de 3-5 oraciones: situación actual con cifras, causa raíz identificada, relación con los KPIs y Health Score reportados, y contexto macroeconómico relevante si aplica.",\n'
    '      "evidencia": [{"tipo": "kpi|shap|sku|macro|documento", "fuente": "nombre del indicador o documento", "valor": "valor numérico exacto del dato"}],\n'
    '      "accion_sugerida": "Pasos concretos y secuenciados (2-3 oraciones): qué hacer, cómo y en qué plazo estimado.",\n'
    '      "impacto_estimado": "Estimación cuantitativa o semi-cuantitativa: porcentaje de mejora esperado, ahorro potencial o variación en márgenes, con base en los datos disponibles."\n'
    '    }\n'
    '  ],\n'
    '  "narrativa_ejecutiva": "Párrafo ejecutivo de 5-7 oraciones que integre: estado financiero general con el Health Score, los KPIs más relevantes vs benchmark, factores ML/SHAP determinantes, tendencia de ingresos y contexto macro. Debe ser redactado como un consultor senior explicando la situación a un director.",\n'
    '  "limitaciones": ["limitación específica con explicación de su impacto en el análisis"]\n'
    '}\n'
    'Entre 3 y 5 recomendaciones. Prioriza por fortaleza de evidencia y magnitud del impacto potencial. Cada descripción debe citar valores numéricos específicos de los datos proporcionados. '
    'El campo "contexto_sectorial" es obligatorio: si no hay documentos cualitativos, infiere el giro de las categorías de SKUs y proporciona igualmente el análisis sectorial.'
)


@dataclass
class CopilotReport:
    cliente_id: str
    periodo: str
    generated_at: str
    model_used: str
    health_score: float
    health_categoria: str
    recomendaciones: List[Dict[str, Any]]
    narrativa_ejecutiva: str
    shap_top_factores: List[Dict[str, Any]]
    forecast: Optional[Dict[str, Any]]
    limitaciones: List[str]
    metadata: Dict[str, Any]
    contexto_sectorial: Dict[str, Any] = field(default_factory=dict)


class CopilotEngine:

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        max_tokens: int = 4000,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self._last_usage: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}
        if openai is None:
            raise ImportError("openai no instalado — ejecuta: pip install openai")
        self._client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

        self._vector_store = None
        if _VectorStore is not None:
            try:
                self._vector_store = _VectorStore()
            except Exception as exc:
                logger.warning("VectorStore init failed — RAG disabled: %s", exc)

    def build_prompt(
        self,
        kpi_report: KPIReport,
        health_score_report: HealthScoreReport,
        macro_indices: Optional[MacroIndices],
        shap_narrative: Optional[SHAPNarrative],
        forecast_result: Optional[ForecastResult],
        chunks: List[Dict[str, Any]],
        scenario_result: Optional[Any] = None,
    ) -> str:
        mes = kpi_report.meses_analizados[-1]
        hs_mes = health_score_report.por_mes[mes]
        consolidado = kpi_report.por_mes[mes]["consolidado"]

        parts: List[str] = []

        # Health Score section
        dim_debil = hs_mes["dimension_mas_debil"]
        dim_fuerte = hs_mes["dimension_mas_fuerte"]
        dim_debil_data = hs_mes["dimensiones"][dim_debil]
        parts.append(
            f"\n## Health Score — {mes}\n"
            f"Score: {hs_mes['score_total']:.1f}/100 ({hs_mes['categoria']})\n"
            f"Dimensión más débil: {dim_debil} "
            f"(score {dim_debil_data['score']}, "
            f"valor {dim_debil_data['valor_base']}, "
            f"benchmark {dim_debil_data['benchmark']})\n"
            f"Dimensión más fuerte: {dim_fuerte} "
            f"(score {hs_mes['dimensiones'][dim_fuerte]['score']})"
        )

        # KPI consolidado section
        parts.append(
            f"\n## KPIs — {mes}\n"
            f"Revenue: ${consolidado.get('total_revenue', 0):,.0f}\n"
            f"Margen bruto: {consolidado.get('margen_bruto', 0):.1%}\n"
            f"EBITDA: ${consolidado.get('ebitda', 0):,.0f}\n"
            f"Margen neto: {consolidado.get('margen_neto', 0):.1%}"
        )

        vs_bench = kpi_report.por_mes[mes].get("vs_benchmark", {})
        alertas = [k for k, v in vs_bench.items() if v.get("estado") in ("alerta", "critico")]
        if alertas:
            lines = "\n".join(
                f"  - {k}: {vs_bench[k]['valor']:.3f} vs {vs_bench[k]['benchmark']:.3f} "
                f"({vs_bench[k]['estado']})"
                for k in alertas[:3]
            )
            parts.append(f"\nKPIs fuera de benchmark:\n{lines}")

        # SHAP narrative section
        if shap_narrative:
            parts.append(
                f"\n## Análisis ML — Factores de eficiencia\n"
                f"{shap_narrative.global_['narrativa']}"
            )

        # Efficiency ranking section
        eff = kpi_report.por_mes[mes].get("efficiency_ranking", [])
        if eff:
            top5 = "\n".join(
                f"  {i + 1}. {r['sku']} ({r['sucursal']}): "
                f"{r['multiplicador_eficiencia']:.2f}×"
                for i, r in enumerate(eff[:5])
            )
            skus_bajo = kpi_report.por_mes[mes].get("skus_bajo_rendimiento", [])
            parts.append(
                f"\n## Ranking de eficiencia\nTop 5 SKUs:\n{top5}\n"
                f"SKUs bajo rendimiento: {len(skus_bajo)}"
            )

        # Forecast section
        if forecast_result:
            parts.append(
                f"\n## Forecast\n"
                f"Mes proyectado: {forecast_result.mes_proyectado}\n"
                f"Revenue proyectado: ${forecast_result.revenue_proyectado:,.0f}\n"
                f"Tendencia: {forecast_result.tendencia} | "
                f"Confianza: {forecast_result.confianza}\n"
                f"Advertencia: {forecast_result.advertencia}"
            )

        # Macro section
        if macro_indices is not None:
            parts.append(
                f"\n## Contexto macroeconómico\n"
                f"{macro_indices.narrativa_consolidada}"
            )

        # Scenario simulation section
        if scenario_result is not None:
            try:
                d_mb = scenario_result.distribuciones.get("margen_bruto")
                d_eb = scenario_result.distribuciones.get("ebitda")
                prob = scenario_result.probabilidades_benchmark
                var = scenario_result.variables_input.get("variaciones_esperadas", {})
                var_str = ", ".join(
                    f"{k} {'+' if v >= 0 else ''}{v:.0%}"
                    for k, v in var.items() if v != 0
                ) or "sin cambios en variables"
                parts.append(
                    f"\n## Escenario simulado ({scenario_result.n_simulaciones:,} iteraciones Monte Carlo)\n"
                    f"Variables modificadas: {var_str}\n"
                    f"Margen bruto — P50={d_mb.p50:.1%}, rango P10-P90=[{d_mb.p10:.1%}, {d_mb.p90:.1%}]\n"
                    f"Prob. margen sobre benchmark: {prob.get('margen_bruto_sobre_benchmark', 0):.0%}\n"
                    f"EBITDA mediano proyectado: ${d_eb.p50:,.0f}\n"
                    f"Prob. EBITDA positivo: {prob.get('ebitda_positivo', 0):.0%}\n"
                    f"Prob. nómina bajo benchmark: {prob.get('nomina_bajo_benchmark', 0):.0%}"
                )
            except Exception:
                pass

        # Qualitative chunks section — all chunks, full context
        if chunks:
            chunk_lines = []
            for c in chunks:
                if hasattr(c, "texto"):
                    source = getattr(c, "doc_id", "doc")
                    text = str(c.texto)[:300]
                else:
                    source = c.get("source", c.get("doc_id", "doc"))
                    text = str(c.get("text", c.get("texto", "")))[:300]
                chunk_lines.append(f"[{source}]: {text}")
            parts.append(f"\n## Contexto cualitativo\n" + "\n".join(chunk_lines))

        parts.append(f"\n## Instrucciones de salida\n{_OUTPUT_FORMAT}")
        return "\n".join(parts)

    def _call_llm(self, prompt: str) -> Dict[str, Any]:
        for attempt in range(2):
            response = self._client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _SYSTEM_INSTRUCTION},
                    {"role": "user", "content": prompt},
                ],
            )
            text = response.choices[0].message.content
            self._last_usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
            }
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                if attempt == 0:
                    logger.warning("LLM returned invalid JSON on attempt 1 — retrying")
                    continue
                logger.error("LLM returned invalid JSON after retry")
                return {
                    "recomendaciones": [],
                    "narrativa_ejecutiva": text[:500],
                    "limitaciones": ["LLM retornó JSON inválido tras reintento."],
                }
        return {"recomendaciones": [], "narrativa_ejecutiva": "", "limitaciones": []}

    def generate(
        self,
        kpi_report: KPIReport,
        health_score_report: HealthScoreReport,
        macro_indices: Optional[MacroIndices] = None,
        shap_narrative: Optional[SHAPNarrative] = None,
        forecast_result: Optional[ForecastResult] = None,
        chunks: Optional[List[Any]] = None,
        scenario_result: Optional[Any] = None,
        cliente_id: str = "default",
    ) -> CopilotReport:
        if not kpi_report.meses_analizados:
            raise ValueError("kpi_report has no months with data")

        chunks = chunks or []
        mes = kpi_report.meses_analizados[-1]

        prompt = self.build_prompt(
            kpi_report, health_score_report, macro_indices,
            shap_narrative, forecast_result, chunks, scenario_result,
        )
        llm_data = self._call_llm(prompt)

        hs_mes = health_score_report.por_mes[mes]

        shap_top: List[Dict[str, Any]] = []
        if shap_narrative:
            shap_top = shap_narrative.global_.get("top_3_factores_descripcion", [])

        limitaciones: List[str] = list(llm_data.get("limitaciones", []))
        if len(kpi_report.meses_analizados) < 3:
            limitaciones.append(
                f"Solo {len(kpi_report.meses_analizados)} mes(es) de datos — "
                "tendencias poco confiables."
            )

        skus_bajo = kpi_report.por_mes[mes].get("skus_bajo_rendimiento", [])
        eff = kpi_report.por_mes[mes].get("efficiency_ranking", [])

        forecast_dict: Optional[Dict[str, Any]] = None
        if forecast_result:
            forecast_dict = {
                "mes_proyectado": forecast_result.mes_proyectado,
                "revenue_proyectado": forecast_result.revenue_proyectado,
                "tendencia": forecast_result.tendencia,
                "confianza": forecast_result.confianza,
                "advertencia": forecast_result.advertencia,
            }

        return CopilotReport(
            cliente_id=cliente_id,
            periodo=mes,
            generated_at=datetime.now(timezone.utc).isoformat(),
            model_used=self.model,
            health_score=hs_mes["score_total"],
            health_categoria=hs_mes["categoria"],
            recomendaciones=llm_data.get("recomendaciones", []),
            narrativa_ejecutiva=llm_data.get("narrativa_ejecutiva", ""),
            shap_top_factores=shap_top,
            forecast=forecast_dict,
            limitaciones=limitaciones,
            contexto_sectorial=llm_data.get("contexto_sectorial", {}),
            metadata={
                "meses_analizados": len(kpi_report.meses_analizados),
                "total_skus": len(eff),
                "skus_bajo_rendimiento": len(skus_bajo),
                "chunks_cualitativos_usados": len(chunks),
                "prompt_tokens": self._last_usage.get("prompt_tokens", 0),
                "completion_tokens": self._last_usage.get("completion_tokens", 0),
            },
        )

    def run_full_pipeline(
        self,
        bd_filepath: str,
        er_filepath: str,
        qualitative_filepaths: Optional[List[str]] = None,
        cliente_id: str = "default",
        config_path: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        train_model: bool = True,
    ) -> CopilotReport:
        qualitative_filepaths = qualitative_filepaths or []

        if config is None:
            if config_path is None:
                config_path = f"configs/{cliente_id}.json"
            try:
                with open(config_path) as fh:
                    config = json.load(fh)
            except FileNotFoundError:
                logger.warning("Config not found at %s — using defaults", config_path)
                config = {}

        bd_data = parse_bd(bd_filepath)
        er_data = parse_er(er_filepath)
        financial_data = integrate(bd_data, er_data)
        kpi_report = calcular_kpis(financial_data, config)

        shap_narrative: Optional[SHAPNarrative] = None
        if train_model:
            try:
                trained = train(bd_data)
                pred_report = predict_and_explain(trained, bd_data)
                shap_narrative = translate_shap(pred_report, config)
            except Exception as exc:
                logger.warning("ML pipeline failed: %s", exc)

        forecast_result = forecast_revenue(kpi_report)

        macro_indices: Optional[MacroIndices] = None
        try:
            fetcher = MacroFetcher()
            macro_data = fetcher.fetch_all()
            macro_indices = fetcher.calcular_indices(macro_data, config)
        except Exception as exc:
            logger.warning("Macro pipeline failed: %s", exc)

        health_score_report = calcular_health_score(kpi_report, macro_indices, config)

        all_chunks: List[Any] = []
        if qualitative_filepaths:
            try:
                from ..ingestion.document_loader import load_document
                from ..ingestion.chunker import chunk_document
                for fp in qualitative_filepaths:
                    doc = load_document(fp, cliente_id)
                    all_chunks.extend(chunk_document(doc))
            except Exception as exc:
                logger.warning("Qualitative ingestion failed: %s", exc)

        return self.generate(
            kpi_report=kpi_report,
            health_score_report=health_score_report,
            macro_indices=macro_indices,
            shap_narrative=shap_narrative,
            forecast_result=forecast_result,
            chunks=all_chunks,
            cliente_id=cliente_id,
        )
