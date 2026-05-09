"""
Analysis orchestrator.
Combines quantitative indicators with qualitative context from the vector store,
producing a structured AnalysisPackage ready for the recommendation engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from . import indicators

if TYPE_CHECKING:
    from .ingestion.vector_store import VectorStore


@dataclass
class AnalysisPackage:
    cliente_id: str
    periodo: str
    generated_at: str
    indicadores: dict
    contexto_cualitativo: dict
    resumen_alertas: list
    listo_para_recomendaciones: bool


class AnalysisOrchestrator:
    def __init__(self, vector_store: "VectorStore | None" = None) -> None:
        self._vs = vector_store

    # ── Main ──────────────────────────────────────────────────────────────────

    def analyze(self, normalized_json: dict, cliente_id: str) -> AnalysisPackage:
        """
        Run indicators, retrieve qualitative context per month, and assemble
        an AnalysisPackage.
        """
        inds = indicators.analizar(normalized_json)
        periodo = inds.get("periodo", "")
        por_mes: dict = inds.get("por_mes", {})

        contexto_cualitativo: dict = {}
        resumen_alertas: list = []
        any_chunk_retrieved = False

        for mes, mes_ind in por_mes.items():
            queries = _generar_queries(mes, periodo, mes_ind)
            chunks_relevantes: list[dict] = []

            if self._vs is not None:
                seen_ids: set[str] = set()
                candidatos = []
                for q in queries:
                    for r in self._vs.search(q, cliente_id, n_results=3):
                        if r.chunk_id not in seen_ids:
                            seen_ids.add(r.chunk_id)
                            candidatos.append(r)
                candidatos.sort(key=lambda r: r.score, reverse=True)
                top = candidatos[:8]
                if top:
                    any_chunk_retrieved = True
                chunks_relevantes = [
                    {
                        "texto": r.texto,
                        "score": r.score,
                        "filename": r.filename,
                        "chunk_index": r.chunk_index,
                    }
                    for r in top
                ]

            contexto_cualitativo[mes] = {
                "queries_usadas": queries,
                "chunks_relevantes": chunks_relevantes,
            }

            for alerta in mes_ind.get("alertas", []):
                resumen_alertas.append({"mes": mes, "alerta": alerta})

        has_data = len(por_mes) > 0
        if self._vs is None:
            listo = has_data
        else:
            listo = has_data and any_chunk_retrieved

        return AnalysisPackage(
            cliente_id=cliente_id,
            periodo=periodo,
            generated_at=datetime.now(timezone.utc).isoformat(),
            indicadores=inds,
            contexto_cualitativo=contexto_cualitativo,
            resumen_alertas=resumen_alertas,
            listo_para_recomendaciones=listo,
        )

    # ── Convenience ───────────────────────────────────────────────────────────

    def ingest_and_analyze(
        self,
        financial_filepath,
        qualitative_filepaths,
        cliente_id: str,
        store,
        vector_store,
    ) -> AnalysisPackage:
        """
        Full pipeline: normalize financial file → ingest qualitative docs →
        analyze and return AnalysisPackage.
        """
        from . import normalizer
        from . import ingestion

        normalized = normalizer.normalize(financial_filepath, cliente_id)
        for path in qualitative_filepaths:
            ingestion.ingest(path, cliente_id, store, vector_store)
        return self.analyze(normalized, cliente_id)


# ── Private helpers ────────────────────────────────────────────────────────────

def _generar_queries(mes: str, periodo: str, indicadores_mes: dict) -> list[str]:
    """
    Build 4–8 search queries for a month based on its indicator values.
    4 base queries are always included; conditionals fire when thresholds are breached.
    """
    rent = indicadores_mes["rentabilidad"]
    ec = indicadores_mes["estructura_costos"]
    sucursales = indicadores_mes["sucursales"]

    queries: list[str] = [
        f"estrategia comercial {periodo}",
        f"contexto operativo {mes}",
        f"desempeño ventas {mes}",
        f"resultados financieros {periodo}",
    ]

    if rent["alerta_margen_bruto"]:
        queries.append(f"margen bruto bajo causas {mes}")
    if rent["alerta_ebitda"]:
        queries.append(f"EBITDA bajo eficiencia operativa {mes}")
    alert_grps = [g for g, s in sucursales.items() if s["alerta_margen"]]
    if alert_grps:
        queries.append(f"sucursal {alert_grps[0]} problemas operativos rentabilidad")
    if ec["nomina_sobre_ventas"] > 0.30:
        queries.append("costos laborales nómina eficiencia")
    if ec["gastos_op_sobre_ventas"] > 0.40:
        queries.append("gastos operativos reduccion eficiencia")

    return queries
