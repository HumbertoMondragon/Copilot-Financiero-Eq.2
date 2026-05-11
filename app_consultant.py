"""
Copilot Financiero — Streamlit interface.
Single-page app with three sequential sections:
  1. File upload & pipeline trigger
  2. Indicators & charts
  3. Recommendations & PDF export
"""
from __future__ import annotations

import io
import logging
import shutil
import tempfile
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

# ── Startup: load .env before any pipeline import touches ANTHROPIC_API_KEY ──
load_dotenv()

import os
if not os.environ.get("ANTHROPIC_API_KEY"):
    st.error(
        "⚠️ No se encontró la variable ANTHROPIC_API_KEY. "
        "Agrega tu clave al archivo .env y reinicia la aplicación."
    )
    st.stop()

# ── Lazy pipeline imports (after env check so errors are surfaced cleanly) ────
from financial_normalizer.recommendations import RecommendationEngine, RecommendationError
from financial_normalizer.orchestrator import AnalysisOrchestrator
from financial_normalizer.ingestion.document_store import DocumentStore
from financial_normalizer.ingestion.vector_store import VectorStore
from financial_normalizer.parsers import ParseError
from financial_normalizer.indicators import UMBRAL_MARGEN_SUCURSAL

import plotly.graph_objects as go

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Copilot Financiero",
    page_icon="💼",
    layout="wide",
)
st.title("💼 Copilot Financiero")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_currency(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:.0f}"


def _prioridad_emoji(prioridad: str) -> str:
    return {"alta": "🔴", "media": "🟡", "baja": "🟢"}.get(prioridad, "⚪")


def _run_pipeline(
    financial_path: Path,
    qual_paths: list[Path],
    cliente_id: str,
    chroma_dir: str,
) -> tuple:
    """
    Run the full pipeline and return (RecommendationReport, AnalysisPackage).
    Raises the original exception so the caller can map it to a friendly message.
    """
    store = DocumentStore()
    vs = VectorStore(persist_directory=chroma_dir)

    # generate_from_files runs normalize → ingest → analyze → recommend
    engine = RecommendationEngine()
    report = engine.generate_from_files(
        financial_filepath=str(financial_path),
        qualitative_filepaths=[str(p) for p in qual_paths],
        cliente_id=cliente_id,
        persist_directory=chroma_dir,
    )

    # Re-use the already-populated VectorStore to build the AnalysisPackage
    orch = AnalysisOrchestrator(vector_store=vs if qual_paths else None)
    from financial_normalizer import normalizer
    normalized = normalizer.normalize(str(financial_path), cliente_id)
    # Ingest qualitative files into the shared store (embeddings already in vs)
    from financial_normalizer import ingestion
    for p in qual_paths:
        ingestion.ingest(str(p), cliente_id, store)
    package = orch.analyze(normalized, cliente_id)

    return report, package


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, ParseError):
        return "No pudimos leer el archivo. ¿Es un Estado de Resultados válido?"
    if isinstance(exc, RecommendationError):
        return "Ocurrió un error al generar recomendaciones. Intenta de nuevo."
    return "Ocurrió un error inesperado. Contacta al equipo técnico."


def _build_pdf(report, package) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    bold = ParagraphStyle("bold", parent=styles["Normal"], fontName="Helvetica-Bold")
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=14)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=11)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8)

    story = []

    # Header
    story.append(Paragraph(
        f"Reporte de Análisis Financiero — {report.cliente_id} — {report.periodo}", h1
    ))
    story.append(Paragraph(f"Generado: {report.generated_at[:19].replace('T', ' ')}", small))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.grey))
    story.append(Spacer(1, 0.4*cm))

    # KPI summary table
    por_mes = package.indicadores.get("por_mes", {})
    meses = list(por_mes.keys())
    if meses:
        story.append(Paragraph("Resumen de Indicadores", h2))
        kpi_data = [["Mes", "Ventas", "Margen Bruto", "EBITDA", "Margen Neto"]]
        for mes in meses:
            mi = por_mes[mes]
            rent = mi["rentabilidad"]
            suc = mi["sucursales"]
            tv = sum(s["venta"] for s in suc.values())
            kpi_data.append([
                mes,
                _fmt_currency(tv),
                f"{rent['margen_bruto']*100:.1f}%",
                f"{rent['margen_ebitda']*100:.1f}%",
                f"{rent['margen_neto']*100:.1f}%",
            ])
        tbl = Table(kpi_data, hAlign="LEFT")
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4C78A8")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4ff")]),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 0.5*cm))

    # Recommendations
    story.append(Paragraph("Recomendaciones", h2))
    for rec in report.recomendaciones:
        emoji = _prioridad_emoji(rec.get("prioridad", "baja"))
        story.append(Paragraph(f"{emoji} {rec.get('titulo', '')}", bold))
        story.append(Paragraph(rec.get("descripcion", ""), styles["Normal"]))
        for ev in rec.get("evidencia", []):
            story.append(Paragraph(
                f"• {ev.get('fuente', '')}: {ev.get('valor', '')}", small
            ))
        story.append(Paragraph(
            f"Acción: {rec.get('accion_sugerida', '')}", styles["Normal"]
        ))
        story.append(Spacer(1, 0.3*cm))

    # Limitations
    if report.limitaciones:
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
        story.append(Paragraph("Limitaciones", h2))
        for lim in report.limitaciones:
            story.append(Paragraph(f"• {lim}", styles["Normal"]))
        story.append(Spacer(1, 0.3*cm))

    # Footer
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Paragraph("Generado por Copilot Financiero", small))

    doc.build(story)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — File upload
# ─────────────────────────────────────────────────────────────────────────────

st.header("📁 Cargar archivos")

cliente_id = st.text_input("ID de Cliente", value="cliente_default")

financial_file = st.file_uploader(
    "Estado de Resultados (Excel o PDF)",
    type=["xlsx", "xls", "xlsm", "pdf"],
)

qual_files = st.file_uploader(
    "Documentos de contexto (opcional)",
    type=["pdf", "txt", "md"],
    accept_multiple_files=True,
)

analizar_btn = st.button("Analizar", disabled=(financial_file is None))

if analizar_btn and financial_file is not None:
    tmp_dir = tempfile.mkdtemp()
    try:
        # Save financial file
        fin_path = Path(tmp_dir) / financial_file.name
        fin_path.write_bytes(financial_file.getbuffer())

        # Save qualitative files
        q_paths: list[Path] = []
        for qf in (qual_files or []):
            qp = Path(tmp_dir) / qf.name
            qp.write_bytes(qf.getbuffer())
            q_paths.append(qp)

        chroma_dir = str(Path(tmp_dir) / "chroma")

        with st.spinner("Procesando archivos..."):
            try:
                report, package = _run_pipeline(
                    fin_path, q_paths, cliente_id.strip() or "cliente_default", chroma_dir
                )
                st.session_state.report = report
                st.session_state.package = package
                st.session_state.processed = True
                st.success("¡Análisis completado!")
            except Exception as exc:
                logger.exception("Pipeline error")
                st.error(_friendly_error(exc))
                st.session_state.processed = False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — Indicators & Charts
# ─────────────────────────────────────────────────────────────────────────────

if st.session_state.get("processed"):
    package = st.session_state.package
    por_mes: dict = package.indicadores.get("por_mes", {})
    tendencias: dict = package.indicadores.get("tendencias", {})
    meses_con_datos: list[str] = tendencias.get("meses_con_datos", list(por_mes.keys()))

    st.divider()
    st.header("📊 Indicadores Financieros")

    # ── KPI cards ─────────────────────────────────────────────────────────────
    first_mes = meses_con_datos[0] if meses_con_datos else None
    if first_mes and first_mes in por_mes:
        mi = por_mes[first_mes]
        rent = mi["rentabilidad"]
        suc = mi["sucursales"]
        tv = sum(s["venta"] for s in suc.values())

        mb = rent["margen_bruto"]
        me = rent["margen_ebitda"]
        mn = rent["margen_neto"]

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Ventas", _fmt_currency(tv))
        col2.metric(
            "Margen Bruto",
            f"{mb * 100:.1f}%",
            delta="▲ OK" if not rent["alerta_margen_bruto"] else "▼ Alerta",
            delta_color="normal" if not rent["alerta_margen_bruto"] else "inverse",
        )
        col3.metric(
            "EBITDA",
            f"{me * 100:.1f}%",
            delta="▲ OK" if not rent["alerta_ebitda"] else "▼ Alerta",
            delta_color="normal" if not rent["alerta_ebitda"] else "inverse",
        )
        col4.metric(
            "Margen Neto",
            f"{mn * 100:.1f}%",
            delta="▲ OK" if not rent["alerta_neto"] else "▼ Alerta",
            delta_color="normal" if not rent["alerta_neto"] else "inverse",
        )

    # ── Month selector ────────────────────────────────────────────────────────
    if len(meses_con_datos) > 1:
        selected_mes = st.selectbox(
            "Selecciona el mes", options=meses_con_datos, index=0
        )
    else:
        selected_mes = first_mes

    # ── Chart 1: Ventas y Margen por Sucursal ─────────────────────────────────
    if selected_mes and selected_mes in por_mes:
        mi = por_mes[selected_mes]
        suc = mi["sucursales"]
        grupos = list(suc.keys())
        ventas_m = [suc[g]["venta"] / 1_000_000 for g in grupos]
        margenes = [suc[g]["margen"] * 100 for g in grupos]
        threshold_pct = UMBRAL_MARGEN_SUCURSAL * 100

        fig1 = go.Figure()
        fig1.add_trace(go.Bar(
            x=grupos, y=ventas_m,
            name="Ventas (M$)",
            marker_color="#4C78A8",
            yaxis="y",
            text=[f"${v:.2f}M" for v in ventas_m],
            textposition="outside",
            textfont=dict(size=11),
        ))
        fig1.add_trace(go.Bar(
            x=grupos, y=margenes,
            name="Margen %",
            marker_color="#54A24B",
            yaxis="y2",
            text=[f"{m:.1f}%" for m in margenes],
            textposition="outside",
            textfont=dict(size=11),
        ))
        # Threshold line scoped to the right (margin) axis via add_shape
        fig1.add_shape(
            type="line",
            x0=-0.5, x1=len(grupos) - 0.5,
            y0=threshold_pct, y1=threshold_pct,
            yref="y2",
            line=dict(color="red", dash="dash", width=2),
        )
        fig1.add_annotation(
            x=grupos[-1], y=threshold_pct, yref="y2",
            text=f"Umbral {threshold_pct:.0f}%",
            showarrow=False, xanchor="right",
            font=dict(color="red", size=11),
        )
        fig1.update_layout(
            title=dict(text=f"Ventas y Margen por Sucursal — {selected_mes}", font=dict(size=16)),
            barmode="group",
            xaxis=dict(title="Sucursal"),
            yaxis=dict(
                title=dict(text="Ventas (millones $)", font=dict(color="#4C78A8")),
                tickfont=dict(color="#4C78A8"),
            ),
            yaxis2=dict(
                title=dict(text="Margen (%)", font=dict(color="#54A24B")),
                tickfont=dict(color="#54A24B"),
                overlaying="y",
                side="right",
                ticksuffix="%",
            ),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            plot_bgcolor="white",
        )
        st.plotly_chart(fig1, use_container_width=True)

    # ── Chart 2: Tendencia de Márgenes ────────────────────────────────────────
    if len(meses_con_datos) > 1:
        mb_vals = [
            por_mes[m]["rentabilidad"]["margen_bruto"] * 100
            for m in meses_con_datos if m in por_mes
        ]
        me_vals = [
            por_mes[m]["rentabilidad"]["margen_ebitda"] * 100
            for m in meses_con_datos if m in por_mes
        ]
        mn_vals = [
            por_mes[m]["rentabilidad"]["margen_neto"] * 100
            for m in meses_con_datos if m in por_mes
        ]
        meses_labels = [m for m in meses_con_datos if m in por_mes]

        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=meses_labels, y=mb_vals, mode="lines+markers", name="Margen Bruto",
            line=dict(color="#4C78A8", width=2), marker=dict(size=8, symbol="circle"),
        ))
        fig2.add_trace(go.Scatter(
            x=meses_labels, y=me_vals, mode="lines+markers", name="EBITDA",
            line=dict(color="#F58518", width=2), marker=dict(size=8, symbol="square"),
        ))
        fig2.add_trace(go.Scatter(
            x=meses_labels, y=mn_vals, mode="lines+markers", name="Margen Neto",
            line=dict(color="#54A24B", width=2), marker=dict(size=8, symbol="diamond"),
        ))
        fig2.update_layout(
            title=dict(text="Tendencia de Márgenes", font=dict(size=16)),
            xaxis=dict(title="Mes", showgrid=True, gridcolor="#e0e0e0"),
            yaxis=dict(title="Margen (%)", ticksuffix="%", showgrid=True, gridcolor="#e0e0e0"),
            plot_bgcolor="white",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Se necesitan al menos 2 meses para ver tendencias.")

    # ── Chart 3: Alert table ──────────────────────────────────────────────────
    resumen_alertas: list = package.resumen_alertas
    if resumen_alertas:
        import pandas as pd

        rows = []
        for entry in resumen_alertas:
            a = entry["alerta"]
            rows.append({
                "Mes": entry["mes"],
                "Indicador": a.get("tipo", ""),
                "Valor": f"{a.get('valor', 0) * 100:.2f}%",
                "Umbral": f"{a.get('umbral', 0) * 100:.0f}%",
                "Severidad": a.get("severidad", ""),
            })
        df = pd.DataFrame(rows)

        def _color_row(row):
            sev = row["Severidad"]
            if sev == "alta":
                return ["background-color: #ffd6d6"] * len(row)
            if sev == "media":
                return ["background-color: #fff3cd"] * len(row)
            return ["background-color: #d4edda"] * len(row)

        styled = df.style.apply(_color_row, axis=1)
        st.dataframe(styled, use_container_width=True, hide_index=True)
    else:
        st.success("✅ No se detectaron alertas en el período analizado.")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — Recommendations
# ─────────────────────────────────────────────────────────────────────────────

if st.session_state.get("processed"):
    report = st.session_state.report
    package = st.session_state.package

    st.divider()
    st.header("💡 Recomendaciones")

    # Executive summary
    st.info(report.resumen_ejecutivo)

    # Recommendation expanders
    for rec in report.recomendaciones:
        emoji = _prioridad_emoji(rec.get("prioridad", "baja"))
        with st.expander(f"{emoji} {rec.get('titulo', '')}"):
            st.write(rec.get("descripcion", ""))
            st.markdown("**Evidencia:**")
            for ev in rec.get("evidencia", []):
                st.caption(f"• {ev.get('fuente', '')}: {ev.get('valor', '')}")
            st.markdown("**Acción sugerida:**")
            st.info(rec.get("accion_sugerida", ""))

    # Limitations
    if report.limitaciones:
        st.warning("\n".join(f"• {lim}" for lim in report.limitaciones))

    # Qualitative context used
    st.caption(
        f"Chunks de documentos cualitativos utilizados: "
        f"{report.metadata.get('chunks_cualitativos_usados', 0)}"
    )

    # ── PDF Export ────────────────────────────────────────────────────────────
    pdf_bytes = _build_pdf(report, package)
    st.download_button(
        label="📄 Exportar Reporte PDF",
        data=pdf_bytes,
        file_name=f"reporte_{report.cliente_id}_{report.periodo}.pdf",
        mime="application/pdf",
    )

