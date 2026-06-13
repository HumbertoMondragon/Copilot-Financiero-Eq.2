"""
Genera tablas LaTeX y visualizaciones PNG para el reporte académico.
Ejecutar desde la raíz del proyecto:
    python reporte/reporte_assets/generar_reporte.py
Salida: todos los archivos en reporte/reporte_assets/
"""
import math
import os
import re
import pickle
import sys
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

warnings.filterwarnings("ignore")

# ── Rutas ─────────────────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
# Necesario para que pickle pueda reconstruir TrainedModel (definido en src.ml.trainer)
PROJECT_ROOT = os.path.dirname(os.path.dirname(HERE))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
BD_PATH  = os.path.join(HERE, "BDN.csv")
ER_PATH  = os.path.join(HERE, "ERN.csv")
PKL_PATH = os.path.join(HERE, "..", "..", "models", "default", "xgboost_efficiency.pkl")

# ── Estilo global ──────────────────────────────────────────────────────────────
PALETTE = {
    "ANT": "#2A6EBB",
    "SOK": "#E87722",
    "JUR": "#2E8B57",
    "MOR": "#9B59B6",
    "CAM": "#C0392B",
}
CAT_COLORS = ["#2A6EBB", "#E87722", "#2E8B57", "#9B59B6", "#C0392B", "#F39C12"]

plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
})

DPI = 300

# ── Helpers de parseo ──────────────────────────────────────────────────────────
def _clean_currency(s) -> float:
    if s is None:
        return 0.0
    if isinstance(s, (int, float)):
        return 0.0 if math.isnan(float(s)) else float(s)
    s = str(s).strip()
    if not s or s.lower() == "nan":
        return 0.0
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[()\$,]", "", s).strip()
    try:
        v = float(s)
    except ValueError:
        return 0.0
    return -v if neg else v

MONTH_ORDER = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4,
    "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
    "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}

def _month_key(m: str):
    parts = str(m).split()
    if len(parts) >= 2:
        return (parts[1], MONTH_ORDER.get(parts[0], 0))
    return (m, 0)

# ── Carga BD ───────────────────────────────────────────────────────────────────
def load_bd(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    df.columns = [c.strip() for c in df.columns]

    rows = []
    for _, row in df.iterrows():
        mes = str(row.get("MES", "")).strip().upper()
        if not mes or mes == "NAN":
            continue
        suc  = str(row.get("LÍNEA DE NEGOCIO", "")).strip().upper()
        cat  = str(row.get("SUBCATEGORÍA 1", "")).strip()
        sku  = str(row.get("SUBCATEGORÍA 2", "")).strip()
        tag  = str(row.get("COL ESPECIAL 1", "")).strip()
        if cat.lower() in ("nan", ""):
            continue

        cantidad      = int(float(str(row.get("CANTIDAD", "0")).replace(",", "") or 0))
        subtotal      = _clean_currency(row.get("SUBTOTAL"))
        costo_sin_iva = _clean_currency(row.get("COSTO TOTAL SIN IVA"))
        utilidad      = _clean_currency(row.get("UTILIDAD BRUTA"))
        margen_raw    = _clean_currency(row.get("MARGEN BRUTO"))
        margen        = margen_raw / 100.0 if margen_raw > 1.0 else margen_raw

        if cantidad == 0 or costo_sin_iva == 0:
            continue

        multiplicador = utilidad / costo_sin_iva if costo_sin_iva else 0.0

        rows.append({
            "mes": mes,
            "sucursal": suc,
            "categoria": cat,
            "sku": sku,
            "tag_menu_1": tag if tag.lower() not in ("nan", "") else "OTRO",
            "cantidad": cantidad,
            "subtotal": subtotal,
            "costo_sin_iva": costo_sin_iva,
            "utilidad_bruta": utilidad,
            "margen_bruto": margen,
            "multiplicador_eficiencia": multiplicador,
        })
    return pd.DataFrame(rows)

# ── Carga ER ───────────────────────────────────────────────────────────────────
_KPI_MAP = {
    "NÓMINA": "nomina", "NOMINA": "nomina",
    "GASTOS COMERCIALES": "gastos_comerciales",
    "GASTOS OPERATIVOS": "gastos_operativos",
    "GASTOS ADMINISTRATIVOS": "gastos_administrativos",
    "VIÁTICOS": "viaticos", "VIATICOS": "viaticos",
    "TOTAL GASTOS DE OPERACIÓN": "total_gastos_operacion",
    "TOTAL GASTOS DE OPERACION": "total_gastos_operacion",
    "GASTOS FINANCIEROS": "gastos_financieros",
    "COSTO INTEGRAL DE FINANCIAMIENTO": "costo_integral_financiamiento",
    "IMPUESTOS": "impuestos",
}

def load_er(path: str) -> dict:
    df = pd.read_csv(path, header=None, encoding="utf-8-sig", dtype=str)
    header_row = df.iloc[1]
    month_cols = {}
    for i in range(1, len(header_row)):
        val = str(header_row.iloc[i]).strip().upper()
        if val and val not in ("NAN", "ACUMULADO", ""):
            month_cols[val] = i

    result = {m: {v: 0.0 for v in _KPI_MAP.values()} for m in month_cols}
    for i in range(2, len(df)):
        label = str(df.iloc[i, 0]).strip().upper()
        field = _KPI_MAP.get(label)
        if field is None:
            continue
        for mes, col_idx in month_cols.items():
            result[mes][field] = _clean_currency(df.iloc[i, col_idx] if col_idx < len(df.columns) else None)
    return result

# ── LaTeX helpers ──────────────────────────────────────────────────────────────
def _fmt_peso(v: float) -> str:
    return f"\\${v:,.0f}"

def _fmt_pct(v: float) -> str:
    return f"{v:.1%}".replace("%", "\\%")

def _fmt_f(v: float, dec: int = 2) -> str:
    return f"{v:,.{dec}f}"

def latex_table(caption: str, label: str, header: list[str],
                rows: list[list[str]], col_fmt: str) -> str:
    lines = [
        "\\begin{table}[H]",
        "  \\centering",
        f"  \\caption{{{caption}}}",
        f"  \\label{{{label}}}",
        f"  \\begin{{tabular}}{{{col_fmt}}}",
        "    \\toprule",
        "    " + " & ".join(header) + " \\\\",
        "    \\midrule",
    ]
    for r in rows:
        lines.append("    " + " & ".join(r) + " \\\\")
    lines += [
        "    \\bottomrule",
        "  \\end{tabular}",
        "\\end{table}",
    ]
    return "\n".join(lines)

# ══════════════════════════════════════════════════════════════════════════════
# CARGA DE DATOS
# ══════════════════════════════════════════════════════════════════════════════
print("Cargando datos...")
bd = load_bd(BD_PATH)
er = load_er(ER_PATH)

meses_ord = sorted(bd["mes"].unique(), key=_month_key)
sucursales = sorted(bd["sucursal"].unique())
categorias = sorted(bd["categoria"].unique())

print(f"  BD: {len(bd):,} registros | meses: {meses_ord} | sucursales: {sucursales}")

# ══════════════════════════════════════════════════════════════════════════════
# TAREA 1 — TABLAS LATEX
# ══════════════════════════════════════════════════════════════════════════════
print("\nGenerando tablas LaTeX...")

# ── T1.1 Estadísticas descriptivas variables numéricas ────────────────────────
num_cols = {
    "Subtotal (\\$)": "subtotal",
    "Costo sin IVA (\\$)": "costo_sin_iva",
    "Utilidad bruta (\\$)": "utilidad_bruta",
    "Margen bruto": "margen_bruto",
    "Cantidad (uds.)": "cantidad",
    "Multiplicador efic.": "multiplicador_eficiencia",
}
stats_rows = []
for label, col in num_cols.items():
    s = bd[col]
    stats_rows.append([
        label,
        _fmt_f(s.mean()),
        _fmt_f(s.median()),
        _fmt_f(s.std()),
        _fmt_f(s.min()),
        _fmt_f(s.quantile(0.25)),
        _fmt_f(s.quantile(0.75)),
        _fmt_f(s.max()),
    ])

tbl1 = latex_table(
    caption="Estadísticas descriptivas de las variables numéricas clave (BD Grupo Nama, enero--marzo 2026)",
    label="tab:desc_stats",
    header=["Variable", "Media", "Mediana", "DE", "Mín.", "P25", "P75", "Máx."],
    rows=stats_rows,
    col_fmt="lrrrrrrrr",
)

# ── T1.2 Resumen por sucursal ─────────────────────────────────────────────────
suc_rows = []
for suc in sucursales:
    sub = bd[bd["sucursal"] == suc]
    suc_rows.append([
        suc,
        _fmt_peso(sub["subtotal"].sum()),
        _fmt_pct(sub["margen_bruto"].mean()),
        str(sub["sku"].nunique()),
        str(len(sub)),
    ])

tbl2 = latex_table(
    caption="Resumen por sucursal (enero--marzo 2026)",
    label="tab:suc_summary",
    header=["Sucursal", "Ingresos totales", "Margen bruto prom.", "SKUs distintos", "Registros"],
    rows=suc_rows,
    col_fmt="lrrrr",
)

# ── T1.3 Resumen por categoría ────────────────────────────────────────────────
cat_rows = []
for cat in categorias:
    sub = bd[bd["categoria"] == cat]
    cat_rows.append([
        cat,
        _fmt_peso(sub["subtotal"].sum()),
        _fmt_pct(sub["margen_bruto"].mean()),
        str(sub["sku"].nunique()),
    ])
# Ordenar por ingresos desc
cat_rows.sort(key=lambda r: -float(r[1].replace("\\$", "").replace(",", "")))

tbl3 = latex_table(
    caption="Resumen por categoría (enero--marzo 2026)",
    label="tab:cat_summary",
    header=["Categoría", "Ingresos totales", "Margen bruto prom.", "SKUs distintos"],
    rows=cat_rows,
    col_fmt="lrrr",
)

# Guardar tablas
tables_out = os.path.join(HERE, "tablas_latex.tex")
with open(tables_out, "w", encoding="utf-8") as f:
    preamble = (
        "% Requiere: \\usepackage{booktabs} \\usepackage{float} en el preámbulo\n\n"
    )
    f.write(preamble)
    f.write("% ── Tabla 1: Estadísticas descriptivas ──────────────────────────\n")
    f.write(tbl1 + "\n\n")
    f.write("% ── Tabla 2: Resumen por sucursal ───────────────────────────────\n")
    f.write(tbl2 + "\n\n")
    f.write("% ── Tabla 3: Resumen por categoría ──────────────────────────────\n")
    f.write(tbl3 + "\n")
print("  tablas_latex.tex")

# ══════════════════════════════════════════════════════════════════════════════
# TAREA 2 — VISUALIZACIONES
# ══════════════════════════════════════════════════════════════════════════════
print("\nGenerando visualizaciones...")

# ── V1 Boxplot margen bruto por sucursal ──────────────────────────────────────
fig, ax = plt.subplots(figsize=(7, 4))
data_box = [bd[bd["sucursal"] == s]["margen_bruto"].values for s in sucursales]
bp = ax.boxplot(data_box, patch_artist=True, notch=False,
                medianprops={"color": "white", "linewidth": 2},
                whiskerprops={"linewidth": 1.2},
                capprops={"linewidth": 1.2},
                flierprops={"marker": "o", "markersize": 3, "alpha": 0.4})
for patch, suc in zip(bp["boxes"], sucursales):
    patch.set_facecolor(PALETTE[suc])
    patch.set_alpha(0.85)
ax.set_xticklabels(sucursales)
ax.set_xlabel("Sucursal")
ax.set_ylabel("Margen bruto")
ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1, decimals=0))
ax.set_title("Distribución del margen bruto por sucursal\n(enero–marzo 2026)")
ax.axhline(bd["margen_bruto"].mean(), color="gray", linestyle="--",
           linewidth=1, label=f"Media global {bd['margen_bruto'].mean():.1%}")
ax.legend(fontsize=9)
plt.tight_layout()
p1 = os.path.join(HERE, "fig1_boxplot_margen_sucursal.png")
fig.savefig(p1, dpi=DPI, bbox_inches="tight")
plt.close()
print("  fig1_boxplot_margen_sucursal.png")

# ── V2 Bar chart ingresos por categoría (horizontal) ─────────────────────────
cat_ing = bd.groupby("categoria")["subtotal"].sum().sort_values(ascending=True)
fig, ax = plt.subplots(figsize=(7, 4))
bars = ax.barh(cat_ing.index, cat_ing.values,
               color=CAT_COLORS[:len(cat_ing)], alpha=0.88, height=0.6)
for bar, val in zip(bars, cat_ing.values):
    ax.text(val + cat_ing.max() * 0.01, bar.get_y() + bar.get_height() / 2,
            f"${val/1e6:.1f}M", va="center", ha="left", fontsize=9)
ax.set_xlabel("Ingresos totales (MXN)")
ax.set_title("Ingresos totales por categoría\n(enero–marzo 2026)")
ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x/1e6:.0f}M"))
ax.set_xlim(0, cat_ing.max() * 1.18)
plt.tight_layout()
p2 = os.path.join(HERE, "fig2_barras_ingresos_categoria.png")
fig.savefig(p2, dpi=DPI, bbox_inches="tight")
plt.close()
print("  fig2_barras_ingresos_categoria.png")

# ── V3 Evolución mensual de ingresos por sucursal ────────────────────────────
suc_mes = (bd.groupby(["mes", "sucursal"])["subtotal"]
             .sum()
             .reset_index())
fig, ax = plt.subplots(figsize=(7, 4))
for suc in sucursales:
    sub = suc_mes[suc_mes["sucursal"] == suc].sort_values("mes", key=lambda s: s.map(_month_key))
    ax.plot(sub["mes"].str.split().str[0].str.capitalize(),
            sub["subtotal"] / 1e6,
            marker="o", linewidth=2, markersize=6,
            color=PALETTE[suc], label=suc)
ax.set_xlabel("Mes")
ax.set_ylabel("Ingresos (millones MXN)")
ax.set_title("Evolución mensual de ingresos por sucursal")
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:.1f}M"))
ax.legend(title="Sucursal", fontsize=9)
plt.tight_layout()
p3 = os.path.join(HERE, "fig3_evolucion_ingresos_sucursal.png")
fig.savefig(p3, dpi=DPI, bbox_inches="tight")
plt.close()
print("  fig3_evolucion_ingresos_sucursal.png")

# ── V4 Importancia SHAP global ────────────────────────────────────────────────
print("  Cargando modelo y calculando SHAP...")
try:
    import shap

    with open(PKL_PATH, "rb") as fh:
        trained = pickle.load(fh)

    model       = trained.model
    le_dict     = trained.label_encoders
    cat_stats   = trained.category_stats
    feat_names  = trained.feature_names

    # Construir matrix de features para todos los registros
    registros = bd.to_dict("records")
    # Calcular stats de categoría sobre todos los registros
    cat_precios = {}
    cat_costos  = {}
    for r in registros:
        qty = r["cantidad"]
        if qty <= 0:
            continue
        cat = r["categoria"]
        cat_precios.setdefault(cat, []).append(r["subtotal"] / qty)
        cat_costos.setdefault(cat, []).append(r["costo_sin_iva"] / qty)
    cat_stats_live = {
        cat: {
            "mean_precio": float(np.mean(cat_precios[cat])) if cat in cat_precios else 1.0,
            "mean_costo":  float(np.mean(cat_costos[cat]))  if cat in cat_costos  else 1.0,
        }
        for cat in set(cat_precios) | set(cat_costos)
    }

    feat_rows = []
    for r in registros:
        qty = r["cantidad"]
        if qty <= 0:
            continue
        pu = r["subtotal"] / qty
        cu = r["costo_sin_iva"] / qty
        tag = r["tag_menu_1"] if r["tag_menu_1"] else "OTRO"

        mes_parts = r["mes"].split()
        mes_num = float(MONTH_ORDER.get(mes_parts[0], 0)) if mes_parts else 0.0

        cstat = cat_stats_live.get(r["categoria"], {"mean_precio": 1.0, "mean_costo": 1.0})
        mp = cstat["mean_precio"] or 1.0
        mc = cstat["mean_costo"]  or 1.0

        def _encode(col, val):
            le = le_dict[col]
            return float(le.transform([val])[0]) if val in set(le.classes_) else 0.0

        feat_rows.append([
            _encode("sucursal", r["sucursal"]),
            _encode("categoria", r["categoria"]),
            _encode("tag_menu_1", tag),
            pu,
            cu,
            mes_num,
            float(np.log(qty + 1)),
            pu / mp,
            cu / mc,
        ])

    X = pd.DataFrame(feat_rows, columns=feat_names)

    # Subsample para velocidad (máx 3000 filas)
    rng_shap = np.random.default_rng(42)
    idx = rng_shap.choice(len(X), size=min(3000, len(X)), replace=False)
    X_sample = X.iloc[idx]

    explainer   = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_sample)
    mean_abs    = np.abs(shap_values).mean(axis=0)

    feat_labels = {
        "sucursal": "Sucursal",
        "categoria": "Categoría",
        "tag_menu_1": "Etiqueta menú",
        "precio_unitario": "Precio unitario",
        "costo_unitario": "Costo unitario",
        "mes_num": "Mes",
        "log_cantidad": "log(Cantidad)",
        "precio_vs_categoria_avg": "Precio vs. promedio cat.",
        "costo_vs_categoria_avg": "Costo vs. promedio cat.",
    }

    order      = np.argsort(mean_abs)
    feat_sorted = [feat_labels.get(feat_names[i], feat_names[i]) for i in order]
    vals_sorted = mean_abs[order]

    fig, ax = plt.subplots(figsize=(7, 5))
    bars = ax.barh(feat_sorted, vals_sorted,
                   color="#2A6EBB", alpha=0.85, height=0.6)
    for bar, val in zip(bars, vals_sorted):
        ax.text(val + max(vals_sorted) * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{val:.3f}", va="center", ha="left", fontsize=9)
    ax.set_xlabel("|Valor SHAP| promedio")
    ax.set_title("Importancia global de variables (SHAP)\nModelo XGBoost — multiplicador de eficiencia")
    ax.set_xlim(0, max(vals_sorted) * 1.18)
    plt.tight_layout()
    p4 = os.path.join(HERE, "fig4_shap_importancia_global.png")
    fig.savefig(p4, dpi=DPI, bbox_inches="tight")
    plt.close()
    print("  fig4_shap_importancia_global.png")
    shap_ok = True

except Exception as e:
    print(f"  ADVERTENCIA SHAP: {e}")
    shap_ok = False

# ── V5 Histograma Monte Carlo — margen bruto marzo 2026 ──────────────────────
print("  Simulando Monte Carlo (10,000 iter.)...")
marzo = bd[bd["mes"] == "MARZO 2026"]
revenue_base      = marzo["subtotal"].sum()
costo_dir_base    = marzo["costo_sin_iva"].sum()
er_marzo          = er.get("MARZO 2026", {})
nomina_base       = er_marzo.get("nomina", 0.0)
gastos_fin_base   = er_marzo.get("gastos_financieros", 0.0)
total_gastos_base = er_marzo.get("total_gastos_operacion", 0.0)
otros_gastos      = total_gastos_base - nomina_base

N   = 10_000
rng = np.random.default_rng(42)
SIGMAS = {"revenue": 0.05, "costo_directo": 0.04, "nomina": 0.03, "gastos_financieros": 0.02}
VARIACIONES = {"revenue": 0.05, "costo_directo": -0.05, "nomina": 0.0, "gastos_financieros": 0.0}

r_rev  = 1 + VARIACIONES["revenue"]       + rng.normal(0, SIGMAS["revenue"],       N)
r_cos  = 1 + VARIACIONES["costo_directo"] + rng.normal(0, SIGMAS["costo_directo"], N)
r_nom  = 1 + VARIACIONES["nomina"]        + rng.normal(0, SIGMAS["nomina"],        N)
r_gfin = 1 + VARIACIONES["gastos_financieros"] + rng.normal(0, SIGMAS["gastos_financieros"], N)

rev_sim   = revenue_base   * r_rev
cos_sim   = costo_dir_base * r_cos
ub_sim    = rev_sim - cos_sim
safe_rev  = np.where(rev_sim > 0, rev_sim, np.nan)
mb_sim    = ub_sim / safe_rev
mb_clean  = mb_sim[~np.isnan(mb_sim)]

benchmark_mb = 0.68
p10, p50, p90 = np.percentile(mb_clean, [10, 50, 90])
prob_sobre    = float(np.mean(mb_clean >= benchmark_mb))

fig, ax = plt.subplots(figsize=(7, 4))
ax.hist(mb_clean, bins=80, color="#2A6EBB", alpha=0.75, edgecolor="none", density=True)
ax.axvline(p50,          color="#E87722", linewidth=2,   linestyle="-",  label=f"Mediana {p50:.1%}")
ax.axvline(benchmark_mb, color="#C0392B", linewidth=1.8, linestyle="--", label=f"Benchmark {benchmark_mb:.0%}")
ax.axvspan(p10, p90, alpha=0.12, color="#2A6EBB", label=f"Rango P10–P90 ({p10:.1%}–{p90:.1%})")
ax.xaxis.set_major_formatter(mticker.PercentFormatter(xmax=1, decimals=0))
ax.set_xlabel("Margen bruto simulado")
ax.set_ylabel("Densidad")
ax.set_title(
    f"Distribución Monte Carlo del margen bruto — marzo 2026\n"
    f"Escenario: revenue +5\\% / costo directo −5\\%   "
    f"(n = {N:,} simulaciones,  P(MB ≥ benchmark) = {prob_sobre:.1%})"
)
ax.legend(fontsize=9)
plt.tight_layout()
p5 = os.path.join(HERE, "fig5_montecarlo_margen_bruto.png")
fig.savefig(p5, dpi=DPI, bbox_inches="tight")
plt.close()
print("  fig5_montecarlo_margen_bruto.png")

# ══════════════════════════════════════════════════════════════════════════════
# RESUMEN FINAL
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("Archivos generados en reporte_assets/")
print("=" * 60)
print("  TABLAS LaTeX:")
print("    tablas_latex.tex")
print("  FIGURAS PNG (300 DPI):")
print("    fig1_boxplot_margen_sucursal.png")
print("    fig2_barras_ingresos_categoria.png")
print("    fig3_evolucion_ingresos_sucursal.png")
if shap_ok:
    print("    fig4_shap_importancia_global.png")
else:
    print("    fig4_shap_importancia_global.png  (OMITIDA - ver advertencia)")
print("    fig5_montecarlo_margen_bruto.png")
print()
print("Uso en LaTeX:")
print('  \\input{reporte_assets/tablas_latex.tex}')
print('  \\includegraphics[width=\\linewidth]{reporte_assets/fig1_boxplot_margen_sucursal}')
