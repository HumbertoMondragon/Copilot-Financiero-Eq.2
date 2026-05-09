"""
Tests for the financial_normalizer/ingestion/ package.
All file I/O uses tmp_path so no binary fixtures are needed.
"""
import pytest

from financial_normalizer.ingestion import DocumentLoadError, ingest
from financial_normalizer.ingestion.document_loader import Document, load_document
from financial_normalizer.ingestion.chunker import Chunk, chunk_document
from financial_normalizer.ingestion.document_store import DocumentStore


# ── Shared fixtures ───────────────────────────────────────────────────────────

SAMPLE_TXT = """\
REPORTE FINANCIERO EJECUTIVO - ENERO 2026

Este reporte presenta el análisis financiero completo del período enero 2026.
Las ventas totales alcanzaron un nivel satisfactorio comparado con el año anterior.

RESUMEN DE VENTAS

El grupo A registró el mayor volumen de ventas en el período analizado.
Las categorías de alimentos y bebidas representan la mayor parte de los ingresos.
Se observa una tendencia positiva en los márgenes de contribución por grupo.

ANÁLISIS DE EGRESOS

Los costos operativos se mantuvieron dentro de los parámetros presupuestados.
La nómina representa el rubro de mayor egreso dentro de los gastos de operación.
Los gastos financieros se redujeron en comparación con el período anterior.

INDICADORES CLAVE

El margen EBITDA superó el umbral mínimo establecido en las políticas internas.
La rentabilidad neta refleja una mejora sostenida en la eficiencia operativa.
Se recomienda mantener la estrategia de control de costos implementada.

CONCLUSIONES

El período enero 2026 cierra con resultados positivos en todos los indicadores.
La dirección financiera propone continuar con el plan de expansión aprobado.
Se adjuntan los estados financieros detallados como soporte de este reporte.
"""

SAMPLE_MD = """\
# Análisis Financiero - Enero 2026

Resumen ejecutivo del período con los principales hallazgos financieros.

## Ventas por Grupo

El grupo A lideró las ventas con una participación del cuarenta por ciento.
Los grupos B y C mostraron crecimiento sostenido respecto al trimestre anterior.
El grupo D presentó el margen más alto de toda la red de sucursales del período.
Las ventas totales consolidadas superaron el presupuesto anual establecido.

## Egresos y Costos

Los costos de ventas se mantuvieron estables en relación a los ingresos totales.
La nómina consolidada representó el principal componente de los gastos operativos.
Se implementaron medidas de eficiencia que redujeron los gastos administrativos.
Los viáticos y gastos comerciales presentaron variaciones mínimas respecto al plan.

## EBITDA y Rentabilidad

El EBITDA consolidado superó el umbral mínimo del diez por ciento sobre ventas.
El margen neto refleja la capacidad de generación de valor para los accionistas.
Los indicadores de rentabilidad se encuentran alineados con los objetivos anuales.
Se proyecta mantener los márgenes actuales durante el resto del ejercicio fiscal.

## Alertas y Recomendaciones

No se registraron alertas críticas en ninguno de los grupos durante el período.
Se sugiere monitorear de cerca la evolución del grupo A en los próximos meses.
El comité financiero aprobó el presupuesto revisado para el segundo trimestre.
"""


# ── load_document ─────────────────────────────────────────────────────────────

class TestLoadDocument:

    def test_loads_txt_file(self, tmp_path):
        f = tmp_path / "report.txt"
        f.write_text(SAMPLE_TXT, encoding="utf-8")
        doc = load_document(f, "cliente_abc")
        assert isinstance(doc, Document)

    def test_loads_md_file(self, tmp_path):
        f = tmp_path / "report.md"
        f.write_text(SAMPLE_MD, encoding="utf-8")
        doc = load_document(f, "cliente_abc")
        assert isinstance(doc, Document)

    def test_doc_id_is_string(self, tmp_path):
        f = tmp_path / "report.txt"
        f.write_text(SAMPLE_TXT, encoding="utf-8")
        doc = load_document(f, "cliente_abc")
        assert isinstance(doc.doc_id, str)
        assert len(doc.doc_id) > 0

    def test_doc_id_unique_per_call(self, tmp_path):
        f = tmp_path / "report.txt"
        f.write_text(SAMPLE_TXT, encoding="utf-8")
        doc1 = load_document(f, "c1")
        doc2 = load_document(f, "c1")
        assert doc1.doc_id != doc2.doc_id

    def test_filename_matches(self, tmp_path):
        f = tmp_path / "informe_enero.txt"
        f.write_text(SAMPLE_TXT, encoding="utf-8")
        doc = load_document(f, "c1")
        assert doc.filename == "informe_enero.txt"

    def test_cliente_id_propagated(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text(SAMPLE_TXT, encoding="utf-8")
        doc = load_document(f, "empresa_xyz")
        assert doc.cliente_id == "empresa_xyz"

    def test_texto_completo_content(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text(SAMPLE_TXT, encoding="utf-8")
        doc = load_document(f, "c1")
        assert "REPORTE FINANCIERO" in doc.texto_completo

    def test_tipo_texto_for_txt(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text(SAMPLE_TXT, encoding="utf-8")
        doc = load_document(f, "c1")
        assert doc.tipo == "texto"

    def test_tipo_texto_for_md(self, tmp_path):
        f = tmp_path / "r.md"
        f.write_text(SAMPLE_MD, encoding="utf-8")
        doc = load_document(f, "c1")
        assert doc.tipo == "texto"

    def test_metadata_has_filepath(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text(SAMPLE_TXT, encoding="utf-8")
        doc = load_document(f, "c1")
        assert "filepath" in doc.metadata

    def test_metadata_has_size_bytes(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text(SAMPLE_TXT, encoding="utf-8")
        doc = load_document(f, "c1")
        assert doc.metadata["size_bytes"] > 0

    def test_created_at_is_string(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text(SAMPLE_TXT, encoding="utf-8")
        doc = load_document(f, "c1")
        assert isinstance(doc.created_at, str)

    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(DocumentLoadError):
            load_document(tmp_path / "nonexistent.txt", "c1")

    def test_unsupported_type_raises(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b,c", encoding="utf-8")
        with pytest.raises(DocumentLoadError, match="Unsupported"):
            load_document(f, "c1")


# ── chunk_document ────────────────────────────────────────────────────────────

class TestChunkDocument:

    def _make_doc(self, tmp_path, content: str, name: str = "r.txt") -> "Document":
        f = tmp_path / name
        f.write_text(content, encoding="utf-8")
        return load_document(f, "c1")

    # --- Basic structure ---

    def test_returns_list(self, tmp_path):
        doc = self._make_doc(tmp_path, SAMPLE_TXT)
        chunks = chunk_document(doc)
        assert isinstance(chunks, list)

    def test_chunks_are_chunk_instances(self, tmp_path):
        doc = self._make_doc(tmp_path, SAMPLE_TXT)
        chunks = chunk_document(doc)
        assert all(isinstance(c, Chunk) for c in chunks)

    def test_at_least_one_chunk_for_nonempty_doc(self, tmp_path):
        doc = self._make_doc(tmp_path, SAMPLE_TXT)
        chunks = chunk_document(doc)
        assert len(chunks) >= 1

    def test_empty_document_returns_empty_list(self, tmp_path):
        doc = self._make_doc(tmp_path, "   \n  ")
        chunks = chunk_document(doc)
        assert chunks == []

    def test_chunk_ids_are_unique(self, tmp_path):
        doc = self._make_doc(tmp_path, SAMPLE_TXT)
        chunks = chunk_document(doc)
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))

    def test_chunk_doc_id_matches_document(self, tmp_path):
        doc = self._make_doc(tmp_path, SAMPLE_TXT)
        chunks = chunk_document(doc)
        assert all(c.doc_id == doc.doc_id for c in chunks)

    def test_chunk_cliente_id_matches_document(self, tmp_path):
        doc = self._make_doc(tmp_path, SAMPLE_TXT)
        chunks = chunk_document(doc)
        assert all(c.cliente_id == doc.cliente_id for c in chunks)

    def test_chunk_metadata_has_index(self, tmp_path):
        doc = self._make_doc(tmp_path, SAMPLE_TXT)
        chunks = chunk_document(doc)
        for i, c in enumerate(chunks):
            assert c.metadata["chunk_index"] == i

    def test_chunk_metadata_has_positions(self, tmp_path):
        doc = self._make_doc(tmp_path, SAMPLE_TXT)
        chunks = chunk_document(doc)
        for c in chunks:
            assert "start_char" in c.metadata
            assert "end_char" in c.metadata

    # --- Size constraints ---

    def test_chunk_size_respected(self, tmp_path):
        # long single paragraph — no sentence boundaries between capitals
        long_text = ("A" * 400 + ". ") * 5  # 2010 chars, multiple sentence boundaries
        doc = self._make_doc(tmp_path, long_text)
        chunks = chunk_document(doc, chunk_size=200, chunk_overlap=0)
        # Each core chunk (before overlap) should be reasonably bounded
        # Allow up to 1.5× chunk_size because sentence boundary search may extend slightly
        for c in chunks:
            assert len(c.texto) <= 300

    def test_large_doc_produces_multiple_chunks(self, tmp_path):
        doc = self._make_doc(tmp_path, SAMPLE_TXT)
        chunks = chunk_document(doc, chunk_size=200, chunk_overlap=0)
        assert len(chunks) >= 2

    def test_two_paragraph_doc_splits_into_two(self, tmp_path):
        text = "X" * 300 + "\n\n" + "Y" * 300
        doc = self._make_doc(tmp_path, text)
        chunks = chunk_document(doc, chunk_size=500, chunk_overlap=0)
        assert len(chunks) == 2

    # --- Overlap ---

    def test_overlap_prefix_present(self, tmp_path):
        text = "X" * 300 + "\n\n" + "Y" * 300
        doc = self._make_doc(tmp_path, text)
        chunks = chunk_document(doc, chunk_size=500, chunk_overlap=50)
        assert len(chunks) == 2
        # Second chunk should start with the tail of the first chunk's core
        tail = "X" * 50
        assert chunks[1].texto.startswith(tail)

    def test_no_overlap_when_zero(self, tmp_path):
        text = "X" * 300 + "\n\n" + "Y" * 300
        doc = self._make_doc(tmp_path, text)
        chunks = chunk_document(doc, chunk_size=500, chunk_overlap=0)
        assert chunks[1].texto.startswith("Y")

    # --- Markdown splitting ---

    def test_md_headers_produce_separate_chunks(self, tmp_path):
        doc = self._make_doc(tmp_path, SAMPLE_MD, name="r.md")
        chunks = chunk_document(doc, chunk_size=500, chunk_overlap=0)
        assert len(chunks) >= 2

    def test_md_chunk_contains_header(self, tmp_path):
        doc = self._make_doc(tmp_path, SAMPLE_MD, name="r.md")
        chunks = chunk_document(doc, chunk_size=500, chunk_overlap=0)
        header_chunks = [c for c in chunks if "##" in c.texto]
        assert len(header_chunks) >= 1

    # --- Content preservation ---

    def test_all_text_covered(self, tmp_path):
        text = "Hello world. " * 100
        doc = self._make_doc(tmp_path, text)
        chunks = chunk_document(doc, chunk_size=200, chunk_overlap=0)
        combined = " ".join(c.texto for c in chunks)
        # Every word in the original should appear somewhere in the chunks
        for word in ["Hello", "world"]:
            assert word in combined


# ── DocumentStore ─────────────────────────────────────────────────────────────

class TestDocumentStore:

    def _make_doc_and_chunks(self, tmp_path, content=SAMPLE_TXT, cliente="c1"):
        f = tmp_path / "r.txt"
        f.write_text(content, encoding="utf-8")
        doc = load_document(f, cliente)
        chunks = chunk_document(doc)
        return doc, chunks

    # --- add / get ---

    def test_add_and_retrieve_document(self, tmp_path):
        store = DocumentStore()
        doc, chunks = self._make_doc_and_chunks(tmp_path)
        store.add_document(doc)
        assert store.get_document(doc.doc_id) is doc

    def test_get_missing_document_returns_none(self):
        store = DocumentStore()
        assert store.get_document("nonexistent") is None

    def test_add_chunks_and_get(self, tmp_path):
        store = DocumentStore()
        doc, chunks = self._make_doc_and_chunks(tmp_path)
        store.add_document(doc)
        store.add_chunks(chunks)
        retrieved = store.get_chunks(doc.doc_id)
        assert len(retrieved) == len(chunks)

    def test_get_chunks_missing_doc_returns_empty(self):
        store = DocumentStore()
        assert store.get_chunks("missing") == []

    # --- list_documents ---

    def test_list_documents_all(self, tmp_path):
        store = DocumentStore()
        doc1, _ = self._make_doc_and_chunks(tmp_path, cliente="c1")
        f2 = tmp_path / "r2.txt"
        f2.write_text(SAMPLE_TXT, encoding="utf-8")
        doc2 = load_document(f2, "c2")
        store.add_document(doc1)
        store.add_document(doc2)
        assert len(store.list_documents()) == 2

    def test_list_documents_filtered_by_cliente(self, tmp_path):
        store = DocumentStore()
        doc1, _ = self._make_doc_and_chunks(tmp_path, cliente="clienteX")
        f2 = tmp_path / "r2.txt"
        f2.write_text(SAMPLE_TXT, encoding="utf-8")
        doc2 = load_document(f2, "clienteY")
        store.add_document(doc1)
        store.add_document(doc2)
        result = store.list_documents(cliente_id="clienteX")
        assert len(result) == 1
        assert result[0].cliente_id == "clienteX"

    # --- retrieve ---

    def test_retrieve_returns_matching_chunks(self, tmp_path):
        store = DocumentStore()
        doc, chunks = self._make_doc_and_chunks(tmp_path)
        store.add_document(doc)
        store.add_chunks(chunks)
        results = store.retrieve("EBITDA")
        assert len(results) >= 1
        assert all("ebitda" in r.texto.lower() for r in results)

    def test_retrieve_top_k_respected(self, tmp_path):
        store = DocumentStore()
        doc, chunks = self._make_doc_and_chunks(tmp_path)
        store.add_document(doc)
        store.add_chunks(chunks)
        results = store.retrieve("el", top_k=2)
        assert len(results) <= 2

    def test_retrieve_no_match_returns_empty(self, tmp_path):
        store = DocumentStore()
        doc, chunks = self._make_doc_and_chunks(tmp_path)
        store.add_document(doc)
        store.add_chunks(chunks)
        results = store.retrieve("XYZNONEXISTENTTERM12345")
        assert results == []

    def test_retrieve_filtered_by_cliente(self, tmp_path):
        store = DocumentStore()
        doc1, chunks1 = self._make_doc_and_chunks(tmp_path, cliente="target")
        f2 = tmp_path / "r2.txt"
        f2.write_text(SAMPLE_TXT, encoding="utf-8")
        doc2 = load_document(f2, "other")
        chunks2 = chunk_document(doc2)
        store.add_document(doc1)
        store.add_chunks(chunks1)
        store.add_document(doc2)
        store.add_chunks(chunks2)
        results = store.retrieve("EBITDA", cliente_id="target")
        assert all(c.cliente_id == "target" for c in results)

    # --- clear ---

    def test_clear_empties_store(self, tmp_path):
        store = DocumentStore()
        doc, chunks = self._make_doc_and_chunks(tmp_path)
        store.add_document(doc)
        store.add_chunks(chunks)
        store.clear()
        assert store.list_documents() == []
        assert store.get_chunks(doc.doc_id) == []

    # --- stats ---

    def test_stats_empty_store(self):
        store = DocumentStore()
        s = store.stats()
        assert s["total_documents"] == 0
        assert s["total_chunks"] == 0

    def test_stats_after_ingest(self, tmp_path):
        store = DocumentStore()
        doc, chunks = self._make_doc_and_chunks(tmp_path)
        store.add_document(doc)
        store.add_chunks(chunks)
        s = store.stats()
        assert s["total_documents"] == 1
        assert s["total_chunks"] == len(chunks)

    def test_stats_documents_by_cliente(self, tmp_path):
        store = DocumentStore()
        doc1, _ = self._make_doc_and_chunks(tmp_path, cliente="alpha")
        f2 = tmp_path / "r2.txt"
        f2.write_text(SAMPLE_TXT, encoding="utf-8")
        doc2 = load_document(f2, "alpha")
        store.add_document(doc1)
        store.add_document(doc2)
        s = store.stats()
        assert s["documents_by_cliente"]["alpha"] == 2


# ── ingest (integration) ───────────────────────────────────────────────────────

class TestIngest:

    def test_ingest_returns_dict(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text(SAMPLE_TXT, encoding="utf-8")
        store = DocumentStore()
        result = ingest(f, "c1", store)
        assert isinstance(result, dict)

    def test_ingest_result_keys(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text(SAMPLE_TXT, encoding="utf-8")
        store = DocumentStore()
        result = ingest(f, "c1", store)
        for key in ("doc_id", "filename", "cliente_id", "chunks_created", "texto_length"):
            assert key in result

    def test_ingest_cliente_id_propagated(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text(SAMPLE_TXT, encoding="utf-8")
        store = DocumentStore()
        result = ingest(f, "empresa_test", store)
        assert result["cliente_id"] == "empresa_test"

    def test_ingest_chunks_created_positive(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text(SAMPLE_TXT, encoding="utf-8")
        store = DocumentStore()
        result = ingest(f, "c1", store)
        assert result["chunks_created"] > 0

    def test_ingest_texto_length_matches(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text(SAMPLE_TXT, encoding="utf-8")
        store = DocumentStore()
        result = ingest(f, "c1", store)
        assert result["texto_length"] == len(SAMPLE_TXT)

    def test_ingest_stores_document(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text(SAMPLE_TXT, encoding="utf-8")
        store = DocumentStore()
        result = ingest(f, "c1", store)
        assert store.get_document(result["doc_id"]) is not None

    def test_ingest_stores_chunks(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text(SAMPLE_TXT, encoding="utf-8")
        store = DocumentStore()
        result = ingest(f, "c1", store)
        assert len(store.get_chunks(result["doc_id"])) == result["chunks_created"]

    def test_ingest_md_file(self, tmp_path):
        f = tmp_path / "r.md"
        f.write_text(SAMPLE_MD, encoding="utf-8")
        store = DocumentStore()
        result = ingest(f, "c1", store)
        assert result["chunks_created"] > 0

    def test_ingest_missing_file_raises(self, tmp_path):
        store = DocumentStore()
        with pytest.raises(DocumentLoadError):
            ingest(tmp_path / "missing.txt", "c1", store)

    def test_ingest_stats_updated(self, tmp_path):
        f = tmp_path / "r.txt"
        f.write_text(SAMPLE_TXT, encoding="utf-8")
        store = DocumentStore()
        result = ingest(f, "c1", store)
        s = store.stats()
        assert s["total_documents"] == 1
        assert s["total_chunks"] == result["chunks_created"]
