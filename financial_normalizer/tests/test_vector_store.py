"""
Tests for financial_normalizer/ingestion/vector_store.py.

These tests load the sentence-transformers model on first run (~10-30 s).
Each test class creates a fresh VectorStore in a tmp_path directory so
tests are fully isolated and leave no state in the repo.
"""
import pytest

from financial_normalizer.ingestion import DocumentLoadError, ingest
from financial_normalizer.ingestion.document_loader import load_document
from financial_normalizer.ingestion.chunker import chunk_document
from financial_normalizer.ingestion.document_store import DocumentStore
from financial_normalizer.ingestion.vector_store import VectorStore, SearchResult


# ── Shared fixtures ───────────────────────────────────────────────────────────

SAMPLE_A = """\
REPORTE FINANCIERO - CLIENTE ALFA

El grupo A registró ventas superiores al presupuesto establecido para el período.
Las categorías de alimentos y bebidas representan la mayor parte de los ingresos.
El margen EBITDA superó el umbral mínimo establecido en las políticas internas.
La rentabilidad neta refleja una mejora sostenida en la eficiencia operativa.
Se recomienda mantener la estrategia de control de costos implementada este período.
Los indicadores de liquidez se encuentran dentro de los parámetros esperados.
"""

SAMPLE_B = """\
INFORME EJECUTIVO - CLIENTE BETA

Las ventas consolidadas mostraron una tendencia positiva durante el trimestre.
El margen bruto se mantuvo estable en comparación con el período anterior.
Los gastos operativos presentaron una reducción significativa respecto al plan.
La nómina representó el principal componente del gasto de operación total.
Se implementaron medidas de eficiencia que redujeron los gastos administrativos.
Los indicadores financieros reflejan una gestión adecuada de los recursos.
"""


def _make_chunks(tmp_path, content: str, cliente: str, filename: str = "r.txt"):
    f = tmp_path / filename
    f.write_text(content, encoding="utf-8")
    doc = load_document(f, cliente)
    return doc, chunk_document(doc)


# ── VectorStore basic tests ───────────────────────────────────────────────────

class TestVectorStoreAddAndSearch:

    @pytest.fixture
    def vs(self, tmp_path):
        return VectorStore(persist_directory=str(tmp_path / "chroma"), collection_name="test")

    @pytest.fixture
    def loaded(self, tmp_path, vs):
        doc, chunks = _make_chunks(tmp_path, SAMPLE_A, "cliente_a")
        vs.add_chunks(chunks)
        return vs, doc, chunks

    def test_search_returns_list(self, loaded):
        vs, doc, chunks = loaded
        results = vs.search("EBITDA margen", "cliente_a")
        assert isinstance(results, list)

    def test_search_returns_search_result_instances(self, loaded):
        vs, doc, chunks = loaded
        results = vs.search("EBITDA margen", "cliente_a")
        assert all(isinstance(r, SearchResult) for r in results)

    def test_search_finds_relevant_chunk(self, loaded):
        vs, doc, chunks = loaded
        results = vs.search("EBITDA margen rentabilidad", "cliente_a")
        assert len(results) >= 1

    def test_search_score_between_zero_and_one(self, loaded):
        vs, doc, chunks = loaded
        results = vs.search("ventas alimentos bebidas", "cliente_a")
        for r in results:
            assert 0.0 <= r.score <= 1.0

    def test_search_result_fields_populated(self, loaded, tmp_path):
        vs, doc, chunks = loaded
        results = vs.search("margen EBITDA", "cliente_a")
        assert len(results) >= 1
        r = results[0]
        assert isinstance(r.chunk_id, str) and r.chunk_id
        assert isinstance(r.texto, str) and r.texto
        assert r.cliente_id == "cliente_a"
        assert r.filename == "r.txt"
        assert isinstance(r.chunk_index, int)

    def test_search_n_results_respected(self, loaded):
        vs, doc, chunks = loaded
        results = vs.search("ventas", "cliente_a", n_results=1)
        assert len(results) <= 1

    def test_search_empty_store_returns_empty(self, vs):
        results = vs.search("cualquier consulta", "cliente_x")
        assert results == []


# ── Client isolation ──────────────────────────────────────────────────────────

class TestVectorStoreClientIsolation:

    @pytest.fixture
    def vs_with_two_clients(self, tmp_path):
        vs = VectorStore(persist_directory=str(tmp_path / "chroma"), collection_name="test")
        doc_a, chunks_a = _make_chunks(tmp_path, SAMPLE_A, "cliente_a", "a.txt")
        doc_b, chunks_b = _make_chunks(tmp_path, SAMPLE_B, "cliente_b", "b.txt")
        vs.add_chunks(chunks_a)
        vs.add_chunks(chunks_b)
        return vs, chunks_a, chunks_b

    def test_search_only_returns_own_client(self, vs_with_two_clients):
        vs, chunks_a, chunks_b = vs_with_two_clients
        results = vs.search("ventas margen", "cliente_a")
        assert all(r.cliente_id == "cliente_a" for r in results)

    def test_search_b_does_not_see_a_chunks(self, vs_with_two_clients):
        vs, chunks_a, chunks_b = vs_with_two_clients
        results = vs.search("ventas margen", "cliente_b")
        assert all(r.cliente_id == "cliente_b" for r in results)

    def test_search_unknown_client_returns_empty(self, vs_with_two_clients):
        vs, _, _ = vs_with_two_clients
        results = vs.search("ventas margen", "cliente_inexistente")
        assert results == []


# ── delete_by_cliente ─────────────────────────────────────────────────────────

class TestVectorStoreDelete:

    @pytest.fixture
    def vs_with_two_clients(self, tmp_path):
        vs = VectorStore(persist_directory=str(tmp_path / "chroma"), collection_name="test")
        doc_a, chunks_a = _make_chunks(tmp_path, SAMPLE_A, "cliente_a", "a.txt")
        doc_b, chunks_b = _make_chunks(tmp_path, SAMPLE_B, "cliente_b", "b.txt")
        vs.add_chunks(chunks_a)
        vs.add_chunks(chunks_b)
        return vs

    def test_delete_removes_target_client(self, vs_with_two_clients):
        vs = vs_with_two_clients
        vs.delete_by_cliente("cliente_a")
        results = vs.search("ventas margen", "cliente_a")
        assert results == []

    def test_delete_keeps_other_client(self, vs_with_two_clients):
        vs = vs_with_two_clients
        vs.delete_by_cliente("cliente_a")
        results = vs.search("ventas margen", "cliente_b")
        assert len(results) >= 1

    def test_delete_nonexistent_client_no_error(self, vs_with_two_clients):
        vs = vs_with_two_clients
        vs.delete_by_cliente("no_existe")  # must not raise

    def test_stats_updated_after_delete(self, vs_with_two_clients, tmp_path):
        vs = vs_with_two_clients
        before = vs.stats()["total_chunks"]
        vs.delete_by_cliente("cliente_a")
        after = vs.stats()["total_chunks"]
        assert after < before


# ── stats ─────────────────────────────────────────────────────────────────────

class TestVectorStoreStats:

    def test_stats_empty_store(self, tmp_path):
        vs = VectorStore(persist_directory=str(tmp_path / "chroma"), collection_name="test")
        s = vs.stats()
        assert s["total_chunks"] == 0
        assert s["by_cliente"] == {}

    def test_stats_counts_chunks(self, tmp_path):
        vs = VectorStore(persist_directory=str(tmp_path / "chroma"), collection_name="test")
        doc, chunks = _make_chunks(tmp_path, SAMPLE_A, "cliente_a")
        vs.add_chunks(chunks)
        s = vs.stats()
        assert s["total_chunks"] == len(chunks)
        assert s["by_cliente"]["cliente_a"] == len(chunks)

    def test_stats_two_clients(self, tmp_path):
        vs = VectorStore(persist_directory=str(tmp_path / "chroma"), collection_name="test")
        doc_a, chunks_a = _make_chunks(tmp_path, SAMPLE_A, "cliente_a", "a.txt")
        doc_b, chunks_b = _make_chunks(tmp_path, SAMPLE_B, "cliente_b", "b.txt")
        vs.add_chunks(chunks_a)
        vs.add_chunks(chunks_b)
        s = vs.stats()
        assert s["total_chunks"] == len(chunks_a) + len(chunks_b)
        assert s["by_cliente"]["cliente_a"] == len(chunks_a)
        assert s["by_cliente"]["cliente_b"] == len(chunks_b)


# ── upsert (no duplicates) ────────────────────────────────────────────────────

class TestVectorStoreUpsert:

    def test_upsert_same_chunks_no_duplicate(self, tmp_path):
        vs = VectorStore(persist_directory=str(tmp_path / "chroma"), collection_name="test")
        doc, chunks = _make_chunks(tmp_path, SAMPLE_A, "cliente_a")
        vs.add_chunks(chunks)
        count_before = vs.stats()["total_chunks"]
        vs.add_chunks(chunks)  # add same chunks again
        count_after = vs.stats()["total_chunks"]
        assert count_after == count_before


# ── ingest() integration ──────────────────────────────────────────────────────

class TestIngestWithVectorStore:

    def test_ingest_with_vector_store_returns_embeddings_stored_true(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text(SAMPLE_A, encoding="utf-8")
        store = DocumentStore()
        vs = VectorStore(persist_directory=str(tmp_path / "chroma"), collection_name="test")
        result = ingest(f, "cliente_a", store, vector_store=vs)
        assert result["embeddings_stored"] is True

    def test_ingest_without_vector_store_returns_embeddings_stored_false(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text(SAMPLE_A, encoding="utf-8")
        store = DocumentStore()
        result = ingest(f, "cliente_a", store)
        assert result["embeddings_stored"] is False

    def test_ingest_chunks_searchable_via_vector_store(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text(SAMPLE_A, encoding="utf-8")
        store = DocumentStore()
        vs = VectorStore(persist_directory=str(tmp_path / "chroma"), collection_name="test")
        ingest(f, "cliente_a", store, vector_store=vs)
        results = vs.search("EBITDA rentabilidad", "cliente_a")
        assert len(results) >= 1

    def test_ingest_vector_store_stats_updated(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text(SAMPLE_A, encoding="utf-8")
        store = DocumentStore()
        vs = VectorStore(persist_directory=str(tmp_path / "chroma"), collection_name="test")
        result = ingest(f, "cliente_a", store, vector_store=vs)
        s = vs.stats()
        assert s["total_chunks"] == result["chunks_created"]
