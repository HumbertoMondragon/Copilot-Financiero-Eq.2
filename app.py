"""
Copilot Financiero — Demo Técnica para desarrolladores.
Muestra paso a paso qué ocurre en cada fase del pipeline:
  Fase 0: normalización, Fase 1: indicadores, Fase 2: ingesta,
  Fase 3: embeddings, Fase 4: orquestador, Fase 5: recomendaciones.
"""
from __future__ import annotations

import dataclasses
import logging
import shutil
import tempfile
import time
import traceback
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

import os
if not os.environ.get("ANTHROPIC_API_KEY"):
    st.error(
        "⚠️ No se encontró ANTHROPIC_API_KEY. "
        "Agrega tu clave al archivo .env y reinicia la aplicación."
    )
    st.stop()

from financial_normalizer import normalizer, indicators as ind_module
from financial_normalizer.validator import validate
from financial_normalizer import ingestion
from financial_normalizer.ingestion.document_store import DocumentStore
from financial_normalizer.ingestion.vector_store import VectorStore
from financial_normalizer.orchestrator import AnalysisOrchestrator
from financial_normalizer.recommendations import RecommendationEngine
from financial_normalizer.indicators import UMBRAL_MARGEN_SUCURSAL

logger = logging.getLogger(__name__)

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Demo Técnica — Copilot Financiero",
    page_icon="🔬",
    layout="wide",
)
st.title("🔬 Copilot Financiero — Demo Técnica")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _detect_file_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".xlsx", ".xls", ".xlsm"}:
        return "excel"
    if ext == ".pdf":
        try:
            import pdfplumber
            with pdfplumber.open(str(path)) as pdf:
                if not pdf.pages:
                    return "scanned"
                text = pdf.pages[0].extract_text() or ""
                return "scanned" if len(text.strip()) < 50 else "pdf"
        except Exception:
            return "pdf"
    return "unknown"


def _detect_parser(path: Path) -> str:
    t = _detect_file_type(path)
    if t == "excel":
        return "parser_excel"
    if t == "scanned":
        return "parser_pdf_escaneado"
    if t == "pdf":
        return "parser_pdf_texto"
    return "parser_llm"


def _prioridad_emoji(prioridad: str) -> str:
    return {"alta": "🔴", "media": "🟡", "baja": "🟢"}.get(prioridad, "⚪")


def _safe_json(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, dict):
        return {k: _safe_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_safe_json(v) for v in obj]
    return obj


def _rec_attr(r, key: str, default=""):
    return r.get(key, default) if isinstance(r, dict) else getattr(r, key, default)


# ── Pipeline ──────────────────────────────────────────────────────────────────

def _run_pipeline(
    fin_path: Path,
    qual_paths: list[Path],
    cliente_id: str,
    chroma_dir: str,
) -> tuple[dict, dict]:
    results: dict = {}
    errors: dict = {}

    # ── Phase 0: Normalization ────────────────────────────────────────────────
    t = time.perf_counter()
    try:
        file_type = _detect_file_type(fin_path)
        parser_used = _detect_parser(fin_path)
        norm_json = normalizer.normalize(str(fin_path), cliente_id)
        validation = validate(norm_json)
        results[0] = {
            "normalized_json": norm_json,
            "parser_used": parser_used,
            "file_type": file_type,
            "validation": validation,
            "filename": fin_path.name,
            "size_kb": round(fin_path.stat().st_size / 1024, 2),
            "time": time.perf_counter() - t,
        }
    except Exception:
        errors[0] = traceback.format_exc()
        results[0] = {"time": time.perf_counter() - t, "error": True}
        return results, errors

    # ── Phase 1: Indicators ───────────────────────────────────────────────────
    t = time.perf_counter()
    try:
        indicators_output = ind_module.analizar(results[0]["normalized_json"])
        results[1] = {
            "indicators": indicators_output,
            "time": time.perf_counter() - t,
        }
    except Exception:
        errors[1] = traceback.format_exc()
        results[1] = {"time": time.perf_counter() - t, "error": True}

    # ── Phase 2: Document ingestion ───────────────────────────────────────────
    t = time.perf_counter()
    store = DocumentStore()
    try:
        ingestion_results = []
        for qp in qual_paths:
            r = ingestion.ingest(str(qp), cliente_id, store)
            ingestion_results.append(r)
        chunks_by_doc = {
            r["doc_id"]: store.get_chunks(r["doc_id"])
            for r in ingestion_results
        }
        results[2] = {
            "ingestion_results": ingestion_results,
            "chunks_by_doc": chunks_by_doc,
            "store": store,
            "time": time.perf_counter() - t,
        }
    except Exception:
        errors[2] = traceback.format_exc()
        results[2] = {"ingestion_results": [], "chunks_by_doc": {}, "store": store,
                      "time": time.perf_counter() - t, "error": True}

    # ── Phase 3: Embeddings / VectorStore ─────────────────────────────────────
    t = time.perf_counter()
    vs = VectorStore(persist_directory=chroma_dir)
    try:
        for chunks in results[2].get("chunks_by_doc", {}).values():
            vs.add_chunks(chunks)
        results[3] = {
            "vector_store": vs,
            "time": time.perf_counter() - t,
        }
    except Exception:
        errors[3] = traceback.format_exc()
        results[3] = {"vector_store": vs, "time": time.perf_counter() - t, "error": True}

    # ── Phase 4: Orchestrator ─────────────────────────────────────────────────
    t = time.perf_counter()
    try:
        use_vs = vs if qual_paths else None
        orch = AnalysisOrchestrator(vector_store=use_vs)
        package = orch.analyze(results[0]["normalized_json"], cliente_id)
        results[4] = {
            "package": package,
            "time": time.perf_counter() - t,
        }
    except Exception:
        errors[4] = traceback.format_exc()
        results[4] = {"time": time.perf_counter() - t, "error": True}
        return results, errors

    # ── Phase 5: Recommendations ──────────────────────────────────────────────
    t = time.perf_counter()
    try:
        engine = RecommendationEngine()
        package = results[4]["package"]
        prompt_text = engine.build_prompt(package)
        report = engine.generate(package)
        results[5] = {
            "report": report,
            "prompt_text": prompt_text,
            "time": time.perf_counter() - t,
        }
    except Exception:
        errors[5] = traceback.format_exc()
        results[5] = {"time": time.perf_counter() - t, "error": True}

    return results, errors


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("⚙️ Configuración")

    financial_file = st.file_uploader(
        "Archivo financiero (Excel/PDF)",
        type=["xlsx", "xls", "xlsm", "pdf"],
    )
    qual_files = st.file_uploader(
        "Documentos cualitativos (opcional)",
        type=["pdf", "txt", "md"],
        accept_multiple_files=True,
    )
    cliente_id_input = st.text_input("cliente_id", value="demo_client")
    run_btn = st.button("▶ Ejecutar Pipeline", disabled=(financial_file is None))

    if run_btn and financial_file is not None:
        # Clean up previous run's temp dir if it exists
        prev_tmp = st.session_state.get("_tmp_dir")
        if prev_tmp and Path(prev_tmp).exists():
            shutil.rmtree(prev_tmp, ignore_errors=True)

        tmp_dir = tempfile.mkdtemp()
        st.session_state["_tmp_dir"] = tmp_dir

        try:
            fin_path = Path(tmp_dir) / financial_file.name
            fin_path.write_bytes(financial_file.getbuffer())

            qual_paths: list[Path] = []
            for qf in (qual_files or []):
                qp = Path(tmp_dir) / qf.name
                qp.write_bytes(qf.getbuffer())
                qual_paths.append(qp)

            chroma_dir = str(Path(tmp_dir) / "chroma")
            cid = cliente_id_input.strip() or "demo_client"

            with st.spinner("Ejecutando pipeline..."):
                phase_results, phase_errors = _run_pipeline(
                    fin_path, qual_paths, cid, chroma_dir
                )
                st.session_state.phase_results = phase_results
                st.session_state.phase_errors = phase_errors
        except Exception:
            st.error("Error inesperado al iniciar el pipeline.")
            st.code(traceback.format_exc())

    # Timing summary
    if st.session_state.get("phase_results"):
        st.divider()
        st.subheader("⏱ Tiempos por fase")
        pr_ = st.session_state.phase_results
        pe_ = st.session_state.get("phase_errors", {})
        phase_labels = [
            "Normalización", "Indicadores", "Ingesta docs",
            "Embeddings", "Orquestador", "Recomendaciones",
        ]
        for i, label in enumerate(phase_labels):
            if i in pr_:
                t_ = pr_[i].get("time", 0)
                icon = "❌" if i in pe_ else "✅"
                st.caption(f"{icon} Fase {i} — {label}: {t_:.2f}s")


# ── Main: Tabs ────────────────────────────────────────────────────────────────

tab0, tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["Fase 0", "Fase 1", "Fase 2", "Fase 3", "Fase 4", "Fase 5"]
)

pr = st.session_state.get("phase_results", {})
pe = st.session_state.get("phase_errors", {})


# ─────────────────────────────────────────────────────────────────────────────
# TAB 0 — Normalización
# ─────────────────────────────────────────────────────────────────────────────

with tab0:
    st.header("📥 Fase 0: Normalización de Datos")
    st.subheader("El parser convierte el archivo en un JSON estructurado")

    if 0 not in pr:
        st.info("Sube un archivo financiero y ejecuta el pipeline.")
    elif pr[0].get("error"):
        st.error("Error en Fase 0")
        st.code(pe.get(0, ""), language="python")
    else:
        d0 = pr[0]
        v = d0["validation"]

        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("**Archivo recibido**")
            st.write(d0["filename"])
            st.caption(f"{d0['size_kb']} KB")
            st.caption(f"Tipo detectado: `{d0['file_type']}`")
        with col2:
            st.markdown("**Parser usado**")
            st.code(d0["parser_used"])
        with col3:
            st.markdown("**Validación**")
            if v["valid"]:
                st.success("✅ VÁLIDO")
            else:
                st.error(f"❌ {len(v['errors'])} error(es)")
                for e in v["errors"]:
                    st.caption(f"• {e}")
            for w in v.get("warnings", []):
                st.warning(w)

        st.subheader("JSON Normalizado")
        st.json(d0["normalized_json"])

        st.subheader("Resumen de datos extraídos")
        norm = d0["normalized_json"]
        meses = list(norm.get("meses", {}).keys())
        periodo = norm.get("periodo", "—")
        first_mes_data = next(iter(norm.get("meses", {}).values()), {})
        ventas_data = first_mes_data.get("ventas", {})
        sucursales_detectadas = sorted({
            k for g in ventas_data.values()
            if isinstance(g, dict)
            for k in g if k != "total"
        })

        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Meses con datos", len(meses))
        col_b.metric(
            "Sucursales detectadas",
            ", ".join(sucursales_detectadas) if sucursales_detectadas else "—",
        )
        col_c.metric("Rango", periodo)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — Indicadores
# ─────────────────────────────────────────────────────────────────────────────

with tab1:
    st.header("📊 Fase 1: Cálculo de Indicadores")
    st.subheader("Python puro, sin LLM — todo determinista")

    if 1 not in pr:
        st.info("Ejecuta el pipeline para ver los indicadores.")
    elif pr[1].get("error"):
        st.error("Error en Fase 1")
        st.code(pe.get(1, ""), language="python")
    else:
        import pandas as pd

        ind = pr[1]["indicators"]
        por_mes = ind.get("por_mes", {})
        meses = list(por_mes.keys())

        selected_mes1 = (
            st.selectbox("Mes", options=meses, key="tab1_mes")
            if len(meses) > 1
            else (meses[0] if meses else None)
        )

        if selected_mes1 and selected_mes1 in por_mes:
            mi = por_mes[selected_mes1]
            rent = mi["rentabilidad"]
            ec = mi["estructura_costos"]
            sucursales = mi["sucursales"]
            alertas = mi.get("alertas", [])

            with st.expander("Rentabilidad", expanded=True):
                df_rent = pd.DataFrame([
                    {
                        "Indicador": "Margen Bruto",
                        "Valor": f"{rent['margen_bruto']*100:.2f}%",
                        "Umbral": "40%",
                        "Estado": "❌" if rent.get("alerta_margen_bruto") else "✅",
                    },
                    {
                        "Indicador": "Margen EBITDA",
                        "Valor": f"{rent['margen_ebitda']*100:.2f}%",
                        "Umbral": "10%",
                        "Estado": "❌" if rent.get("alerta_ebitda") else "✅",
                    },
                    {
                        "Indicador": "Margen Neto",
                        "Valor": f"{rent['margen_neto']*100:.2f}%",
                        "Umbral": "5%",
                        "Estado": "❌" if rent.get("alerta_neto") else "✅",
                    },
                ])
                st.dataframe(df_rent, use_container_width=True, hide_index=True)

            with st.expander("Estructura de Costos"):
                rows_ec = []
                for k, v_ in ec.items():
                    if not isinstance(v_, float):
                        continue
                    flag = ""
                    if k == "nomina_sobre_ventas" and v_ > 0.30:
                        flag = " ⚠️"
                    elif k == "gastos_op_sobre_ventas" and v_ > 0.40:
                        flag = " ⚠️"
                    rows_ec.append({"Concepto": k, "% sobre ventas": f"{v_*100:.2f}%{flag}"})
                st.dataframe(pd.DataFrame(rows_ec), use_container_width=True, hide_index=True)

            with st.expander("Análisis por Sucursal"):
                total_ventas = sum(s["venta"] for s in sucursales.values()) or 1.0
                rows_suc = []
                for s_name, s_data in sucursales.items():
                    margen = s_data.get("margen", 0.0)
                    participacion = s_data["venta"] / total_ventas
                    rows_suc.append({
                        "Sucursal": s_name,
                        "Ventas": f"${s_data['venta']:,.0f}",
                        "Egresos": f"${s_data.get('egreso', 0):,.0f}",
                        "Margen": f"{margen*100:.1f}%" + (" 🔴" if margen < UMBRAL_MARGEN_SUCURSAL else ""),
                        "Participación": f"{participacion*100:.1f}%",
                        "Alerta": "⚠️" if margen < UMBRAL_MARGEN_SUCURSAL else "✅",
                    })
                st.dataframe(pd.DataFrame(rows_suc), use_container_width=True, hide_index=True)

            with st.expander("Alertas Generadas"):
                if not alertas:
                    st.success("Sin alertas")
                else:
                    for a in alertas:
                        st.warning(
                            f"**{a.get('tipo', '')}** | "
                            f"Severidad: {a.get('severidad', '')} | "
                            f"Valor: {a.get('valor', 0)*100:.2f}% | "
                            f"Umbral: {a.get('umbral', 0)*100:.0f}%"
                        )

        st.subheader("Output de indicators.analizar()")
        st.json(pr[1]["indicators"])


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — Ingesta de Documentos
# ─────────────────────────────────────────────────────────────────────────────

with tab2:
    st.header("📄 Fase 2: Ingesta de Documentos Cualitativos")
    st.subheader("Carga, lectura y chunking de documentos")

    if 2 not in pr:
        st.info("Ejecuta el pipeline para ver la ingesta.")
    elif pr[2].get("error"):
        st.error("Error en Fase 2")
        st.code(pe.get(2, ""), language="python")
    else:
        d2 = pr[2]
        if not d2["ingestion_results"]:
            st.info("No se subieron documentos cualitativos. Sube archivos en la barra lateral.")
        else:
            for r in d2["ingestion_results"]:
                st.markdown(f"### 📄 {r['filename']}")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("doc_id (prefix)", r["doc_id"][:8] + "…")
                c2.metric("chunks_created", r["chunks_created"])
                c3.metric("texto_length", r["texto_length"])
                c4.metric("embeddings_stored", str(r["embeddings_stored"]))

                chunks = d2["chunks_by_doc"].get(r["doc_id"], [])
                with st.expander(f"Ver chunks de {r['filename']}"):
                    for c in chunks:
                        idx = c.metadata.get("chunk_index", 0)
                        start = c.metadata.get("start_char", "?")
                        end = c.metadata.get("end_char", "?")
                        st.caption(f"Chunk {idx + 1}/{len(chunks)} | chars {start}–{end}")
                        st.text_area(
                            label="",
                            value=c.texto,
                            height=100,
                            disabled=True,
                            key=f"chunk_{c.chunk_id}",
                        )

        st.subheader("Estadísticas del DocumentStore")
        st.json(d2["store"].stats())


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — Embeddings
# ─────────────────────────────────────────────────────────────────────────────

with tab3:
    st.header("🧮 Fase 3: Búsqueda Semántica con ChromaDB")
    st.subheader("Cada chunk se convierte en un vector de 384 dimensiones")

    if 3 not in pr:
        st.info("Ejecuta el pipeline para ver los embeddings.")
    elif pr[3].get("error"):
        st.error("Error en Fase 3")
        st.code(pe.get(3, ""), language="python")
    else:
        d3 = pr[3]
        vs = d3["vector_store"]
        d2 = pr.get(2, {})
        has_docs = bool(d2.get("ingestion_results"))

        if not has_docs:
            st.info("Sin documentos — no se generaron embeddings.")
        else:
            vs_stats = vs.stats()
            total_indexed = vs_stats.get("total_chunks", 0)
            col1, col2, col3 = st.columns(3)
            col1.metric("Chunks indexados en ChromaDB", total_indexed)
            col2.metric("Dimensiones por vector", 384)
            col3.metric("Modelo", "all-MiniLM-L6-v2")

            st.subheader("🔍 Prueba de búsqueda semántica")
            norm0 = pr.get(0, {}).get("normalized_json", {})
            search_cliente = norm0.get("cliente_id", cliente_id_input.strip() or "demo_client")

            query_input = st.text_input(
                "Escribe una query:",
                placeholder="ej: costos operativos eficiencia",
                key="tab3_query",
            )
            n_results = st.slider("Resultados", 1, 8, 3, key="tab3_n")

            if query_input and st.button("Buscar", key="tab3_search"):
                search_results = vs.search(query_input, search_cliente, n_results)
                if not search_results:
                    st.info("No se encontraron resultados.")
                else:
                    for sr in search_results:
                        c_left, c_right = st.columns([1, 4])
                        with c_left:
                            st.progress(float(sr.score))
                            st.caption(f"{sr.score:.3f}")
                        with c_right:
                            st.caption(f"📄 {sr.filename} — chunk {sr.chunk_index}")
                            st.text_area(
                                label="",
                                value=sr.texto,
                                height=80,
                                disabled=True,
                                key=f"sr_{sr.chunk_id}",
                            )

            st.subheader("Muestra de vectores (primeros 3 chunks)")
            all_chunks_flat = [
                c
                for chunks in d2.get("chunks_by_doc", {}).values()
                for c in chunks
            ]
            for c in all_chunks_flat[:3]:
                fname = c.metadata.get("filename", "?")
                cidx = c.metadata.get("chunk_index", "?")
                st.caption(f"📄 {fname} — chunk {cidx}")
                embedding = vs.embedding_model.encode(c.texto).tolist()
                first20 = ", ".join(f"{x:.3f}" for x in embedding[:20])
                st.code(f"[{first20}, ... (364 más)]")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 4 — Orquestador
# ─────────────────────────────────────────────────────────────────────────────

with tab4:
    st.header("🔗 Fase 4: Orquestador de Análisis")
    st.subheader("Conecta indicadores cuantitativos con contexto cualitativo")

    if 4 not in pr:
        st.info("Ejecuta el pipeline para ver el orquestador.")
    elif pr[4].get("error"):
        st.error("Error en Fase 4")
        st.code(pe.get(4, ""), language="python")
    else:
        import pandas as pd

        package = pr[4]["package"]
        ind4 = pr.get(1, {}).get("indicators", {})
        por_mes4 = ind4.get("por_mes", {})
        meses4 = list(package.contexto_cualitativo.keys())

        selected_mes4 = (
            st.selectbox("Mes", options=meses4, key="tab4_mes")
            if len(meses4) > 1
            else (meses4[0] if meses4 else None)
        )

        if selected_mes4 and selected_mes4 in package.contexto_cualitativo:
            ctx4 = package.contexto_cualitativo[selected_mes4]
            queries4 = ctx4.get("queries_usadas", [])
            chunks4 = ctx4.get("chunks_relevantes", [])

            st.subheader("Queries generadas dinámicamente")
            mes_ind4 = por_mes4.get(selected_mes4, {})
            ec4 = mes_ind4.get("estructura_costos", {})
            for q in queries4:
                q_lower = q.lower()
                if "estrategia" in q_lower:
                    reason = "siempre incluida"
                elif "contexto operativo" in q_lower:
                    reason = "siempre incluida"
                elif "desempeño ventas" in q_lower or "ventas" in q_lower:
                    reason = "siempre incluida"
                elif "resultados financieros" in q_lower:
                    reason = "siempre incluida"
                elif "nómina" in q_lower or "nomina" in q_lower:
                    reason = f"nomina_sobre_ventas > 0.30 (valor: {ec4.get('nomina_sobre_ventas', 0)*100:.1f}%)"
                elif "gastos" in q_lower:
                    reason = f"gastos_op_sobre_ventas > 0.40 (valor: {ec4.get('gastos_op_sobre_ventas', 0)*100:.1f}%)"
                elif "margen" in q_lower:
                    reason = "alerta de margen detectada"
                elif "sucursal" in q_lower or "branch" in q_lower:
                    reason = "alerta por sucursal detectada"
                else:
                    reason = "query contextual"
                st.code(f'"{q}"  →  {reason}')

            st.subheader("Chunks recuperados por query")
            vs4 = pr.get(3, {}).get("vector_store")
            if vs4 and queries4:
                for q in queries4:
                    q_results = vs4.search(q, package.cliente_id, 3)
                    st.markdown(f"**Query:** `{q}`")
                    st.caption(f"Resultados: {len(q_results)}")
                    if q_results:
                        top4 = q_results[0]
                        st.caption(
                            f"Top: score={top4.score:.3f} | {top4.filename} | "
                            f"{top4.texto[:100]}…"
                        )
                    st.divider()
            else:
                st.info("Sin documentos cualitativos — no se realizaron búsquedas.")

            st.subheader("Chunks finales después de deduplicación")
            if chunks4:
                rows_dedup = [
                    {
                        "Rank": i + 1,
                        "Score": f"{c['score']:.3f}",
                        "Filename": c["filename"],
                        "Chunk": c["chunk_index"],
                        "Preview": c["texto"][:80] + "…",
                    }
                    for i, c in enumerate(chunks4)
                ]
                st.dataframe(pd.DataFrame(rows_dedup), use_container_width=True, hide_index=True)
            else:
                st.info("No se recuperaron chunks cualitativos para este mes.")

        st.subheader("AnalysisPackage completo")
        st.json(_safe_json(package))

        st.metric(
            "listo_para_recomendaciones",
            "✅ Sí" if package.listo_para_recomendaciones else "❌ No",
        )


# ─────────────────────────────────────────────────────────────────────────────
# TAB 5 — Recomendaciones
# ─────────────────────────────────────────────────────────────────────────────

with tab5:
    st.header("💡 Fase 5: Motor de Recomendaciones")
    st.subheader("Claude API genera recomendaciones basadas en evidencia real")

    if 5 not in pr:
        st.info("Ejecuta el pipeline para ver las recomendaciones.")
    elif pr[5].get("error"):
        st.error("Error en Fase 5")
        st.code(pe.get(5, ""), language="python")
    else:
        d5 = pr[5]
        report = d5["report"]
        prompt_text = d5["prompt_text"]

        st.subheader("Prompt enviado a Claude")
        st.text_area("Prompt", prompt_text, height=400, disabled=True)

        col1, col2 = st.columns(2)
        col1.metric("Tokens estimados del prompt", int(len(prompt_text.split()) * 1.3))
        col2.metric("Modelo", report.model_used)

        st.subheader("Recomendaciones generadas")
        for rec in report.recomendaciones:
            prioridad = _rec_attr(rec, "prioridad", "baja")
            titulo = _rec_attr(rec, "titulo", "")
            descripcion = _rec_attr(rec, "descripcion", "")
            evidencia = _rec_attr(rec, "evidencia", [])
            accion = _rec_attr(rec, "accion_sugerida", "")
            rec_id = _rec_attr(rec, "id", "")

            with st.expander(f"{_prioridad_emoji(prioridad)} [{rec_id}] {titulo}"):
                st.write(descripcion)
                st.markdown("**Evidencia citada:**")
                for e in evidencia:
                    fuente = _rec_attr(e, "fuente", "")
                    valor = _rec_attr(e, "valor", "")
                    st.code(f"{fuente}: {valor}")
                st.info(f"**Acción:** {accion}")

        st.subheader("Response JSON de la API")
        st.json({"recomendaciones": _safe_json(report.recomendaciones)})

        st.subheader("Metadata de la llamada")
        st.json(report.metadata)

        st.subheader("Limitaciones detectadas")
        for lim in report.limitaciones:
            st.warning(lim)
