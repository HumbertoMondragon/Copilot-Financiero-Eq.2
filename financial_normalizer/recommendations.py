"""
Recommendation engine.
Takes an AnalysisPackage and generates structured, evidence-based financial
recommendations using the Claude API. Every recommendation must cite a
specific value from the AnalysisPackage — the LLM must never invent numbers.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .orchestrator import AnalysisPackage


class RecommendationError(Exception):
    def __init__(self, message: str, raw_response: str = "") -> None:
        super().__init__(message)
        self.raw_response = raw_response


@dataclass
class RecommendationReport:
    cliente_id: str
    periodo: str
    generated_at: str
    model_used: str
    recomendaciones: list
    limitaciones: list
    resumen_ejecutivo: str
    metadata: dict


class RecommendationEngine:
    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 2000,
    ) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY environment variable not set")
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    # ── Public API ─────────────────────────────────────────────────────────────

    def build_prompt(self, pkg: "AnalysisPackage") -> str:
        """
        Build the user prompt from the AnalysisPackage.
        Uses only formatted summary data — never dumps raw JSON into the prompt.
        """
        parts: list[str] = []

        # 1. Strict instruction block
        parts.append(
            "INSTRUCCIONES: Eres un consultor financiero senior. "
            "Genera recomendaciones basadas ÚNICAMENTE en los datos proporcionados. "
            "Cada recomendación DEBE citar el valor numérico específico que la sustenta. "
            "Si los datos son insuficientes para una recomendación, omítela. "
            "No inventes cifras, tendencias ni contexto que no esté en los datos."
        )

        # 2. Financial summary
        por_mes: dict = pkg.indicadores.get("por_mes", {})
        tendencias: dict = pkg.indicadores.get("tendencias", {})
        re_exec: dict = pkg.indicadores.get("resumen_ejecutivo", {})

        parts.append(f"\nDATOS FINANCIEROS | Período: {pkg.periodo}")

        for mes, mi in por_mes.items():
            rent = mi["rentabilidad"]
            ec = mi["estructura_costos"]
            suc: dict = mi["sucursales"]
            ranking: list = mi.get("ranking_sucursales", list(suc.keys()))
            alertas: list = mi.get("alertas", [])

            tv = sum(s["venta"] for s in suc.values())
            parts.append(f"\n[{mes}]")
            parts.append(
                f"  Ventas: ${tv:,.0f}"
                f" | Margen bruto: {rent['margen_bruto'] * 100:.1f}%"
                f" | EBITDA: {rent['margen_ebitda'] * 100:.1f}%"
                f" | Neto: {rent['margen_neto'] * 100:.1f}%"
            )
            parts.append(
                f"  Nómina/Ventas: {ec['nomina_sobre_ventas'] * 100:.1f}%"
                f" | Gastos op/Ventas: {ec['gastos_op_sobre_ventas'] * 100:.1f}%"
            )
            mayor = ec.get("categoria_mayor_egreso")
            menor = ec.get("categoria_menor_egreso")
            if mayor or menor:
                parts.append(f"  Mayor egreso: {mayor} | Menor egreso: {menor}")
            parts.append("  Sucursales:")
            for grp in ranking:
                s = suc[grp]
                flag = " [ALERTA]" if s["alerta_margen"] else ""
                parts.append(
                    f"    {grp}: ${s['venta']:,.0f}"
                    f" | margen {s['margen'] * 100:.1f}%"
                    f" | part. {s['participacion_ventas'] * 100:.1f}%{flag}"
                )
            if alertas:
                parts.append("  Alertas:")
                for a in alertas:
                    parts.append(
                        f"    [{a['severidad'].upper()}] {a['tipo']}:"
                        f" {a['valor'] * 100:.2f}% (umbral: {a['umbral'] * 100:.0f}%)"
                    )
            else:
                parts.append("  Alertas: ninguna")

        # Trend summary
        meses_con_datos: list = tendencias.get("meses_con_datos", [])
        tend_ventas = tendencias.get("ventas", {}).get("tendencia", "N/A")
        parts.append(f"\nTendencias ventas: {tend_ventas} ({len(meses_con_datos)} mes(es) con datos)")

        mejor = re_exec.get("mejor_sucursal_promedio") or "N/A"
        peor = re_exec.get("peor_sucursal_promedio") or "N/A"
        alertas_total = re_exec.get("total_alertas_activas", 0)
        parts.append(f"Resumen: mejor sucursal {mejor}, peor {peor}, {alertas_total} alerta(s) activa(s)")

        # 3. Qualitative context — gather all chunks, deduplicate, top 8 by score
        all_chunks: list[dict] = []
        for ctx in pkg.contexto_cualitativo.values():
            all_chunks.extend(ctx.get("chunks_relevantes", []))

        seen_texts: set[str] = set()
        unique_chunks: list[dict] = []
        for ch in sorted(all_chunks, key=lambda c: c["score"], reverse=True):
            if ch["texto"] not in seen_texts:
                seen_texts.add(ch["texto"])
                unique_chunks.append(ch)
            if len(unique_chunks) == 8:
                break

        if unique_chunks:
            parts.append("\nCONTEXTO CUALITATIVO")
            for ch in unique_chunks:
                parts.append(f"  [{ch['filename']}, chunk {ch['chunk_index']}]: {ch['texto'][:300]}")
        else:
            parts.append("\nCONTEXTO CUALITATIVO: ninguno disponible")

        # 4. Output instructions
        parts.append(
            "\nRESPONDE ÚNICAMENTE con un JSON array válido (sin markdown, sin texto adicional):\n"
            '[\n  {"id": "REC-001",\n'
            '   "area": "rentabilidad|costos|sucursales|operaciones|financiero",\n'
            '   "prioridad": "alta|media|baja",\n'
            '   "titulo": "...",\n'
            '   "descripcion": "...",\n'
            '   "evidencia": [{"tipo": "indicador|alerta|documento", "fuente": "...", "valor": "..."}],\n'
            '   "accion_sugerida": "..."}\n'
            "]\n"
            "Máximo 5 recomendaciones."
        )

        return "\n".join(parts)

    def generate(self, pkg: "AnalysisPackage") -> RecommendationReport:
        if not pkg.listo_para_recomendaciones:
            raise RecommendationError("AnalysisPackage not ready: no months with data")

        prompt = self.build_prompt(pkg)

        # First attempt
        response = self._call_api(prompt)
        raw = response.content[0].text
        usage = response.usage
        recs_data = _try_parse_json(raw)

        if recs_data is None:
            # Single retry with explicit JSON-only instruction
            retry_prompt = (
                prompt
                + "\n\nADVERTENCIA: Tu respuesta anterior no fue JSON válido. "
                "Responde ÚNICAMENTE con el array JSON, sin ningún otro texto."
            )
            response = self._call_api(retry_prompt)
            raw = response.content[0].text
            usage = response.usage
            recs_data = _try_parse_json(raw)
            if recs_data is None:
                raise RecommendationError(
                    "Claude returned invalid JSON after retry",
                    raw_response=raw,
                )

        total_chunks = sum(
            len(ctx.get("chunks_relevantes", []))
            for ctx in pkg.contexto_cualitativo.values()
        )
        re_exec: dict = pkg.indicadores.get("resumen_ejecutivo", {})

        return RecommendationReport(
            cliente_id=pkg.cliente_id,
            periodo=pkg.periodo,
            generated_at=datetime.now(timezone.utc).isoformat(),
            model_used=self._model,
            recomendaciones=recs_data if isinstance(recs_data, list) else [],
            limitaciones=_build_limitaciones(pkg),
            resumen_ejecutivo=_build_resumen_ejecutivo(pkg),
            metadata={
                "meses_analizados": re_exec.get("meses_analizados", 0),
                "alertas_activas": re_exec.get("total_alertas_activas", 0),
                "chunks_cualitativos_usados": total_chunks,
                "prompt_tokens": usage.input_tokens,
                "completion_tokens": usage.output_tokens,
            },
        )

    def generate_from_files(
        self,
        financial_filepath,
        qualitative_filepaths,
        cliente_id: str,
        persist_directory: str = "./chroma_db",
    ) -> RecommendationReport:
        """
        End-to-end convenience: normalise → ingest → analyse → recommend.
        Creates its own DocumentStore, VectorStore, and AnalysisOrchestrator.
        """
        from .ingestion.document_store import DocumentStore
        from .ingestion.vector_store import VectorStore
        from .orchestrator import AnalysisOrchestrator

        store = DocumentStore()
        vs = VectorStore(persist_directory=persist_directory)
        orch = AnalysisOrchestrator(vector_store=vs)
        pkg = orch.ingest_and_analyze(
            financial_filepath, qualitative_filepaths, cliente_id, store, vs
        )
        return self.generate(pkg)

    # ── Private ────────────────────────────────────────────────────────────────

    def _call_api(self, prompt: str):
        return self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )


# ── Module-level helpers ──────────────────────────────────────────────────────

def _try_parse_json(text: str):
    """Parse text as a JSON list. Strips markdown fences. Returns None on failure."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        end = len(lines) - 1 if lines[-1].strip().startswith("```") else len(lines)
        text = "\n".join(lines[1:end]).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        # Handle common wrapper patterns
        for key in ("recomendaciones", "recommendations", "data"):
            if isinstance(parsed, dict) and key in parsed and isinstance(parsed[key], list):
                return parsed[key]
        return None
    except json.JSONDecodeError:
        return None


def _build_limitaciones(pkg: "AnalysisPackage") -> list[str]:
    lims: list[str] = []
    meses_con_datos: list = pkg.indicadores.get("tendencias", {}).get("meses_con_datos", [])
    if len(meses_con_datos) <= 1:
        lims.append("Solo se cuenta con datos de 1 mes, tendencias no disponibles")
    total_chunks = sum(
        len(ctx.get("chunks_relevantes", []))
        for ctx in pkg.contexto_cualitativo.values()
    )
    if total_chunks == 0:
        lims.append("No se proporcionaron documentos cualitativos para contexto")
    return lims


def _build_resumen_ejecutivo(pkg: "AnalysisPackage") -> str:
    re_exec: dict = pkg.indicadores.get("resumen_ejecutivo", {})
    n = re_exec.get("meses_analizados", 0)
    alertas = re_exec.get("total_alertas_activas", 0)
    mejor = re_exec.get("mejor_sucursal_promedio") or "N/A"
    peor = re_exec.get("peor_sucursal_promedio") or "N/A"
    return (
        f"Análisis de {n} mes(es) del período {pkg.periodo}. "
        f"Sucursal con mejor desempeño: {mejor}; con menor desempeño: {peor}. "
        f"Se identificaron {alertas} alerta(s) activa(s)."
    )
