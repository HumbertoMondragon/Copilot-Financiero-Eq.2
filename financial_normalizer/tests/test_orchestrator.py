"""
Tests for financial_normalizer/orchestrator.py.

Most tests mock vector_store and heavy dependencies so they run in milliseconds.
The ingest_and_analyze test patches normalizer.normalize and ingestion.ingest
to verify the call sequence without touching the filesystem or the LLM.
"""
import pytest
from dataclasses import fields
from unittest.mock import MagicMock, patch, call

from financial_normalizer.orchestrator import AnalysisOrchestrator, AnalysisPackage
from financial_normalizer.ingestion.vector_store import SearchResult
from financial_normalizer.tests.fixtures import build_normalized_doc
from financial_normalizer.profiles import empty_month


# ── Shared helpers ────────────────────────────────────────────────────────────

def _low_margin_doc() -> dict:
    """Normalized doc whose single month triggers all alert types."""
    mes = empty_month()
    mes["kpis"]["total_ventas"] = 1_000_000.0
    mes["kpis"]["margen_bruto"] = 0.30     # < UMBRAL_MARGEN_BRUTO (0.40)
    mes["kpis"]["margen_ebitda"] = 0.04    # < UMBRAL_EBITDA (0.10)
    mes["kpis"]["margen_neto"] = 0.02      # < UMBRAL_MARGEN_NETO (0.05)
    mes["ventas"]["A"]["total"] = 500_000.0
    mes["egresos"]["A"]["total"] = 400_000.0  # sucursal A margen 0.20 < 0.40
    return {"cliente_id": "c1", "periodo": "2026", "meses": {"ENERO 2026": mes}}


def _make_search_result(chunk_id: str, score: float = 0.85) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        texto=f"texto del chunk {chunk_id}",
        score=score,
        cliente_id="c1",
        filename="doc.txt",
        chunk_index=0,
    )


def _mock_vs_returning(results_per_call: list[list[SearchResult]]) -> MagicMock:
    """VS mock whose search() returns successive lists from results_per_call."""
    vs = MagicMock()
    vs.search.side_effect = results_per_call
    return vs


def _mock_vs_empty() -> MagicMock:
    vs = MagicMock()
    vs.search.return_value = []
    return vs


# ── AnalysisPackage structure ─────────────────────────────────────────────────

class TestAnalysisPackageFields:

    def test_all_required_fields_present(self):
        doc = build_normalized_doc()
        pkg = AnalysisOrchestrator().analyze(doc, "test_client")
        field_names = {f.name for f in fields(pkg)}
        for required in (
            "cliente_id", "periodo", "generated_at",
            "indicadores", "contexto_cualitativo",
            "resumen_alertas", "listo_para_recomendaciones",
        ):
            assert required in field_names

    def test_cliente_id_propagated(self):
        doc = build_normalized_doc()
        pkg = AnalysisOrchestrator().analyze(doc, "test_client")
        assert pkg.cliente_id == "test_client"

    def test_periodo_propagated(self):
        doc = build_normalized_doc()
        pkg = AnalysisOrchestrator().analyze(doc, "test_client")
        assert pkg.periodo == "2026"

    def test_generated_at_is_iso_string(self):
        doc = build_normalized_doc()
        pkg = AnalysisOrchestrator().analyze(doc, "test_client")
        assert isinstance(pkg.generated_at, str)
        assert "T" in pkg.generated_at   # ISO-8601 datetime

    def test_indicadores_has_por_mes(self):
        doc = build_normalized_doc()
        pkg = AnalysisOrchestrator().analyze(doc, "test_client")
        assert "por_mes" in pkg.indicadores

    def test_contexto_cualitativo_has_month_key(self):
        doc = build_normalized_doc()
        pkg = AnalysisOrchestrator().analyze(doc, "test_client")
        assert "ENERO 2026" in pkg.contexto_cualitativo

    def test_contexto_cualitativo_month_has_expected_keys(self):
        doc = build_normalized_doc()
        pkg = AnalysisOrchestrator().analyze(doc, "test_client")
        entry = pkg.contexto_cualitativo["ENERO 2026"]
        assert "queries_usadas" in entry
        assert "chunks_relevantes" in entry


# ── analyze() — indicators integration ───────────────────────────────────────

class TestAnalyzeCallsIndicators:

    def test_calls_indicators_analizar_with_normalized_json(self):
        doc = build_normalized_doc()
        with patch("financial_normalizer.indicators.analizar") as mock_analizar:
            mock_analizar.return_value = {
                "cliente_id": "test_client",
                "periodo": "2026",
                "por_mes": {},
                "tendencias": {},
                "resumen_ejecutivo": {
                    "meses_analizados": 0,
                    "mejor_mes_ebitda": None,
                    "peor_mes_ebitda": None,
                    "mejor_sucursal_promedio": None,
                    "peor_sucursal_promedio": None,
                    "total_alertas_activas": 0,
                },
            }
            AnalysisOrchestrator().analyze(doc, "test_client")
            mock_analizar.assert_called_once_with(doc)

    def test_indicadores_result_stored_in_package(self):
        doc = build_normalized_doc()
        pkg = AnalysisOrchestrator().analyze(doc, "test_client")
        assert pkg.indicadores.get("cliente_id") == "test_client"
        assert "resumen_ejecutivo" in pkg.indicadores


# ── analyze() — query generation ─────────────────────────────────────────────

class TestQueryGeneration:

    def test_generates_at_least_4_queries_per_month(self):
        doc = build_normalized_doc()
        pkg = AnalysisOrchestrator().analyze(doc, "test_client")
        queries = pkg.contexto_cualitativo["ENERO 2026"]["queries_usadas"]
        assert len(queries) >= 4

    def test_queries_are_strings(self):
        doc = build_normalized_doc()
        pkg = AnalysisOrchestrator().analyze(doc, "test_client")
        queries = pkg.contexto_cualitativo["ENERO 2026"]["queries_usadas"]
        assert all(isinstance(q, str) and q for q in queries)

    def test_always_includes_estrategia_comercial(self):
        doc = build_normalized_doc()
        pkg = AnalysisOrchestrator().analyze(doc, "test_client")
        queries = pkg.contexto_cualitativo["ENERO 2026"]["queries_usadas"]
        assert any("estrategia comercial" in q for q in queries)

    def test_always_includes_contexto_operativo(self):
        doc = build_normalized_doc()
        pkg = AnalysisOrchestrator().analyze(doc, "test_client")
        queries = pkg.contexto_cualitativo["ENERO 2026"]["queries_usadas"]
        assert any("contexto operativo" in q for q in queries)

    def test_alert_condition_adds_extra_query(self):
        doc = _low_margin_doc()
        pkg = AnalysisOrchestrator().analyze(doc, "c1")
        queries = pkg.contexto_cualitativo["ENERO 2026"]["queries_usadas"]
        assert any("margen bruto" in q.lower() for q in queries)

    def test_sucursal_alert_adds_extra_query(self):
        doc = _low_margin_doc()
        pkg = AnalysisOrchestrator().analyze(doc, "c1")
        queries = pkg.contexto_cualitativo["ENERO 2026"]["queries_usadas"]
        assert any("sucursal" in q.lower() for q in queries)

    def test_no_months_produces_empty_contexto(self):
        doc = {"cliente_id": "c1", "periodo": "2026", "meses": {}}
        pkg = AnalysisOrchestrator().analyze(doc, "c1")
        assert pkg.contexto_cualitativo == {}


# ── analyze() — no vector_store ───────────────────────────────────────────────

class TestAnalyzeNoVectorStore:

    def test_chunks_relevantes_empty_when_no_vs(self):
        doc = build_normalized_doc()
        pkg = AnalysisOrchestrator(vector_store=None).analyze(doc, "test_client")
        entry = pkg.contexto_cualitativo["ENERO 2026"]
        assert entry["chunks_relevantes"] == []

    def test_vs_not_searched_when_none(self):
        doc = build_normalized_doc()
        orch = AnalysisOrchestrator(vector_store=None)
        pkg = orch.analyze(doc, "test_client")
        # No AttributeError and no side effects — just a clean empty result
        assert pkg is not None


# ── analyze() — deduplication ─────────────────────────────────────────────────

class TestChunkDeduplication:

    def test_same_chunk_returned_by_multiple_queries_counted_once(self):
        doc = build_normalized_doc()
        # All 4+ queries return the same chunk — should appear only once
        same = _make_search_result("dup_chunk", score=0.9)
        vs = MagicMock()
        vs.search.return_value = [same]
        pkg = AnalysisOrchestrator(vector_store=vs).analyze(doc, "test_client")
        chunks = pkg.contexto_cualitativo["ENERO 2026"]["chunks_relevantes"]
        chunk_textos = [c["texto"] for c in chunks]
        assert chunk_textos.count(same.texto) == 1

    def test_deduplication_preserves_unique_chunks(self):
        doc = build_normalized_doc()
        a = _make_search_result("chunk_a", score=0.9)
        b = _make_search_result("chunk_b", score=0.8)
        vs = MagicMock()
        # First query returns both; subsequent queries return only 'a' (duplicate)
        vs.search.side_effect = [[a, b]] + [[a]] * 20
        pkg = AnalysisOrchestrator(vector_store=vs).analyze(doc, "test_client")
        chunks = pkg.contexto_cualitativo["ENERO 2026"]["chunks_relevantes"]
        ids = {c["texto"] for c in chunks}
        assert a.texto in ids
        assert b.texto in ids
        assert len(chunks) == 2


# ── analyze() — max 8 chunks ──────────────────────────────────────────────────

class TestChunkLimit:

    def test_max_8_chunks_per_month(self):
        doc = build_normalized_doc()
        # 12 unique chunks spread across queries
        all_chunks = [_make_search_result(f"c{i}", score=0.9 - i * 0.01) for i in range(12)]
        call_idx = [0]

        def next_3(q, cid, n_results=3):
            start = call_idx[0] * 3
            call_idx[0] += 1
            return all_chunks[start: start + 3]

        vs = MagicMock()
        vs.search.side_effect = next_3
        pkg = AnalysisOrchestrator(vector_store=vs).analyze(doc, "test_client")
        chunks = pkg.contexto_cualitativo["ENERO 2026"]["chunks_relevantes"]
        assert len(chunks) <= 8

    def test_chunks_sorted_by_score_descending(self):
        doc = build_normalized_doc()
        # Return 4 chunks with known scores in shuffled order
        results = [
            _make_search_result("c0", score=0.50),
            _make_search_result("c1", score=0.95),
            _make_search_result("c2", score=0.70),
            _make_search_result("c3", score=0.85),
        ]
        vs = MagicMock()
        vs.search.return_value = results
        pkg = AnalysisOrchestrator(vector_store=vs).analyze(doc, "test_client")
        scores = [c["score"] for c in pkg.contexto_cualitativo["ENERO 2026"]["chunks_relevantes"]]
        assert scores == sorted(scores, reverse=True)


# ── resumen_alertas ───────────────────────────────────────────────────────────

class TestResumenAlertas:

    def test_resumen_alertas_empty_for_healthy_data(self):
        doc = build_normalized_doc()
        pkg = AnalysisOrchestrator().analyze(doc, "test_client")
        assert pkg.resumen_alertas == []

    def test_resumen_alertas_populated_when_alerts_fire(self):
        pkg = AnalysisOrchestrator().analyze(_low_margin_doc(), "c1")
        assert len(pkg.resumen_alertas) > 0

    def test_resumen_alertas_entries_have_mes_and_alerta(self):
        pkg = AnalysisOrchestrator().analyze(_low_margin_doc(), "c1")
        for entry in pkg.resumen_alertas:
            assert "mes" in entry
            assert "alerta" in entry

    def test_resumen_alertas_contains_all_alert_types(self):
        pkg = AnalysisOrchestrator().analyze(_low_margin_doc(), "c1")
        tipos = {e["alerta"]["tipo"] for e in pkg.resumen_alertas}
        assert "margen_bruto" in tipos
        assert "ebitda" in tipos
        assert "margen_neto" in tipos
        assert "margen_sucursal" in tipos

    def test_resumen_alertas_mes_matches_month_name(self):
        pkg = AnalysisOrchestrator().analyze(_low_margin_doc(), "c1")
        meses_en_alertas = {e["mes"] for e in pkg.resumen_alertas}
        assert "ENERO 2026" in meses_en_alertas

    def test_resumen_alertas_multi_month(self):
        """Alerts from two distinct months both appear in resumen_alertas."""
        import copy
        doc = {
            "cliente_id": "c1",
            "periodo": "2026",
            "meses": {
                "ENERO 2026": copy.deepcopy(_low_margin_doc()["meses"]["ENERO 2026"]),
                "FEBRERO 2026": copy.deepcopy(_low_margin_doc()["meses"]["ENERO 2026"]),
            },
        }
        pkg = AnalysisOrchestrator().analyze(doc, "c1")
        meses_en_alertas = {e["mes"] for e in pkg.resumen_alertas}
        assert "ENERO 2026" in meses_en_alertas
        assert "FEBRERO 2026" in meses_en_alertas


# ── listo_para_recomendaciones ────────────────────────────────────────────────

class TestListoParaRecomendaciones:

    def test_true_when_has_data_and_no_vector_store(self):
        doc = build_normalized_doc()
        pkg = AnalysisOrchestrator(vector_store=None).analyze(doc, "test_client")
        assert pkg.listo_para_recomendaciones is True

    def test_false_when_no_months_have_data(self):
        doc = {"cliente_id": "c1", "periodo": "2026", "meses": {}}
        pkg = AnalysisOrchestrator(vector_store=None).analyze(doc, "c1")
        assert pkg.listo_para_recomendaciones is False

    def test_false_when_all_months_have_zero_ventas(self):
        doc = {"cliente_id": "c1", "periodo": "2026",
               "meses": {"ENERO 2026": empty_month()}}
        pkg = AnalysisOrchestrator(vector_store=None).analyze(doc, "c1")
        assert pkg.listo_para_recomendaciones is False

    def test_true_when_has_data_and_chunks_retrieved(self):
        doc = build_normalized_doc()
        vs = MagicMock()
        vs.search.return_value = [_make_search_result("c1")]
        pkg = AnalysisOrchestrator(vector_store=vs).analyze(doc, "test_client")
        assert pkg.listo_para_recomendaciones is True

    def test_false_when_has_data_but_no_chunks_retrieved(self):
        doc = build_normalized_doc()
        pkg = AnalysisOrchestrator(vector_store=_mock_vs_empty()).analyze(doc, "test_client")
        assert pkg.listo_para_recomendaciones is False


# ── ingest_and_analyze ────────────────────────────────────────────────────────

class TestIngestAndAnalyze:

    def test_calls_normalize_with_correct_args(self, tmp_path):
        doc = build_normalized_doc()
        with patch("financial_normalizer.normalizer.normalize", return_value=doc) as mock_norm, \
             patch("financial_normalizer.ingestion.ingest", return_value={}):
            AnalysisOrchestrator().ingest_and_analyze(
                "financial.xlsx", [], "c1", MagicMock(), None
            )
            mock_norm.assert_called_once_with("financial.xlsx", "c1")

    def test_calls_ingest_for_each_qualitative_file(self, tmp_path):
        doc = build_normalized_doc()
        store = MagicMock()
        qual_paths = ["doc1.txt", "doc2.txt", "doc3.txt"]
        with patch("financial_normalizer.normalizer.normalize", return_value=doc), \
             patch("financial_normalizer.ingestion.ingest", return_value={}) as mock_ingest:
            AnalysisOrchestrator().ingest_and_analyze(
                "financial.xlsx", qual_paths, "c1", store, None
            )
            assert mock_ingest.call_count == 3
            for path in qual_paths:
                mock_ingest.assert_any_call(path, "c1", store, None)

    def test_returns_analysis_package(self):
        doc = build_normalized_doc()
        with patch("financial_normalizer.normalizer.normalize", return_value=doc), \
             patch("financial_normalizer.ingestion.ingest", return_value={}):
            result = AnalysisOrchestrator().ingest_and_analyze(
                "financial.xlsx", [], "c1", MagicMock(), None
            )
            assert isinstance(result, AnalysisPackage)

    def test_normalize_called_before_ingest(self):
        """Verify normalize runs before any ingest call."""
        doc = build_normalized_doc()
        call_order: list[str] = []

        def fake_normalize(fp, cid):
            call_order.append("normalize")
            return doc

        def fake_ingest(path, cid, store, vs):
            call_order.append("ingest")
            return {}

        with patch("financial_normalizer.normalizer.normalize", side_effect=fake_normalize), \
             patch("financial_normalizer.ingestion.ingest", side_effect=fake_ingest):
            AnalysisOrchestrator().ingest_and_analyze(
                "financial.xlsx", ["q.txt"], "c1", MagicMock(), None
            )
            assert call_order.index("normalize") < call_order.index("ingest")

    def test_no_qualitative_files_skips_ingest(self):
        doc = build_normalized_doc()
        with patch("financial_normalizer.normalizer.normalize", return_value=doc), \
             patch("financial_normalizer.ingestion.ingest", return_value={}) as mock_ingest:
            AnalysisOrchestrator().ingest_and_analyze(
                "financial.xlsx", [], "c1", MagicMock(), None
            )
            mock_ingest.assert_not_called()
