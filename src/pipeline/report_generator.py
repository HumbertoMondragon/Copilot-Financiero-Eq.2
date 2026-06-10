"""PDF report generator — fpdf2 with Arial (Unicode) for professional output."""
from __future__ import annotations

import os
import textwrap
import unicodedata
from datetime import datetime
from typing import Any, Optional

try:
    from fpdf import FPDF, XPos, YPos
    _FPDF_OK = True
except ImportError:
    _FPDF_OK = False

# ── Font paths (Windows first, then common Linux/Mac locations) ───────────────
def _find_font(names: list[str]) -> str | None:
    search = [
        r"C:\Windows\Fonts",
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/truetype/liberation",
        "/Library/Fonts",
        os.path.join(os.path.dirname(__file__), "fonts"),
    ]
    for folder in search:
        for name in names:
            path = os.path.join(folder, name)
            if os.path.exists(path):
                return path
    return None

_FONT_REG  = _find_font(["arial.ttf",    "Arial.ttf",    "DejaVuSans.ttf",         "LiberationSans-Regular.ttf"])
_FONT_BOLD = _find_font(["arialbd.ttf",  "Arial Bold.ttf","DejaVuSans-Bold.ttf",    "LiberationSans-Bold.ttf"])
_FONT_ITAL = _find_font(["ariali.ttf",   "Arial Italic.ttf","DejaVuSans-Oblique.ttf","LiberationSans-Italic.ttf"])
_USE_UNICODE = bool(_FONT_REG)

# ── Palette ───────────────────────────────────────────────────────────────────
_DARK_BLUE   = (18,  50,  90)
_MID_BLUE    = (52, 120, 200)
_ACCENT_BLUE = (210, 228, 252)
_GREEN       = (34, 154,  60)
_YELLOW      = (230, 175,   0)
_ORANGE      = (220, 110,   0)
_RED         = (200,  45,  45)
_GRAY        = (110, 118, 130)
_LIGHT_GRAY  = (242, 244, 248)
_WHITE       = (255, 255, 255)
_BLACK       = ( 28,  30,  36)


def _score_color(score: float):
    if score >= 75: return _GREEN
    if score >= 55: return _YELLOW
    if score >= 35: return _ORANGE
    return _RED


def _estado_color(estado: str):
    return {"en_rango": _GREEN, "alerta": _YELLOW, "critico": _RED}.get(estado, _GRAY)


def _t(text: Any, max_len: int = 0) -> str:
    """Make text safe for PDF: strip non-ASCII if no unicode font available."""
    s = str(text) if text is not None else ""
    if not _USE_UNICODE:
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    if max_len and len(s) > max_len:
        s = s[:max_len - 1] + "..."
    return s


# ── PDF class ─────────────────────────────────────────────────────────────────

class _PDF(FPDF):
    _cliente: str = ""
    _periodo: str = ""
    _font: str = "Helvetica"

    def setup_fonts(self):
        if _USE_UNICODE:
            self.add_font("Main",  "",  _FONT_REG)
            if _FONT_BOLD: self.add_font("Main", "B", _FONT_BOLD)
            if _FONT_ITAL: self.add_font("Main", "I", _FONT_ITAL)
            self._font = "Main"

    def f(self, style: str = "", size: int = 10):
        self.set_font(self._font, style, size)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_fill_color(*_DARK_BLUE)
        self.rect(0, 0, 210, 11, "F")
        self.set_text_color(*_WHITE)
        self.f("B", 7)
        self.set_xy(10, 2)
        self.cell(130, 7, _t(f"Copilot Financiero  |  {self._cliente}  |  {self._periodo}"),
                  new_x=XPos.RIGHT)
        self.f("", 7)
        self.cell(0, 7, _t(datetime.now().strftime("%d/%m/%Y")), align="R",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*_BLACK)
        self.ln(3)

    def footer(self):
        self.set_y(-13)
        self.set_draw_color(*_LIGHT_GRAY)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(1)
        self.f("", 7)
        self.set_text_color(*_GRAY)
        self.cell(0, 5, _t(f"Pagina {self.page_no()}  |  Generado el {datetime.now().strftime('%d/%m/%Y a las %H:%M')}  |  Uso confidencial"),
                  align="C")
        self.set_text_color(*_BLACK)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def section_title(self, text: str):
        self.ln(5)
        x, y = self.get_x(), self.get_y()
        # Left accent bar
        self.set_fill_color(*_MID_BLUE)
        self.rect(x, y, 3, 7, "F")
        # Title background
        self.set_fill_color(*_ACCENT_BLUE)
        self.rect(x + 3, y, 187, 7, "F")
        self.set_text_color(*_DARK_BLUE)
        self.f("B", 10)
        self.set_xy(x + 7, y)
        self.cell(183, 7, _t(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*_BLACK)
        self.ln(3)

    def kv_row(self, label: str, value: str, bold_val: bool = False):
        self.f("", 8)
        self.set_text_color(*_GRAY)
        self.cell(58, 5, _t(label), new_x=XPos.RIGHT)
        self.f("B" if bold_val else "", 8)
        self.set_text_color(*_BLACK)
        self.cell(0, 5, _t(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def h_bar(self, label: str, value: float, max_val: float, color,
              bar_w: int = 85, suffix: str = ""):
        x0, y0 = self.get_x(), self.get_y()
        # Label
        self.f("", 8)
        self.set_text_color(*_GRAY)
        self.cell(62, 5, _t(label, 36), new_x=XPos.RIGHT)
        self.set_text_color(*_BLACK)
        # Background track
        bx = self.get_x()
        self.set_fill_color(225, 228, 235)
        self.rect(bx, y0 + 0.8, bar_w, 3.5, "F")
        # Filled portion
        filled = int(bar_w * min(max(value / max_val, 0), 1)) if max_val else 0
        if filled > 0:
            self.set_fill_color(*color)
            self.rect(bx, y0 + 0.8, filled, 3.5, "F")
        # Suffix label
        self.set_xy(bx + bar_w + 2, y0)
        self.f("B", 8)
        self.cell(28, 5, _t(suffix), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def badge(self, text: str, color, w: int = 24):
        self.set_fill_color(*color)
        self.set_text_color(*_WHITE)
        self.f("B", 7)
        self.cell(w, 5, _t(text), fill=True, align="C", new_x=XPos.RIGHT)
        self.set_text_color(*_BLACK)

    def divider(self):
        self.ln(2)
        self.set_draw_color(*_LIGHT_GRAY)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(3)

    def wrapped(self, text: str, size: int = 9, indent: int = 0, lh: float = 4.8):
        self.f("", size)
        self.set_x(10 + indent)
        self.multi_cell(190 - indent, lh, _t(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def info_box(self, text: str, color=None):
        color = color or _ACCENT_BLUE
        self.set_fill_color(*color)
        self.f("I", 8)
        x, y = self.get_x(), self.get_y()
        self.rect(x, y, 190, 1, "F")
        self.set_x(12)
        self.set_fill_color(*color)
        self.multi_cell(188, 4.5, _t(text), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_fill_color(*color)
        self.cell(190, 1, "", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.f("", 9)
        self.ln(2)


# ── Page builders ─────────────────────────────────────────────────────────────

def _portada(pdf: _PDF, cliente_id: str, periodo: str, score: float,
             categoria: str, narrativa: str):
    pdf.add_page()

    # Top band
    pdf.set_fill_color(*_DARK_BLUE)
    pdf.rect(0, 0, 210, 62, "F")

    # Title
    pdf.set_text_color(*_WHITE)
    pdf.set_xy(14, 12)
    pdf.f("B", 22)
    pdf.cell(0, 10, "Reporte Financiero Ejecutivo", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_xy(14, 26)
    pdf.f("", 11)
    pdf.cell(0, 7, _t(f"Cliente: {cliente_id.upper()}   |   Periodo: {periodo}"),
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_xy(14, 36)
    pdf.f("I", 9)
    pdf.cell(0, 6, _t(f"Generado el {datetime.now().strftime('%d de %B de %Y')}"),
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Health score box (right side of band)
    sc = _score_color(score)
    pdf.set_fill_color(*sc)
    pdf.rect(148, 5, 54, 52, "F")
    pdf.set_text_color(*_WHITE)
    pdf.set_xy(148, 9)
    pdf.f("", 8)
    pdf.cell(54, 6, "HEALTH SCORE", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_xy(148, 16)
    pdf.f("B", 34)
    pdf.cell(54, 18, f"{score:.0f}", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_xy(148, 36)
    pdf.f("", 8)
    pdf.cell(54, 5, "/ 100", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_xy(148, 43)
    pdf.f("B", 9)
    pdf.cell(54, 7, _t(categoria.upper().replace("_", " ")), align="C",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*_BLACK)

    # Resumen ejecutivo
    pdf.set_xy(10, 72)
    pdf.f("B", 10)
    pdf.set_text_color(*_DARK_BLUE)
    pdf.cell(0, 6, "Resumen ejecutivo", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*_BLACK)
    pdf.ln(1)
    if narrativa:
        pdf.info_box(narrativa)

    # Leyenda de colores
    pdf.ln(8)
    pdf.set_xy(10, pdf.get_y())
    pdf.f("B", 8)
    pdf.set_text_color(*_GRAY)
    pdf.cell(0, 5, "Codigo de salud financiera:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    for label, color in [("Saludable (75-100)", _GREEN), ("En observacion (55-74)", _YELLOW),
                         ("En riesgo (35-54)", _ORANGE), ("Critico (0-34)", _RED)]:
        pdf.set_fill_color(*color)
        pdf.rect(pdf.get_x(), pdf.get_y() + 1, 4, 4, "F")
        pdf.set_x(pdf.get_x() + 6)
        pdf.f("", 8)
        pdf.set_text_color(*_BLACK)
        pdf.cell(50, 5, _t(label), new_x=XPos.RIGHT)
    pdf.ln(8)

    # Tabla de contenidos
    pdf.divider()
    pdf.f("B", 9)
    pdf.set_text_color(*_DARK_BLUE)
    pdf.cell(0, 5, "Contenido de este reporte:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*_BLACK)
    pdf.ln(1)
    items = [
        "1. KPIs y benchmarking sectorial",
        "2. Dimensiones del Health Score",
        "3. Analisis de eficiencia (Machine Learning / SHAP)",
        "4. Forecast de ingresos y contexto macroeconomico",
        "5. Contexto macroeconomico sectorial (giro del negocio)",
        "6. Simulacion de escenarios Monte Carlo",
        "7. Recomendaciones del copilot",
    ]
    for item in items:
        pdf.f("", 8)
        pdf.set_text_color(*_GRAY)
        pdf.cell(5, 5, "-", new_x=XPos.RIGHT)
        pdf.set_text_color(*_BLACK)
        pdf.cell(0, 5, _t(item), new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _pagina_kpis(pdf: _PDF, kpi_report, health_report):
    pdf.add_page()
    mes = kpi_report.meses_analizados[-1]
    con = kpi_report.por_mes[mes]["consolidado"]
    hs = health_report.por_mes[mes]

    pdf.section_title(f"KPIs Consolidados  |  {mes}")

    # KPI metric cards (2 rows x 3 cols)
    cards = [
        ("Ingresos Totales",    f"${con.get('total_revenue', 0)/1e6:.2f} M",    _MID_BLUE),
        ("Margen Bruto",        f"{con.get('margen_bruto', 0):.1%}",            _score_color(con.get('margen_bruto', 0) / 0.68 * 75)),
        ("EBITDA",              f"${con.get('ebitda', 0)/1e6:.2f} M",           _MID_BLUE),
        ("Margen Neto",         f"{con.get('margen_neto', 0):.1%}",             _MID_BLUE),
        ("Nomina / Ingresos",   f"{con.get('nomina_pct', 0):.1%}",              _GRAY),
        ("Gastos Fin. / Ingr.", f"{con.get('gastos_financieros_pct', 0):.1%}", _GRAY),
    ]
    card_w, card_h = 59, 18
    gap = 5
    start_x = 12
    cy_row0 = pdf.get_y()
    for i, (label, val, color) in enumerate(cards):
        col, row = i % 3, i // 3
        cx = start_x + col * (card_w + gap)

        pdf.set_fill_color(*_DARK_BLUE if color == _MID_BLUE else color)
        pdf.rect(cx, cy_row0 + row * (card_h + 4), card_w, card_h, "F")
        pdf.set_text_color(*_WHITE)
        pdf.set_xy(cx, cy_row0 + row * (card_h + 4) + 2)
        pdf.f("B", 13)
        pdf.cell(card_w, 8, _t(val), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_xy(cx, cy_row0 + row * (card_h + 4) + 11)
        pdf.f("", 7)
        pdf.cell(card_w, 5, _t(label), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*_BLACK)
    pdf.set_y(cy_row0 + 2 * (card_h + 4) + 4)

    # vs Benchmark table
    pdf.section_title("Indicadores vs Benchmark Sectorial")

    # Header
    headers = [("Indicador", 58), ("Valor actual", 30), ("Benchmark", 30),
               ("Diferencia", 30), ("Estado", 30)]
    pdf.set_fill_color(*_DARK_BLUE)
    pdf.set_text_color(*_WHITE)
    pdf.f("B", 8)
    for h, w in headers:
        pdf.cell(w, 6, _t(h), fill=True, align="C", new_x=XPos.RIGHT)
    pdf.ln()
    pdf.set_text_color(*_BLACK)

    vs = kpi_report.por_mes[mes].get("vs_benchmark", {})
    label_map = {
        "margen_bruto":             "Margen Bruto",
        "costo_directo_pct":        "Costo Directo %",
        "nomina_pct":               "Nomina %",
        "gastos_op_pct":            "Gastos Operativos %",
        "gastos_financieros_pct":   "Gastos Financieros %",
        "margen_neto":              "Margen Neto",
    }
    for row_i, (key, label) in enumerate(label_map.items()):
        if key not in vs:
            continue
        item = vs[key]
        estado = item.get("estado", "")
        ec = _estado_color(estado)
        bg = _LIGHT_GRAY if row_i % 2 == 0 else _WHITE
        pdf.set_fill_color(*bg)
        pdf.f("", 8)
        pdf.cell(58, 5.5, _t(label), fill=True, new_x=XPos.RIGHT)
        dif = item.get("diferencia", 0)
        for val, w in [
            (f"{item.get('valor', 0):.2%}", 30),
            (f"{item.get('benchmark', 0):.2%}", 30),
            (f"{dif:+.2%}", 30),
        ]:
            pdf.cell(w, 5.5, _t(val), fill=True, align="C", new_x=XPos.RIGHT)
        pdf.set_fill_color(*ec)
        pdf.set_text_color(*_WHITE)
        pdf.f("B", 7)
        pdf.cell(30, 5.5, _t(estado.upper()), fill=True, align="C",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(*_BLACK)

    # Health Score dimensions chart
    pdf.section_title("Dimensiones del Health Score")
    dims = hs.get("dimensiones", {})
    dim_labels = {
        "margen_bruto_vs_benchmark":        "Margen Bruto vs Benchmark",
        "nomina_vs_benchmark":              "Nomina vs Benchmark",
        "gastos_financieros_vs_benchmark":  "Gastos Financieros vs Benchmark",
        "presion_inflacionaria":            "Presion Inflacionaria",
        "tendencia_ingresos":               "Tendencia de Ingresos",
    }
    score_total = hs.get("score_total", 0)
    pdf.f("B", 9)
    pdf.set_text_color(*_DARK_BLUE)
    pdf.cell(0, 5, _t(f"Score total: {score_total:.1f} / 100  ({_t(hs.get('categoria', ''))})"),
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*_BLACK)
    pdf.ln(2)
    debil = hs.get("dimension_mas_debil", "")
    for key, label in dim_labels.items():
        if key not in dims:
            continue
        d = dims[key]
        score = d.get("score", 0)
        peso = d.get("peso", 0)
        contrib = d.get("contribucion", 0)
        color = _score_color(score)
        suffix = f"{score:.0f}/100  (peso {peso:.0%}, aporta {contrib:.1f} pts)"
        if key == debil:
            pdf.set_text_color(*_RED)
            pdf.f("B", 8)
            pdf.cell(0, 4, _t(f"  << Dimension mas debil"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(*_BLACK)
        pdf.h_bar(label, score, 100, color, bar_w=75, suffix=suffix)
        pdf.ln(2)


def _pagina_shap(pdf: _PDF, shap_narrative):
    if shap_narrative is None:
        return
    pdf.add_page()
    pdf.section_title("Analisis de Eficiencia | Machine Learning + SHAP")

    pdf.f("", 8)
    pdf.set_text_color(*_GRAY)
    pdf.wrapped(
        "Los valores SHAP miden cuanto contribuye cada variable a la prediccion del multiplicador "
        "de eficiencia por SKU. Valor positivo = empuja el multiplicador hacia arriba; "
        "negativo = lo arrastra hacia abajo. La suma de todos los SHAP values mas el valor base "
        "equivale exactamente a la prediccion final.", size=8)
    pdf.set_text_color(*_BLACK)
    pdf.ln(2)

    global_data = getattr(shap_narrative, "global_", {})
    narrativa = global_data.get("narrativa", "")
    if narrativa:
        pdf.info_box(narrativa)

    top3 = global_data.get("top_3_factores_descripcion", [])
    if top3:
        pdf.f("B", 9)
        pdf.cell(0, 5, "Importancia global de factores (mean |SHAP|):",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1)
        max_imp = max((f.get("importancia", 0) for f in top3), default=1)
        for f in top3:
            imp = f.get("importancia", 0)
            pdf.h_bar(f["feature"], imp, max_imp or 1, _MID_BLUE, bar_w=75,
                      suffix=f"{imp:.4f}")
            pdf.ln(1)
        pdf.ln(3)

        pdf.f("B", 9)
        pdf.cell(0, 5, "Detalle de los 3 principales factores:",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        for f in top3:
            pdf.ln(2)
            # Feature header
            pdf.set_fill_color(*_ACCENT_BLUE)
            pdf.set_xy(10, pdf.get_y())
            pdf.f("B", 9)
            pdf.set_text_color(*_DARK_BLUE)
            pdf.cell(190, 5.5,
                     _t(f"  {f['feature']}  (importancia: {f.get('importancia', 0):.4f})"),
                     fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(*_BLACK)
            desc = f.get("descripcion", "")
            if desc:
                pdf.wrapped(desc, size=8, indent=4)

    por_suc = getattr(shap_narrative, "por_sucursal_mes", {})
    if por_suc:
        pdf.ln(4)
        pdf.f("B", 9)
        pdf.cell(0, 5, "Resumen por sucursal / mes (primeras 4):",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        for key, data in list(por_suc.items())[:4]:
            if pdf.get_y() > 255:
                pdf.add_page()
            pdf.ln(2)
            pdf.set_fill_color(*_LIGHT_GRAY)
            pdf.f("B", 8)
            pdf.cell(190, 5, _t(f"  {key}"), fill=True,
                     new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            narr = data.get("narrativa", "")
            if narr:
                pdf.wrapped(narr, size=8, indent=4)
            factores = data.get("factores", [])
            if factores:
                pdf.ln(1)
                pdf.set_fill_color(*_DARK_BLUE)
                pdf.set_text_color(*_WHITE)
                pdf.f("B", 7)
                for h, w in [("Factor", 55), ("SHAP", 22), ("Direccion", 25),
                              ("Magnitud", 25), ("Descripcion", 63)]:
                    pdf.cell(w, 5, _t(h), fill=True, align="C", new_x=XPos.RIGHT)
                pdf.ln()
                pdf.set_text_color(*_BLACK)
                for fi, fac in enumerate(factores[:5]):
                    bg = _LIGHT_GRAY if fi % 2 == 0 else _WHITE
                    pdf.set_fill_color(*bg)
                    pdf.f("", 7)
                    shap_val = fac.get("shap", 0)
                    shap_color = _GREEN if shap_val > 0 else _RED
                    pdf.cell(55, 4.5, _t(fac.get("feature", "")), fill=True, new_x=XPos.RIGHT)
                    pdf.set_text_color(*shap_color)
                    pdf.f("B", 7)
                    pdf.cell(22, 4.5, _t(f"{shap_val:+.4f}"), fill=True, align="C", new_x=XPos.RIGHT)
                    pdf.set_text_color(*_BLACK)
                    pdf.f("", 7)
                    for val, w in [
                        (fac.get("direccion", ""), 25),
                        (fac.get("magnitud", ""), 25),
                        (_t(fac.get("descripcion", ""), 50), 63),
                    ]:
                        pdf.cell(w, 4.5, _t(val), fill=True, new_x=XPos.RIGHT)
                    pdf.ln()


def _pagina_forecast_macro(pdf: _PDF, forecast_result, macro_indices):
    if forecast_result is None and macro_indices is None:
        return
    pdf.add_page()

    if forecast_result is not None:
        pdf.section_title("Forecast de Ingresos")
        # Big metric boxes
        items = [
            ("Mes proyectado",     _t(forecast_result.mes_proyectado)),
            ("Ingreso proyectado", f"${forecast_result.revenue_proyectado:,.0f}"),
            ("Tendencia",          _t(forecast_result.tendencia)),
            ("Confianza",          _t(forecast_result.confianza)),
        ]
        box_w = 44
        for i, (label, val) in enumerate(items):
            cx = 10 + i * (box_w + 3)
            cy = pdf.get_y()
            tc = _MID_BLUE if i <= 1 else (_GRAY)
            pdf.set_fill_color(*tc)
            pdf.rect(cx, cy, box_w, 16, "F")
            pdf.set_text_color(*_WHITE)
            pdf.set_xy(cx, cy + 1)
            pdf.f("B", 10)
            pdf.cell(box_w, 7, _t(val), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_xy(cx, cy + 9)
            pdf.f("", 7)
            pdf.cell(box_w, 5, _t(label), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(*_BLACK)
        pdf.ln(20)

        if forecast_result.advertencia:
            pdf.set_text_color(*_ORANGE)
            pdf.f("I", 8)
            pdf.cell(4, 5, "!", new_x=XPos.RIGHT)
            pdf.wrapped(forecast_result.advertencia, size=8, indent=0)
            pdf.set_text_color(*_BLACK)
        pdf.ln(4)

        # Per-sucursal forecast mini table
        por_suc = getattr(forecast_result, "por_sucursal", {})
        if por_suc:
            pdf.f("B", 8)
            pdf.cell(0, 5, "Forecast por sucursal:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_fill_color(*_DARK_BLUE)
            pdf.set_text_color(*_WHITE)
            pdf.f("B", 7)
            for h, w in [("Sucursal", 40), ("Ingreso proyectado", 55), ("Tendencia", 45), ("Variacion esperada", 50)]:
                pdf.cell(w, 5, _t(h), fill=True, align="C", new_x=XPos.RIGHT)
            pdf.ln()
            pdf.set_text_color(*_BLACK)
            for si, (suc, data) in enumerate(por_suc.items()):
                pdf.set_fill_color(*(_LIGHT_GRAY if si % 2 == 0 else _WHITE))
                pdf.f("", 7)
                pdf.cell(40, 4.5, _t(suc), fill=True, new_x=XPos.RIGHT)
                pdf.cell(55, 4.5, f"${data.get('revenue_proyectado', 0):,.0f}",
                         fill=True, align="C", new_x=XPos.RIGHT)
                pdf.cell(45, 4.5, _t(data.get("tendencia", "")),
                         fill=True, align="C", new_x=XPos.RIGHT)
                vp = data.get("variacion_pct_esperada", 0)
                pdf.set_text_color(*(_GREEN if vp >= 0 else _RED))
                pdf.cell(50, 4.5, f"{vp:+.1%}", fill=True, align="C",
                         new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.set_text_color(*_BLACK)

    if macro_indices is not None:
        pdf.section_title("Contexto Macroeconomico")
        narr = macro_indices.narrativa_consolidada
        if narr:
            pdf.info_box(narr)
            pdf.ln(2)

        indices_data = [
            ("Presion Inflacionaria",
             macro_indices.indice_presion_inflacionaria.get("valor", 0),
             macro_indices.indice_presion_inflacionaria.get("interpretacion", ""),
             macro_indices.indice_presion_inflacionaria.get("descripcion", ""),
             2.0),
            ("Entorno Economico",
             macro_indices.indice_entorno_economico.get("valor", 0),
             macro_indices.indice_entorno_economico.get("interpretacion", ""),
             macro_indices.indice_entorno_economico.get("descripcion", ""),
             1.0),
            ("Presion Financiera",
             macro_indices.indice_presion_financiera.get("valor", 0),
             macro_indices.indice_presion_financiera.get("interpretacion", ""),
             macro_indices.indice_presion_financiera.get("descripcion", ""),
             1.0),
        ]
        for label, val, interp, desc, max_v in indices_data:
            if interp in ("alta", "adverso"):
                color = _RED
            elif interp in ("moderada", "neutral"):
                color = _YELLOW
            else:
                color = _GREEN
            pdf.h_bar(f"{label}  ({interp})", val, max_v, color, bar_w=75,
                      suffix=f"{val:.3f}")
            if desc:
                pdf.f("I", 7)
                pdf.set_text_color(*_GRAY)
                pdf.set_x(14)
                pdf.cell(0, 4, _t(desc, 120), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.set_text_color(*_BLACK)
            pdf.ln(2)


def _pagina_escenario(pdf: _PDF, sr):
    pdf.add_page()
    pdf.section_title(f"Simulacion Monte Carlo  |  {sr.n_simulaciones:,} iteraciones")

    variaciones = sr.variables_input.get("variaciones_esperadas", {})
    var_parts = [f"{k}: {'+' if v >= 0 else ''}{v:.0%}" for k, v in variaciones.items() if v != 0]
    var_str = "  |  ".join(var_parts) if var_parts else "Escenario neutro (sin cambios en variables)"

    pdf.f("", 8)
    pdf.set_text_color(*_GRAY)
    pdf.cell(0, 5, _t(f"Base: {sr.mes_base}  |  Variables: {var_str}"),
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*_BLACK)
    pdf.ln(3)

    pdf.info_box(sr.narrativa)

    # Percentile table
    pdf.f("B", 9)
    pdf.cell(0, 5, "Distribucion de resultados (percentiles):",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    col_widths = [("Metrica", 50), ("P10", 20), ("P25", 20), ("Mediana", 23),
                  ("P75", 20), ("P90", 20), ("Desv.", 25)]
    pdf.set_fill_color(*_DARK_BLUE)
    pdf.set_text_color(*_WHITE)
    pdf.f("B", 8)
    for h, w in col_widths:
        pdf.cell(w, 6, _t(h), fill=True, align="C", new_x=XPos.RIGHT)
    pdf.ln()
    pdf.set_text_color(*_BLACK)

    metric_defs = [
        ("revenue",               "Ingresos",             False),
        ("margen_bruto",          "Margen Bruto",         True),
        ("ebitda",                "EBITDA",               False),
        ("margen_neto",           "Margen Neto",          True),
        ("nomina_pct",            "Nomina / Ingresos",    True),
        ("gastos_financieros_pct","Gastos Fin. / Ingr.", True),
    ]
    for ri, (key, label, is_pct) in enumerate(metric_defs):
        if key not in sr.distribuciones:
            continue
        d = sr.distribuciones[key]
        fmt = (lambda v: f"{v:.1%}") if is_pct else (lambda v: f"${v/1e6:.3f}M")
        bg = _LIGHT_GRAY if ri % 2 == 0 else _WHITE
        pdf.set_fill_color(*bg)
        pdf.f("", 8)
        vals = [label, fmt(d.p10), fmt(d.p25), fmt(d.p50), fmt(d.p75), fmt(d.p90),
                f"{d.desviacion:.1%}" if is_pct else f"${d.desviacion/1e3:.0f}k"]
        for (_, w), v in zip(col_widths, vals):
            align = "L" if v == label else "C"
            pdf.cell(w, 5, _t(v), fill=True, align=align, new_x=XPos.RIGHT)
        pdf.ln()

    # Probability bars
    pdf.ln(5)
    pdf.f("B", 9)
    pdf.cell(0, 5, "Probabilidades vs benchmark sectorial:",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    prob_items = [
        ("P(Margen bruto >= benchmark)",      "margen_bruto_sobre_benchmark"),
        ("P(Nomina <= benchmark)",            "nomina_bajo_benchmark"),
        ("P(Gastos financieros <= benchmark)","gastos_fin_bajo_benchmark"),
        ("P(Margen neto >= benchmark)",       "margen_neto_sobre_benchmark"),
        ("P(EBITDA > 0)",                     "ebitda_positivo"),
    ]
    probs = sr.probabilidades_benchmark
    for plabel, pkey in prob_items:
        val = probs.get(pkey, 0)
        color = _GREEN if val >= 0.70 else (_YELLOW if val >= 0.40 else _RED)
        pdf.h_bar(plabel, val, 1.0, color, bar_w=75, suffix=f"{val:.0%}")
        pdf.ln(1)


def _pagina_contexto_sectorial(pdf: _PDF, ctx: dict):
    giro = _t(ctx.get("giro_detectado", ""))
    resumen = _t(ctx.get("resumen", ""))
    factores = ctx.get("factores", [])
    if not giro and not resumen:
        return

    pdf.add_page()
    pdf.section_title("Contexto Macroeconómico Sectorial")

    if giro:
        pdf.set_fill_color(*_ACCENT_BLUE)
        pdf.set_text_color(*_DARK_BLUE)
        pdf.f("B", 9)
        pdf.set_x(10)
        pdf.cell(190, 7, _t(f"  Giro detectado: {giro}"), fill=True,
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(*_BLACK)
        pdf.ln(4)

    if resumen:
        pdf.f("B", 9)
        pdf.set_text_color(*_DARK_BLUE)
        pdf.cell(0, 5, "Entorno del sector en México:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(*_BLACK)
        pdf.ln(1)
        pdf.info_box(resumen)

    if factores:
        pdf.ln(2)
        pdf.f("B", 9)
        pdf.set_text_color(*_DARK_BLUE)
        pdf.cell(0, 5, "Factores externos relevantes:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(*_BLACK)
        pdf.ln(2)

        tipo_color = {
            "regulatorio": _MID_BLUE,
            "tendencia":   _GRAY,
            "riesgo":      _RED,
            "oportunidad": _GREEN,
        }
        for fac in factores:
            if pdf.get_y() > 265:
                pdf.add_page()
            tipo = _t(fac.get("tipo", "tendencia")).lower()
            desc = _t(fac.get("descripcion", ""))
            color = tipo_color.get(tipo, _GRAY)
            y0 = pdf.get_y()
            pdf.set_fill_color(*color)
            pdf.rect(10, y0 + 1, 3, 4, "F")
            pdf.set_xy(15, y0)
            pdf.badge(_t(tipo.upper()), color, w=28)
            pdf.set_xy(45, y0)
            pdf.f("", 8)
            pdf.set_text_color(*_BLACK)
            pdf.multi_cell(155, 4.5, desc, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(2)


def _pagina_recomendaciones(pdf: _PDF, copilot_report):
    recos = copilot_report.recomendaciones or []
    if not recos:
        return
    pdf.add_page()
    pdf.section_title("Recomendaciones del Copilot Financiero")

    pri_color = {"alta": _RED, "media": _ORANGE, "baja": _YELLOW}

    for i, rec in enumerate(recos):
        if pdf.get_y() > 245:
            pdf.add_page()

        prioridad = rec.get("prioridad", "baja")
        color = pri_color.get(prioridad, _GRAY)
        y0 = pdf.get_y()

        # Colored accent strip
        pdf.set_fill_color(*color)
        pdf.rect(10, y0, 3, 8, "F")

        # Rec header
        pdf.set_fill_color(*_LIGHT_GRAY)
        pdf.set_xy(13, y0)
        pdf.f("B", 8)
        pdf.set_text_color(*_DARK_BLUE)
        rec_id = _t(rec.get("id", f"REC-{i+1:03d}"))
        pdf.cell(185, 5, f"  {rec_id}  |  {_t(rec.get('area', '')).upper()}  |  Prioridad: {prioridad.upper()}",
                 fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_xy(13, pdf.get_y())
        pdf.f("B", 9)
        pdf.multi_cell(185, 5.5, f"  {_t(rec.get('titulo', ''))}", fill=True,
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(*_BLACK)

        pdf.ln(1)

        # Descripcion
        desc = rec.get("descripcion", "")
        if desc:
            pdf.wrapped(desc, size=8, indent=4)

        # Accion sugerida
        accion = rec.get("accion_sugerida", "")
        if accion:
            pdf.ln(1)
            pdf.set_x(14)
            pdf.f("B", 8)
            pdf.set_text_color(*_DARK_BLUE)
            pdf.cell(0, 4.5, "Accion sugerida:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(*_BLACK)
            pdf.f("", 8)
            pdf.set_x(18)
            pdf.multi_cell(182, 4.5, _t(accion), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        # Impacto
        impacto = rec.get("impacto_estimado", "")
        if impacto:
            pdf.ln(1)
            pdf.set_x(14)
            pdf.f("B", 8)
            pdf.set_text_color(*_GREEN)
            pdf.cell(0, 4.5, "Impacto estimado:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.f("", 8)
            pdf.set_x(18)
            pdf.multi_cell(182, 4.5, _t(impacto), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(*_BLACK)

        # Evidencias
        evidencias = rec.get("evidencia", [])
        if evidencias:
            pdf.ln(1)
            pdf.set_x(14)
            pdf.f("B", 7)
            pdf.set_text_color(*_GRAY)
            pdf.cell(0, 4, "Evidencia:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(*_BLACK)
            for ev in evidencias[:3]:
                pdf.set_x(18)
                pdf.f("", 7)
                ev_txt = _t(f"{ev.get('tipo','')}: {ev.get('fuente','')} = {ev.get('valor','')}")
                pdf.multi_cell(182, 3.5, f"- {ev_txt}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        pdf.ln(2)
        pdf.set_draw_color(*_LIGHT_GRAY)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)

    # Limitaciones
    lims = copilot_report.limitaciones or []
    if lims:
        if pdf.get_y() > 250:
            pdf.add_page()
        pdf.ln(2)
        pdf.divider()
        pdf.f("B", 8)
        pdf.set_text_color(*_GRAY)
        pdf.cell(0, 5, "Limitaciones del analisis:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        for lim in lims:
            pdf.f("", 8)
            pdf.set_x(14)
            pdf.multi_cell(186, 4.5, f"- {_t(lim)}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(*_BLACK)


# ── Public API ────────────────────────────────────────────────────────────────

def generar_reporte(
    kpi_report,
    health_report,
    macro_indices=None,
    shap_narrative=None,
    forecast_result=None,
    scenario_result=None,
    copilot_report=None,
    cliente_id: str = "cliente",
) -> bytes:
    if not _FPDF_OK:
        raise ImportError("fpdf2 no instalado -- pip install fpdf2")

    mes = kpi_report.meses_analizados[-1] if kpi_report.meses_analizados else ""
    hs_mes = health_report.por_mes.get(mes, {})
    score = hs_mes.get("score_total", 0)
    cat = hs_mes.get("categoria", "")

    narrativa = ""
    if copilot_report:
        narrativa = copilot_report.narrativa_ejecutiva or ""
    if not narrativa and macro_indices:
        narrativa = macro_indices.narrativa_consolidada or ""

    pdf = _PDF(orientation="P", unit="mm", format="A4")
    pdf._cliente = cliente_id.upper()
    pdf._periodo = mes
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_margins(10, 16, 10)
    pdf.setup_fonts()

    _portada(pdf, cliente_id, mes, score, cat, narrativa)
    _pagina_kpis(pdf, kpi_report, health_report)
    _pagina_shap(pdf, shap_narrative)
    _pagina_forecast_macro(pdf, forecast_result, macro_indices)
    if copilot_report is not None and copilot_report.contexto_sectorial:
        _pagina_contexto_sectorial(pdf, copilot_report.contexto_sectorial)
    if scenario_result is not None:
        _pagina_escenario(pdf, scenario_result)
    if copilot_report is not None:
        _pagina_recomendaciones(pdf, copilot_report)

    return bytes(pdf.output())
