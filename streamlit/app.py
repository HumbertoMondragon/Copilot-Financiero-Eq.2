import sys
import dataclasses
import tempfile
import os
import time
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _is_real_streamlit() -> bool:
    mod = sys.modules.get("streamlit")
    return mod is not None and hasattr(mod, "title") and hasattr(mod, "sidebar")


# ── benchmark presets ───────────────────────────────────────────���────────────

_BENCH_FIELDS = [
    ("margen_bruto",            "Margen Bruto",             65.0, False),
    ("margen_ebitda",           "Margen EBITDA",            20.0, False),
    ("margen_neto",             "Margen Neto",              12.0, False),
    ("nomina_pct",              "Nómina / Revenue",         30.0, True),
    ("gastos_op_pct",           "Gastos Operación / Rev.",  50.0, True),
    ("gastos_financieros_pct",  "Gastos Financieros / Rev.", 8.0, True),
    ("costo_directo_pct",       "Costo Directo / Rev.",     35.0, True),
]

_BENCH_DEFAULTS = {k: v / 100 for k, _, v, _ in _BENCH_FIELDS}


# ── helpers ───────────────────────────────────────────────────────────────────

def _save_tmp(upload, suffix: str = ".csv") -> str:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
        fh.write(upload.read())
        return fh.name


def _color_score(score: float) -> str:
    if score >= 75:
        return "green"
    if score >= 55:
        return "orange"
    if score >= 35:
        return "#e07b00"
    return "red"


def _prioridad_emoji(p: str) -> str:
    return {"alta": "🔴", "media": "🟡", "baja": "🟢"}.get(str(p).lower(), "⚪")


# ── tab renderers ─────────────────────────────────────────────────────────────

def _tab_parsers(st, results):
    bd = results.get("bd_data")
    er = results.get("er_data")
    err = results.get("error_fase1")
    if err:
        st.error(f"Error en parsers: {err}")
        return
    if bd is None:
        st.info("Sube los archivos y ejecuta el pipeline.")
        return

    import pandas as pd

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("BD Transaccional")
        meses = getattr(bd, "meses", []) or []
        sucursales = getattr(bd, "sucursales", []) or []
        rows = getattr(bd, "rows", []) or []
        st.metric("Filas parseadas", len(rows))
        st.metric("Sucursales", len(sucursales))
        skus = {getattr(r, "sku", None) for r in rows if getattr(r, "sku", None)}
        st.metric("SKUs únicos", len(skus))
        st.metric("Meses", ", ".join(str(m) for m in meses) if meses else "—")
        with st.expander("BDData JSON"):
            st.json(dataclasses.asdict(bd) if dataclasses.is_dataclass(bd) else str(bd))

    with col2:
        st.subheader("Estado de Resultados")
        er_meses = getattr(er, "meses", []) or []
        st.metric("Meses", len(er_meses))
        gastos = getattr(er, "gastos_por_mes", {}) or {}
        if gastos:
            rows_er = []
            for mes, g in gastos.items():
                entry = {"Mes": mes}
                entry.update(dataclasses.asdict(g) if dataclasses.is_dataclass(g) else g)
                rows_er.append(entry)
            st.dataframe(pd.DataFrame(rows_er), use_container_width=True)
        with st.expander("ERData JSON"):
            st.json(dataclasses.asdict(er) if dataclasses.is_dataclass(er) else str(er))


def _tab_kpis(st, results):
    import pandas as pd

    kpi = results.get("kpi_report")
    err = results.get("error_fase2")
    if err:
        st.error(f"Error KPIs: {err}")
        return
    if kpi is None:
        st.info("Pipeline no ejecutado aún.")
        return

    kpi_dict = dataclasses.asdict(kpi) if dataclasses.is_dataclass(kpi) else {}
    por_mes = kpi_dict.get("por_mes", {})
    meses = list(por_mes.keys())

    if meses:
        mes_sel = st.selectbox("Mes", meses, key="kpi_mes")
        mes_data = por_mes.get(mes_sel, {})

        # Consolidado
        consolidado = mes_data.get("consolidado", {})
        vs_bench = mes_data.get("vs_benchmark", {})
        if consolidado:
            st.subheader("KPIs Consolidados")
            kpi_rows = []
            for k, v in consolidado.items():
                entry = vs_bench.get(k, {})
                if isinstance(entry, dict) and entry.get("benchmark"):
                    bench_val = entry["benchmark"]
                    estado = entry.get("estado", "—")
                    diferencia = entry.get("diferencia", 0)
                    diff_str = f"{diferencia:+.1%}"
                else:
                    bench_val = "—"
                    estado = "—"
                    diff_str = "—"
                kpi_rows.append({
                    "Métrica": k,
                    "Valor": f"{v:.1%}" if isinstance(v, float) and abs(v) <= 10 else f"{v:,.0f}" if isinstance(v, (int, float)) else v,
                    "Benchmark": f"{bench_val:.1%}" if isinstance(bench_val, float) else bench_val,
                    "Diferencia": diff_str,
                    "Estado": estado,
                })
            df = pd.DataFrame(kpi_rows)

            _estado_colors = {
                "en_rango":  "background-color: #d4edda",
                "alerta":    "background-color: #fff3cd",
                "critico":   "background-color: #f8d7da",
            }

            st.dataframe(
                df.style.map(lambda v: _estado_colors.get(v, ""), subset=["Estado"]),
                use_container_width=True,
            )

        # Efficiency ranking
        ranking = mes_data.get("efficiency_ranking", [])
        if ranking:
            st.subheader("Top 20 SKUs por eficiencia")
            df_rank = pd.DataFrame(ranking[:20])
            st.dataframe(df_rank, use_container_width=True)

        # SKUs bajo rendimiento
        skus_br = mes_data.get("skus_bajo_rendimiento", [])
        st.metric("SKUs bajo rendimiento", len(skus_br))
        if skus_br:
            with st.expander("Ver SKUs bajo rendimiento"):
                st.dataframe(pd.DataFrame(skus_br), use_container_width=True)

        # Alertas
        alertas = mes_data.get("alertas", [])
        if alertas:
            st.subheader("Alertas")
            for a in alertas:
                sev = a.get("severidad", "info") if isinstance(a, dict) else "info"
                msg = a.get("mensaje", str(a)) if isinstance(a, dict) else str(a)
                if sev == "alta":
                    st.error(msg)
                elif sev == "media":
                    st.warning(msg)
                else:
                    st.info(msg)

    # Sucursal bar chart
    tendencias = kpi_dict.get("tendencias", {})
    rev_trend = tendencias.get("revenue", {}) if isinstance(tendencias, dict) else {}
    if rev_trend:
        try:
            import plotly.graph_objects as go
            suc_data = rev_trend.get("por_sucursal", {}) or {}
            if suc_data:
                st.subheader("Revenue por Sucursal")
                suc_names = list(suc_data.keys())
                rev_vals = [suc_data[s].get("ultimo", 0) if isinstance(suc_data[s], dict) else 0
                            for s in suc_names]
                fig = go.Figure(go.Bar(x=suc_names, y=rev_vals, name="Revenue"))
                fig.update_layout(height=350)
                st.plotly_chart(fig, use_container_width=True)
        except Exception:
            pass


def _tab_modelo(st, results):
    import pandas as pd

    ml = results.get("prediction_report")
    shap_nar = results.get("shap_narrative")
    err = results.get("error_fase3")
    if err:
        st.error(f"Error ML: {err}")
        return
    if ml is None:
        st.info("Pipeline no ejecutado aún.")
        return

    ml_dict = dataclasses.asdict(ml) if dataclasses.is_dataclass(ml) else {}
    metrics = ml_dict.get("train_metrics", {})

    # Train metrics
    if metrics:
        st.subheader("Métricas de entrenamiento")
        c1, c2, c3 = st.columns(3)
        c1.metric("RMSE", f"{metrics.get('rmse', 0):.4f}")
        c2.metric("MAE", f"{metrics.get('mae', 0):.4f}")
        c3.metric("R²", f"{metrics.get('r2', 0):.4f}")

    # SHAP feature importance
    shap_vals = ml_dict.get("shap_feature_importance", {}) or {}
    if shap_vals:
        try:
            import plotly.graph_objects as go
            sorted_shap = sorted(shap_vals.items(), key=lambda x: x[1], reverse=True)[:15]
            feats = [s[0] for s in sorted_shap]
            vals = [s[1] for s in sorted_shap]
            fig = go.Figure(go.Bar(x=vals, y=feats, orientation="h"))
            fig.update_layout(title="SHAP Feature Importance", height=400, yaxis={"autorange": "reversed"})
            st.plotly_chart(fig, use_container_width=True)
        except Exception:
            st.json(shap_vals)

    # Top / Bottom SKUs
    rows = ml_dict.get("predictions", []) or []
    if rows:
        df = pd.DataFrame(rows)
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Top 10 SKUs — Mayor eficiencia")
            if "multiplicador_eficiencia" in df.columns:
                st.dataframe(
                    df.nlargest(10, "multiplicador_eficiencia")[
                        ["sku", "sucursal", "multiplicador_eficiencia"]
                    ],
                    use_container_width=True,
                )
        with col2:
            st.subheader("Bottom 10 SKUs — Menor margen")
            if "margen_bruto" in df.columns:
                bottom = df.nsmallest(10, "margen_bruto")[["sku", "sucursal", "margen_bruto"]]
                st.dataframe(
                    bottom.style.map(lambda _: "background-color: #f8d7da"),
                    use_container_width=True,
                )

    # SHAP narrative per sucursal
    if shap_nar and isinstance(shap_nar, dict):
        sucursales = list(shap_nar.keys())
        if sucursales:
            sel = st.selectbox("Narrativa SHAP por sucursal", sucursales, key="shap_suc")
            st.markdown(shap_nar.get(sel, "Sin narrativa disponible."))


def _tab_forecast(st, results):
    fc = results.get("forecast")
    err = results.get("error_fase4")
    if err:
        st.error(f"Error forecast: {err}")
        return
    if fc is None:
        st.info("Pipeline no ejecutado aún.")
        return

    fc_dict = dataclasses.asdict(fc) if dataclasses.is_dataclass(fc) else {}

    rev = fc_dict.get("revenue_proyectado", 0)
    tendencia = fc_dict.get("tendencia", "—")
    confianza = fc_dict.get("confianza", "—")
    advertencia = fc_dict.get("advertencia", "")
    mes_proy = fc_dict.get("mes_proyectado", "—")

    c1, c2, c3 = st.columns(3)
    c1.metric("Revenue Proyectado", f"${rev:,.0f}", delta=mes_proy)

    tendencia_color = {"creciente": "🟢", "decreciente": "🔴", "estable": "🟡"}.get(tendencia, "⚪")
    c2.metric("Tendencia", f"{tendencia_color} {tendencia}")

    confianza_color = {"alta": "🟢", "media": "🟡", "baja": "🔴"}.get(confianza, "⚪")
    c3.metric("Confianza", f"{confianza_color} {confianza}")

    if advertencia:
        st.warning(advertencia)

    # Historical + projected line chart
    kpi = results.get("kpi_report")
    if kpi:
        try:
            import plotly.graph_objects as go
            kpi_d = dataclasses.asdict(kpi) if dataclasses.is_dataclass(kpi) else {}
            por_mes = kpi_d.get("por_mes", {})
            hist_months = list(por_mes.keys())
            hist_rev = [
                por_mes[m].get("consolidado", {}).get("total_revenue", 0)
                for m in hist_months
            ]
            all_months = hist_months + [mes_proy]
            all_rev = hist_rev + [rev]

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=hist_months, y=hist_rev, mode="lines+markers", name="Histórico",
                line={"color": "steelblue"},
            ))
            fig.add_trace(go.Scatter(
                x=[hist_months[-1], mes_proy] if hist_months else [mes_proy],
                y=[hist_rev[-1], rev] if hist_rev else [rev],
                mode="lines+markers", name="Proyectado",
                line={"color": "orange", "dash": "dash"},
            ))
            fig.update_layout(title="Revenue Histórico + Proyectado", height=350)
            st.plotly_chart(fig, use_container_width=True)
        except Exception:
            pass

    por_suc = fc_dict.get("por_sucursal", {}) or {}
    if por_suc:
        import pandas as pd
        st.subheader("Desglose por sucursal")
        st.dataframe(pd.DataFrame.from_dict(por_suc, orient="index"), use_container_width=True)


def _tab_macro(st, results):
    macro = results.get("macro_data")
    macro_idx = results.get("macro_indices")
    err = results.get("error_fase5")
    if err:
        st.warning(f"Macro no disponible: {err}")
    if macro is None:
        st.info("Pipeline no ejecutado aún o macro deshabilitado.")
        return

    macro_dict = dataclasses.asdict(macro) if dataclasses.is_dataclass(macro) else {}
    raw = macro_dict.get("raw", {}) or {}

    def _raw_val(d, suffix=""):
        if isinstance(d, dict):
            v = d.get("valor", "—")
            fecha = d.get("fecha", "")
            return f"{v}{suffix}", fecha
        return str(d) if d else "—", ""

    # 4 raw metrics
    st.subheader("Indicadores macroeconómicos")
    c1, c2, c3, c4 = st.columns(4)
    v, f = _raw_val(raw.get("tipo_cambio_usd"), " MXN")
    c1.metric("Tipo de cambio USD", v, delta=f or None)
    v, f = _raw_val(raw.get("tasa_interes"), "%")
    c2.metric("Tasa interés Banxico", v, delta=f or None)
    v, f = _raw_val(raw.get("inpc_variacion_anual"), "%")
    c3.metric("Inflación (INPC)", v, delta=f or None)
    v, f = _raw_val(raw.get("igae_variacion_anual"), "%")
    c4.metric("IGAE var. anual", v, delta=f or None)

    errores = macro_dict.get("errores", []) or []
    if errores:
        with st.expander(f"⚠️ {len(errores)} fuente(s) no disponible(s) — índices calculados con valores de referencia"):
            for e in errores:
                st.caption(e)
        st.caption("Para datos en tiempo real: agrega `BANXICO_TOKEN` e `INEGI_TOKEN` en tu `.env`")

    if macro_idx is None:
        return

    idx_dict = dataclasses.asdict(macro_idx) if dataclasses.is_dataclass(macro_idx) else {}

    st.subheader("Índices compuestos")

    def _render_index(label, d):
        if not isinstance(d, dict):
            return
        valor = d.get("valor", d.get("nivel", "—"))
        interp = d.get("interpretacion", d.get("nivel_interpretacion", ""))
        color_map = {"alta": "🔴", "moderada": "🟡", "baja": "🟢", "alto": "🔴",
                     "moderado": "🟡", "bajo": "🟢", "positivo": "🟢", "negativo": "🔴", "neutro": "🟡"}
        ico = color_map.get(str(interp).lower(), "⚪")
        st.metric(label, f"{ico} {interp}", delta=f"valor: {valor}")

    _render_index("Presión Inflacionaria", idx_dict.get("indice_presion_inflacionaria", {}))
    _render_index("Entorno Económico", idx_dict.get("indice_entorno_economico", {}))
    _render_index("Presión Financiera", idx_dict.get("indice_presion_financiera", {}))

    narrativa = idx_dict.get("narrativa_consolidada", "")
    if narrativa:
        st.info(narrativa)


def _tab_health(st, results):
    hs = results.get("health_score_report")
    err = results.get("error_fase6")
    if err:
        st.error(f"Error health score: {err}")
        return
    if hs is None:
        st.info("Pipeline no ejecutado aún.")
        return

    hs_dict = dataclasses.asdict(hs) if dataclasses.is_dataclass(hs) else {}
    por_mes = hs_dict.get("por_mes", {}) or {}
    meses = list(por_mes.keys())

    if not meses:
        st.warning("Sin datos de health score.")
        return

    mes_sel = st.selectbox("Mes", meses, key="hs_mes")
    mes_data = por_mes.get(mes_sel, {}) or {}

    score = mes_data.get("score_total", 0)
    categoria = mes_data.get("categoria", "—")

    color = _color_score(score)
    st.markdown(
        f"<h1 style='color:{color};text-align:center;'>{score:.1f} / 100</h1>"
        f"<p style='text-align:center;font-size:1.3em;'>{categoria.replace('_', ' ').title()}</p>",
        unsafe_allow_html=True,
    )

    # Horizontal bar chart of 5 dimensions
    dimensiones = mes_data.get("dimensiones", {}) or {}
    if dimensiones:
        try:
            import plotly.graph_objects as go
            dim_names = list(dimensiones.keys())
            dim_vals = [dimensiones[d].get("score", 0) if isinstance(dimensiones[d], dict)
                        else dimensiones[d] for d in dim_names]
            colors = [_color_score(v) for v in dim_vals]
            fig = go.Figure(go.Bar(
                x=dim_vals, y=dim_names, orientation="h",
                marker_color=colors, text=[f"{v:.0f}" for v in dim_vals],
                textposition="outside",
            ))
            fig.update_layout(title="Score por Dimensión", height=300, xaxis_range=[0, 100])
            st.plotly_chart(fig, use_container_width=True)
        except Exception:
            st.json(dimensiones)

    c1, c2 = st.columns(2)
    debil = mes_data.get("dimension_mas_debil", "—")
    fuerte = mes_data.get("dimension_mas_fuerte", "—")
    c1.error(f"Dimensión más débil: **{debil}**")
    c2.success(f"Dimensión más fuerte: **{fuerte}**")

    # Tendencia line chart (multiple months)
    if len(meses) > 1:
        try:
            import plotly.graph_objects as go
            scores_hist = [por_mes[m].get("score_total", 0) for m in meses]
            fig = go.Figure(go.Scatter(
                x=meses, y=scores_hist, mode="lines+markers",
                line={"color": "steelblue"},
            ))
            fig.update_layout(title="Tendencia Health Score", height=300, yaxis_range=[0, 100])
            st.plotly_chart(fig, use_container_width=True)
        except Exception:
            pass


def _tab_simulador(st, results):
    kpi_report = results.get("kpi_report")
    if kpi_report is None:
        st.info("Carga los archivos y ejecuta el pipeline para usar el simulador.")
        return

    import plotly.graph_objects as go
    from src.pipeline.scenario import ScenarioConfig, simular_escenario

    benchmarks = st.session_state.get("benchmarks", {})

    st.caption(
        "Ingresa cambios esperados en variables clave. "
        "Se corren 10,000 simulaciones Monte Carlo para estimar la distribución de resultados posibles."
    )

    col1, col2 = st.columns(2)
    with col1:
        rev_delta = st.slider("Variación de ingresos (%)", -30, 30, 0, key="sim_rev") / 100
        cos_delta = st.slider("Variación de costo directo (%)", -20, 30, 0, key="sim_cos") / 100
    with col2:
        nom_delta = st.slider("Variación de nómina (%)", -20, 20, 0, key="sim_nom") / 100
        gfin_delta = st.slider("Variación de gastos financieros (%)", -20, 20, 0, key="sim_gfin") / 100

    with st.expander("Parámetros de incertidumbre (σ — qué tan dispersos son los resultados)"):
        sc1, sc2 = st.columns(2)
        with sc1:
            sig_rev = st.slider("σ ingresos (%)", 0, 20, 5, key="sig_rev") / 100
            sig_cos = st.slider("σ costo directo (%)", 0, 20, 4, key="sig_cos") / 100
        with sc2:
            sig_nom = st.slider("σ nómina (%)", 0, 15, 3, key="sig_nom") / 100
            sig_gfin = st.slider("σ gastos financieros (%)", 0, 15, 2, key="sig_gfin") / 100

    if st.button("Simular 10,000 escenarios", type="primary"):
        config = ScenarioConfig(
            variaciones={
                "revenue": rev_delta,
                "costo_directo": cos_delta,
                "nomina": nom_delta,
                "gastos_financieros": gfin_delta,
            },
            sigmas={
                "revenue": sig_rev,
                "costo_directo": sig_cos,
                "nomina": sig_nom,
                "gastos_financieros": sig_gfin,
            },
            n_simulaciones=10_000,
        )
        with st.spinner("Corriendo 10,000 simulaciones…"):
            st.session_state["scenario_result"] = simular_escenario(kpi_report, config, benchmarks)

    sr = st.session_state.get("scenario_result")
    if sr is None:
        return

    st.divider()
    st.subheader(f"Resultados — base: {sr.mes_base}")

    # ── Probabilidades ────────────────────────────────────────────────────────
    prob = sr.probabilidades_benchmark
    p_cols = st.columns(5)
    _prob_items = [
        ("Margen bruto\nsobre benchmark", prob["margen_bruto_sobre_benchmark"]),
        ("Nómina\nbajo benchmark", prob["nomina_bajo_benchmark"]),
        ("Gastos fin.\nbajo benchmark", prob["gastos_fin_bajo_benchmark"]),
        ("Margen neto\nsobre benchmark", prob["margen_neto_sobre_benchmark"]),
        ("EBITDA\npositivo", prob["ebitda_positivo"]),
    ]
    for col, (label, val) in zip(p_cols, _prob_items):
        color = "normal" if val >= 0.7 else ("off" if val < 0.4 else "normal")
        col.metric(label, f"{val:.0%}")

    # ── Distribuciones — histogramas ──────────────────────────────────────────
    dist_mb = sr.distribuciones["margen_bruto"]
    dist_eb = sr.distribuciones["ebitda"]
    bench_mb = benchmarks.get("margen_bruto", 0.68)

    ch1, ch2 = st.columns(2)
    with ch1:
        fig = go.Figure()
        fig.add_trace(go.Histogram(
            x=[v * 100 for v in dist_mb.valores],
            nbinsx=40, name="Margen bruto",
            marker_color="#4C9BE8", opacity=0.8,
        ))
        fig.add_vline(x=dist_mb.p50 * 100, line_dash="dash", line_color="#1E3A5F",
                      annotation_text=f"Mediana {dist_mb.p50:.1%}")
        fig.add_vline(x=bench_mb * 100, line_dash="dot", line_color="#E84C4C",
                      annotation_text=f"Benchmark {bench_mb:.1%}")
        fig.update_layout(title="Distribución — Margen bruto", xaxis_title="%",
                          yaxis_title="Frecuencia", showlegend=False,
                          margin=dict(t=40, b=30), height=280)
        st.plotly_chart(fig, use_container_width=True)

    with ch2:
        fig2 = go.Figure()
        fig2.add_trace(go.Histogram(
            x=[v / 1_000 for v in dist_eb.valores],
            nbinsx=40, name="EBITDA",
            marker_color="#4CBF8E", opacity=0.8,
        ))
        fig2.add_vline(x=dist_eb.p50 / 1_000, line_dash="dash", line_color="#1E3A5F",
                       annotation_text=f"Mediana ${dist_eb.p50/1e6:.2f}M")
        fig2.add_vline(x=0, line_dash="dot", line_color="#E84C4C",
                       annotation_text="Breakeven")
        fig2.update_layout(title="Distribución — EBITDA", xaxis_title="Miles $MXN",
                           yaxis_title="Frecuencia", showlegend=False,
                           margin=dict(t=40, b=30), height=280)
        st.plotly_chart(fig2, use_container_width=True)

    # ── Tabla de percentiles ──────────────────────────────────────────────────
    import pandas as pd
    st.subheader("Tabla de percentiles")
    _metric_labels = {
        "revenue": "Ingresos ($)",
        "margen_bruto": "Margen bruto",
        "ebitda": "EBITDA ($)",
        "margen_neto": "Margen neto",
        "nomina_pct": "Nómina / Ingresos",
        "gastos_financieros_pct": "Gastos fin. / Ingresos",
    }
    _pct_metrics = {"margen_bruto", "margen_neto", "nomina_pct", "gastos_financieros_pct"}
    rows = []
    for key, label in _metric_labels.items():
        d = sr.distribuciones[key]
        fmt = (lambda v: f"{v:.1%}") if key in _pct_metrics else (lambda v: f"${v:,.0f}")
        rows.append({
            "Métrica": label,
            "P10": fmt(d.p10),
            "P25": fmt(d.p25),
            "Mediana": fmt(d.p50),
            "P75": fmt(d.p75),
            "P90": fmt(d.p90),
            "Desv.": f"{d.desviacion:.1%}" if key in _pct_metrics else f"${d.desviacion:,.0f}",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── Narrativa ─────────────────────────────────────────────────────────────
    st.info(sr.narrativa)


def _tab_contexto_llm(st, results):
    needed = ["kpi_report", "health_score_report"]
    missing = [k for k in needed if results.get(k) is None]
    if missing:
        st.info("Ejecuta el pipeline primero (se necesitan al menos Fases 1 y 2).")
        return

    try:
        from src.pipeline.engine import CopilotEngine
        engine = CopilotEngine.__new__(CopilotEngine)  # skip __init__ (no API key needed)
        prompt = engine.build_prompt(
            results.get("kpi_report"),
            results.get("health_score_report"),
            results.get("macro_indices"),
            results.get("shap_narrative"),
            results.get("forecast"),
            results.get("chunks", []),
        )
    except Exception as e:
        st.error(f"Error construyendo el prompt: {e}")
        return

    # ── Métricas del prompt ────────────────────────────────────────────────────
    n_chunks = len(results.get("chunks", []) or [])
    has_shap = results.get("shap_narrative") is not None
    has_macro = results.get("macro_indices") is not None
    has_forecast = results.get("forecast") is not None

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Tokens aprox.", f"{len(prompt.split()):,}")
    m2.metric("Caracteres", f"{len(prompt):,}")
    m3.metric("Chunks cualitativos", n_chunks)
    m4.metric("SHAP incluido", "Sí" if has_shap else "No")
    m5.metric("Macro incluido", "Sí" if has_macro else "No")

    st.divider()

    # ── Secciones desglosadas ──────────────────────────────────────────────────
    sections = []
    current_title = "Sistema"
    current_lines = []
    for line in prompt.split("\n"):
        if line.startswith("## "):
            if current_lines:
                sections.append((current_title, "\n".join(current_lines)))
            current_title = line[3:]
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_title, "\n".join(current_lines)))

    _section_icons = {
        "Health Score": "🏥",
        "KPIs": "📊",
        "Análisis ML": "🤖",
        "Ranking": "🏆",
        "Forecast": "📈",
        "Contexto macroeconómico": "🌍",
        "Contexto cualitativo": "📄",
        "Instrucciones": "📋",
    }

    st.subheader("Secciones del prompt")
    for title, body in sections:
        icon = next((v for k, v in _section_icons.items() if k in title), "•")
        chars = len(body)
        with st.expander(f"{icon} {title}  —  {chars} chars"):
            st.code(body.strip(), language=None)

    st.divider()

    # ── SHAP values explícitos ─────────────────────────────────────────────────
    shap_narrative = results.get("shap_narrative")
    if shap_narrative:
        st.subheader("🤖 SHAP values — qué recibe el LLM")
        st.caption(
            "Los SHAP values miden cuánto aportó cada variable a la predicción del multiplicador "
            "de eficiencia de cada SKU. Valor positivo = empuja el multiplicador hacia arriba; "
            "negativo = lo arrastra hacia abajo."
        )
        global_data = shap_narrative.global_ if hasattr(shap_narrative, "global_") else {}
        if global_data.get("top_3_factores_descripcion"):
            import pandas as pd
            rows = [
                {
                    "Factor": f["feature"],
                    "Importancia (mean |SHAP|)": f"{f['importancia']:.4f}",
                    "Descripción": f.get("descripcion", ""),
                }
                for f in global_data["top_3_factores_descripcion"]
            ]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        if global_data.get("narrativa"):
            st.info(global_data["narrativa"])

        por_suc = shap_narrative.por_sucursal_mes if hasattr(shap_narrative, "por_sucursal_mes") else {}
        if por_suc:
            sel = st.selectbox("Ver detalle por sucursal/mes:", list(por_suc.keys()), key="shap_ctx_sel")
            suc_data = por_suc[sel]
            st.write(suc_data.get("narrativa", ""))
            factores = suc_data.get("factores", [])
            if factores:
                import pandas as pd
                rows2 = [
                    {
                        "Feature": f["feature"],
                        "SHAP": f"{f['shap']:+.4f}",
                        "Dirección": f["direccion"],
                        "Magnitud": f["magnitud"],
                        "Descripción": f.get("descripcion", ""),
                    }
                    for f in factores
                ]
                st.dataframe(pd.DataFrame(rows2), use_container_width=True, hide_index=True)
    else:
        st.info("SHAP no disponible (Fase 3 no ejecutada o ML desactivado).")

    st.divider()

    # ── Prompt completo ────────────────────────────────────────────────────────
    with st.expander("Ver prompt completo (texto plano enviado al LLM)"):
        st.text_area("Prompt completo", prompt, height=500, disabled=True, key="full_prompt_ctx")


def _tab_documentos(st, results):
    chunks = results.get("chunks", []) or []
    err = results.get("error_fase7")

    if err:
        st.warning(f"Error al cargar documentos: {err}")

    if not chunks:
        st.info("Sin documentos cualitativos cargados.")
        return

    st.subheader(f"{len(chunks)} chunks cargados")
    st.caption("El contenido completo se envía como contexto al LLM en Fase 8.")

    import pandas as pd
    chunk_rows = []
    for c in chunks:
        if hasattr(c, "chunk_id"):
            chunk_rows.append({
                "id": c.chunk_id,
                "doc_id": c.doc_id,
                "texto": c.texto[:120] + ("…" if len(c.texto) > 120 else ""),
            })
        elif isinstance(c, dict):
            chunk_rows.append({"id": c.get("chunk_id", ""), "doc_id": c.get("doc_id", ""),
                               "texto": str(c.get("texto", ""))[:120] + "…"})
        else:
            chunk_rows.append({"texto": str(c)[:120]})
    st.dataframe(pd.DataFrame(chunk_rows), use_container_width=True)


def _tab_pdf(st, results):
    kpi_report = results.get("kpi_report")
    health_report = results.get("health_score_report")

    if kpi_report is None or health_report is None:
        st.info("Ejecuta el pipeline primero (se necesitan al menos Fases 1 y 2).")
        return

    scenario_result = st.session_state.get("scenario_result")
    copilot_report = results.get("copilot_report")

    # ── Resumen de lo que se incluye ──────────────────────────────────────────
    st.subheader("Contenido del reporte")
    items = [
        ("Portada + Health Score", True),
        ("KPIs y benchmarking", True),
        ("Analisis SHAP (ML)", results.get("shap_narrative") is not None),
        ("Forecast de ingresos", results.get("forecast") is not None),
        ("Contexto macroeconomico", results.get("macro_indices") is not None),
        ("Simulacion Monte Carlo", scenario_result is not None),
        ("Recomendaciones del LLM", copilot_report is not None),
    ]
    cols = st.columns(4)
    for i, (label, available) in enumerate(items):
        cols[i % 4].metric(
            label,
            "Incluido" if available else "No disponible",
            delta=None,
        )

    if scenario_result is None:
        st.caption("Tip: corre el Simulador What-If (Fase 6.5) para incluir el analisis Monte Carlo en el PDF.")
    if copilot_report is None:
        st.caption("Tip: la Fase 8 (Recomendaciones) requiere creditos de API — el PDF funciona sin ella.")

    st.divider()

    # ── Generar y descargar ────────────────────────────────────────────────────
    if st.button("Generar PDF", type="primary"):
        try:
            from src.pipeline.report_generator import generar_reporte
            with st.spinner("Generando reporte PDF..."):
                pdf_bytes = generar_reporte(
                    kpi_report=kpi_report,
                    health_report=health_report,
                    macro_indices=results.get("macro_indices"),
                    shap_narrative=results.get("shap_narrative"),
                    forecast_result=results.get("forecast"),
                    scenario_result=scenario_result,
                    copilot_report=copilot_report,
                    cliente_id=st.session_state.get("cliente_id", "cliente"),
                )
            st.session_state["pdf_bytes"] = pdf_bytes
            st.success(f"PDF generado: {len(pdf_bytes):,} bytes ({len(pdf_bytes)/1024:.1f} KB)")
        except Exception as e:
            st.error(f"Error generando PDF: {e}")

    pdf_bytes = st.session_state.get("pdf_bytes")
    if pdf_bytes:
        mes = kpi_report.meses_analizados[-1].replace(" ", "_") if kpi_report.meses_analizados else "reporte"
        cliente = st.session_state.get("cliente_id", "cliente")
        filename = f"reporte_{cliente}_{mes}.pdf"
        st.download_button(
            label="Descargar PDF",
            data=pdf_bytes,
            file_name=filename,
            mime="application/pdf",
            type="secondary",
        )


def _tab_recomendaciones(st, results):
    report = results.get("copilot_report")
    err = results.get("error_fase8")
    if err:
        st.error(f"Error en recomendaciones: {err}")
        return
    if report is None:
        st.info("Pipeline no ejecutado aún.")
        return

    report_dict = dataclasses.asdict(report) if dataclasses.is_dataclass(report) else {}

    # Prompt (read-only)
    prompt_used = results.get("prompt_used", "")
    if prompt_used:
        with st.expander("Prompt enviado a Claude"):
            st.text_area("Prompt", prompt_used, height=300, disabled=True, key="prompt_ro")

    # Recommendations
    recos = report_dict.get("recomendaciones", []) or []
    st.subheader(f"Recomendaciones ({len(recos)})")
    for r in recos:
        if not isinstance(r, dict):
            st.markdown(str(r))
            continue
        titulo = r.get("titulo", r.get("title", "Recomendación"))
        prior = r.get("prioridad", r.get("priority", "media"))
        emoji = _prioridad_emoji(prior)
        with st.expander(f"{emoji} {titulo}  [{prior}]"):
            st.markdown(r.get("descripcion", r.get("description", "")))
            impacto = r.get("impacto_estimado", r.get("impacto", ""))
            if impacto:
                st.caption(f"Impacto: {impacto}")
            accion = r.get("accion_inmediata", r.get("accion", ""))
            if accion:
                st.caption(f"Acción: {accion}")

    # Narrativa ejecutiva
    narrativa = report_dict.get("narrativa_ejecutiva", "")
    if narrativa:
        st.subheader("Narrativa ejecutiva")
        st.info(narrativa)

    # SHAP top factores
    shap_top = report_dict.get("shap_top_factores", []) or []
    if shap_top:
        st.subheader("Factores SHAP principales")
        for f in shap_top:
            if isinstance(f, dict):
                st.markdown(f"- **{f.get('feature', f.get('factor', ''))}**: {f.get('impact', f.get('impacto', ''))}")
            else:
                st.markdown(f"- {f}")

    # Metadata
    meta = report_dict.get("metadata", {}) or {}
    if meta:
        st.subheader("Metadata")
        import pandas as pd
        st.dataframe(
            pd.DataFrame(list(meta.items()), columns=["Campo", "Valor"]),
            use_container_width=True,
        )


# ── benchmark recalculation ───────────────────────────────────────────────────

def _recalculate_benchmarks(st, results: dict, bench_config: dict) -> None:
    fin_data = results.get("fin_data")
    if fin_data is None:
        st.warning("Ejecuta el pipeline primero.")
        return
    try:
        from src.pipeline.kpis import calcular_kpis
        from src.pipeline.health_score import calcular_health_score
        config = {"benchmarks": bench_config}
        kpi = calcular_kpis(fin_data, config)
        hs = calcular_health_score(kpi, results.get("macro_indices"), config)
        results["kpi_report"] = kpi
        results["health_score_report"] = hs
        results["benchmark_config"] = bench_config
        st.session_state.results = results
        st.success("KPIs y Health Score recalculados.")
    except Exception as e:
        st.error(f"Error al recalcular: {e}")


# ── main app ──────────────────────────────────────────────────────────────────

def main():
    import streamlit as st
    from dotenv import load_dotenv
    load_dotenv()

    st.set_page_config(
        page_title="Copilot Financiero v2 — Dev Demo",
        layout="wide",
        page_icon="💹",
    )
    st.title("💹 Copilot Financiero v2 — Developer Demo")

    # ── Session state init ────────────────────────────────────────────────────
    for key in ("timings", "results", "errors"):
        if key not in st.session_state:
            st.session_state[key] = {}
    if "benchmarks" not in st.session_state:
        st.session_state.benchmarks = dict(_BENCH_DEFAULTS)

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("Configuración")
        bd_upload = st.file_uploader("Base de Datos transaccional (CSV)", type="csv", key="bd")
        er_upload = st.file_uploader("Estado de Resultados (CSV)", type="csv", key="er")
        qual_uploads = st.file_uploader(
            "Documentos cualitativos (opcional)",
            type=["pdf", "txt", "md"],
            accept_multiple_files=True,
            key="quals",
        )
        cliente_id = st.text_input("Cliente ID", value="default")
        include_macro = st.checkbox("Incluir datos macro", value=True)
        train_ml = st.checkbox("Entrenar modelo ML", value=True)

        run_btn = st.button(
            "Ejecutar Pipeline",
            type="primary",
            disabled=not (bd_upload and er_upload),
        )

        st.divider()
        st.subheader("⚖️ Benchmarks")
        has_data = bool(st.session_state.results.get("fin_data"))

        col_a, col_b = st.columns(2)
        if col_a.button("F&B Sugeridos", help="Valores típicos de industria restaurantera"):
            st.session_state.benchmarks = dict(_BENCH_DEFAULTS)
            st.rerun()
        if col_b.button("Sin benchmarks", help="Quitar comparaciones"):
            st.session_state.benchmarks = {k: 0.0 for k in _BENCH_DEFAULTS}
            st.rerun()

        bench_inputs = {}
        for key, label, _, lower in _BENCH_FIELDS:
            direction = "↓ menor" if lower else "↑ mayor"
            current_pct = st.session_state.benchmarks.get(key, 0.0) * 100
            val = st.number_input(
                f"{label} ({direction})",
                min_value=0.0, max_value=100.0,
                value=float(f"{current_pct:.1f}"),
                step=0.5, format="%.1f",
                key=f"bench_{key}",
            )
            bench_inputs[key] = val / 100

        recalc_btn = st.button(
            "🔄 Recalcular KPIs + Health Score",
            type="primary",
            disabled=not has_data,
        )
        if recalc_btn:
            st.session_state.benchmarks = bench_inputs
            _recalculate_benchmarks(st, st.session_state.results, bench_inputs)
            st.rerun()

        st.divider()
        st.subheader("Estado del Pipeline")
        phase_labels = [
            "Parsers", "KPIs y Benchmarking", "Modelo ML", "Forecast",
            "Macro", "Health Score", "Documentos + RAG", "Recomendaciones",
        ]
        for i, label in enumerate(phase_labels, 1):
            key = f"fase{i}"
            t = st.session_state.timings.get(key)
            err = st.session_state.errors.get(key)
            if t is not None:
                icon = "❌" if err else "✅"
                st.write(f"{icon} Fase {i} — {label} ({t:.2f}s)")
            else:
                st.write(f"⬜ Fase {i} — {label}")

    # ── Pipeline execution ────────────────────────────────────────────────────
    if run_btn and bd_upload and er_upload:
        import importlib, sys as _sys
        for _mod in [k for k in _sys.modules if k.startswith("src.")]:
            try:
                importlib.reload(_sys.modules[_mod])
            except Exception:
                pass

        timings = {}
        errors = {}
        results = {}
        bd_tmp = er_tmp = None
        qual_tmps = []

        try:
            bd_tmp = _save_tmp(bd_upload)
            er_tmp = _save_tmp(er_upload)
            for qu in (qual_uploads or []):
                suffix = Path(qu.name).suffix or ".txt"
                qual_tmps.append(_save_tmp(qu, suffix=suffix))

            with st.spinner("Ejecutando pipeline…"):
                # ── Fase 1: Parsers ───────────────────────────────────────
                t0 = time.perf_counter()
                try:
                    from src.pipeline.parsers.parser_bd import parse_bd
                    from src.pipeline.parsers.parser_er import parse_er
                    results["bd_data"] = parse_bd(bd_tmp)
                    results["er_data"] = parse_er(er_tmp)
                except Exception as e:
                    errors["fase1"] = str(e)
                    results["error_fase1"] = str(e)
                timings["fase1"] = time.perf_counter() - t0

                # ── Fase 2: KPIs ──────────────────────────────────────────
                t0 = time.perf_counter()
                if "fase1" not in errors:
                    try:
                        from src.pipeline.integrator import integrate
                        from src.pipeline.kpis import calcular_kpis
                        fin_data = integrate(results["bd_data"], results["er_data"])
                        results["fin_data"] = fin_data
                        bench_cfg = {"benchmarks": st.session_state.benchmarks}
                        results["kpi_report"] = calcular_kpis(fin_data, bench_cfg)
                        results["benchmark_config"] = st.session_state.benchmarks
                    except Exception as e:
                        errors["fase2"] = str(e)
                        results["error_fase2"] = str(e)
                timings["fase2"] = time.perf_counter() - t0

                # ── Fase 3: Modelo ML ──────────────────────────────────────
                t0 = time.perf_counter()
                if "fase1" not in errors and train_ml:
                    try:
                        from src.ml.trainer import train
                        from src.ml.predictor import predict_and_explain
                        from src.pipeline.shap_translator import translate_shap
                        save_path = f"models/{cliente_id}/xgboost_efficiency.pkl"
                        trained = train(results["bd_data"], save_path=save_path)
                        pred_report = predict_and_explain(trained, results["bd_data"])
                        results["prediction_report"] = pred_report
                        results["shap_narrative"] = translate_shap(pred_report, {})
                    except Exception as e:
                        errors["fase3"] = str(e)
                        results["error_fase3"] = str(e)
                timings["fase3"] = time.perf_counter() - t0

                # ── Fase 4: Forecast ───────────────────────────────────────
                t0 = time.perf_counter()
                if "fase2" not in errors:
                    try:
                        from src.pipeline.forecast import forecast_revenue
                        results["forecast"] = forecast_revenue(results["kpi_report"])
                    except Exception as e:
                        errors["fase4"] = str(e)
                        results["error_fase4"] = str(e)
                timings["fase4"] = time.perf_counter() - t0

                # ── Fase 5: Macro ──────────────────────────────────────────
                t0 = time.perf_counter()
                if include_macro:
                    try:
                        from src.pipeline.macro import MacroFetcher
                        fetcher = MacroFetcher()
                        macro_data = fetcher.fetch_all()
                        macro_idx = fetcher.calcular_indices(macro_data, {})
                        results["macro_data"] = macro_data
                        results["macro_indices"] = macro_idx
                    except Exception as e:
                        errors["fase5"] = str(e)
                        results["error_fase5"] = str(e)
                timings["fase5"] = time.perf_counter() - t0

                # ── Fase 6: Health Score ───────────────────────────────────
                t0 = time.perf_counter()
                if "fase2" not in errors:
                    try:
                        from src.pipeline.health_score import calcular_health_score
                        hs = calcular_health_score(
                            results["kpi_report"],
                            results.get("macro_indices"),
                            {"benchmarks": st.session_state.benchmarks},
                        )
                        results["health_score_report"] = hs
                    except Exception as e:
                        errors["fase6"] = str(e)
                        results["error_fase6"] = str(e)
                timings["fase6"] = time.perf_counter() - t0

                # ── Fase 7: Documentos ────────────────────────────────────
                t0 = time.perf_counter()
                if qual_tmps:
                    try:
                        from src.ingestion.document_loader import load_document
                        from src.ingestion.chunker import chunk_document
                        all_chunks = []
                        for path in qual_tmps:
                            doc = load_document(path, cliente_id=cliente_id)
                            all_chunks.extend(chunk_document(doc))
                        results["chunks"] = all_chunks
                    except Exception as e:
                        errors["fase7"] = str(e)
                        results["error_fase7"] = str(e)
                timings["fase7"] = time.perf_counter() - t0

                # ── Fase 8: Recomendaciones (LLM) ──────────────────────────
                t0 = time.perf_counter()
                if "fase2" not in errors:
                    try:
                        from src.pipeline.engine import CopilotEngine
                        engine = CopilotEngine()
                        report = engine.run_full_pipeline(
                            bd_filepath=bd_tmp,
                            er_filepath=er_tmp,
                            qualitative_filepaths=qual_tmps,
                            cliente_id=cliente_id,
                            train_model=train_ml,
                        )
                        results["copilot_report"] = report
                        results["prompt_used"] = engine.build_prompt(
                            results.get("kpi_report"),
                            results.get("health_score_report"),
                            results.get("macro_indices"),
                            results.get("shap_narrative"),
                            results.get("forecast"),
                            results.get("chunks", []),
                            st.session_state.get("scenario_result"),
                        ) if hasattr(engine, "build_prompt") else ""
                    except Exception as e:
                        errors["fase8"] = str(e)
                        results["error_fase8"] = str(e)
                timings["fase8"] = time.perf_counter() - t0

        finally:
            for p in [bd_tmp, er_tmp] + qual_tmps:
                if p:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

        st.session_state.timings = timings
        st.session_state.errors = errors
        st.session_state.results = results
        st.success("Pipeline completado.")
        st.rerun()

    results = st.session_state.results

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tabs = st.tabs([
        "Fase 1 — Parsers",
        "Fase 2 — KPIs y Benchmarking",
        "Fase 3 — Modelo ML",
        "Fase 4 — Forecast",
        "Fase 5 — Macro",
        "Fase 6 — Health Score",
        "Fase 6.5 — Simulador What-If",
        "Fase 7 — Documentos",
        "Fase 7.5 — Contexto LLM",
        "Fase 8 — Recomendaciones",
        "Fase 9 — Reporte PDF",
    ])

    with tabs[0]:
        _tab_parsers(st, results)
    with tabs[1]:
        _tab_kpis(st, results)
    with tabs[2]:
        _tab_modelo(st, results)
    with tabs[3]:
        _tab_forecast(st, results)
    with tabs[4]:
        _tab_macro(st, results)
    with tabs[5]:
        _tab_health(st, results)
    with tabs[6]:
        _tab_simulador(st, results)
    with tabs[7]:
        _tab_documentos(st, results)
    with tabs[8]:
        _tab_contexto_llm(st, results)
    with tabs[9]:
        _tab_recomendaciones(st, results)
    with tabs[10]:
        _tab_pdf(st, results)


# Run when executed via `streamlit run` (real streamlit is already in sys.modules)
if _is_real_streamlit():
    main()
