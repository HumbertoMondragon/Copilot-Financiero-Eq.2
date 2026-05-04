"""
Excel P&L parser.
Handles merged cells, empty separator rows, and infers row hierarchy.

Real-world row types (in order):
  - Section header:  "VENTAS" / "Egresos"  — label only, no values
  - Group header:    "A", "$3,164,778"     — single letter A-E, value = group total
  - Subline:         "Alimentos", value    — recognised subline name
  - KPI summary:     "UTILIDAD BRUTA", value / "Margen", "64.16%" — bottom of sheet

Duplicate-label KPIs ("% venta" × 2, "Margen" × 3) are resolved by occurrence
order tracked with a per-sheet counter.

Percentage cell values (e.g. "30.26%") are divided by 100 and rounded to 4 dp.
Monetary values are rounded to 2 dp.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import openpyxl

from . import ParseError
from ..profiles import GROUPS, empty_month, get_profile
from ..utils import clean_currency, detect_months

VENTAS_SYNONYMS: dict[str, str] = {
    "ALIMENTOS": "Alimentos",
    "BEBIDAS": "Bebidas",
    "CAFE": "Cafe_Inf", "CAFÉ": "Cafe_Inf", "CAFE_INF": "Cafe_Inf", "CAFÉ INF": "Cafe_Inf",
    "DESTILADOS": "Destilados",
    "VINOS": "Vinos",
}

# Labels that are unambiguous — looked up by exact uppercase match.
KPI_SYNONYMS: dict[str, str] = {
    "VENTAS TOTALES": "total_ventas", "TOTAL VENTAS": "total_ventas",
    "TOTAL DE VENTAS": "total_ventas",
    "COSTO DE VENTAS": "total_costo", "TOTAL COSTO": "total_costo",
    "TOTAL COSTO DE LO VENDIDO": "total_costo",
    "COSTO DE LO VENDIDO": "total_costo",
    "UTILIDAD BRUTA": "utilidad_bruta",
    "MARGEN BRUTO": "margen_bruto",
    "NÓMINA": "nomina", "NOMINA": "nomina",
    "GASTOS COMERCIALES": "gastos_comerciales",
    "GASTOS OPERATIVOS": "gastos_operativos",
    "GASTOS DE OPERACIÓN": "gastos_operativos", "GASTOS DE OPERACION": "gastos_operativos",
    "GASTOS ADMINISTRATIVOS": "gastos_administrativos",
    "VIÁTICOS": "viaticos", "VIATICOS": "viaticos",
    "TOTAL GASTOS OPERACIÓN": "total_gastos_operacion",
    "TOTAL GASTOS DE OPERACIÓN": "total_gastos_operacion",
    "TOTAL GASTOS DE OPERACION": "total_gastos_operacion",
    "TOTAL GASTOS OPERACION": "total_gastos_operacion",
    "EBITDA": "ebitda",
    "MARGEN EBITDA": "margen_ebitda",
    "GASTOS FINANCIEROS": "gastos_financieros",
    "COSTO INTEGRAL DE FINANCIAMIENTO": "costo_integral_financiamiento",
    "IMPUESTOS": "impuestos",
    "UTILIDAD NETA": "utilidad_neta",
    "UTILIDAD (Ó PÉRDIDA)": "utilidad_neta",
    "UTILIDAD (O PERDIDA)": "utilidad_neta",
    "UTILIDAD (Ó PERDIDA)": "utilidad_neta",
    "MARGEN NETO": "margen_neto",
}

# Labels that appear multiple times; resolved by (uppercase_label, 0-based occurrence).
POSITIONAL_KPI_SYNONYMS: dict[tuple[str, int], str] = {
    ("% VENTA", 0): "margen_costo",
    ("% VENTA", 1): "margen_operacion",
    ("MARGEN", 0): "margen_bruto",
    ("MARGEN", 1): "margen_ebitda",
    ("MARGEN", 2): "margen_neto",
}

_RE_SECTION_VENTAS = re.compile(r"^VENTAS$|^INGRESOS$")
_RE_SECTION_EGRESOS = re.compile(r"^EGRESOS$|^COSTOS?$")


def parse(filepath: str | Path, cliente_id: str = "default") -> dict:
    profile = get_profile(cliente_id)
    synonyms = profile.get("synonyms", {})
    scale = profile.get("scale", 1.0)

    try:
        wb = openpyxl.load_workbook(filepath, data_only=True)
    except Exception as exc:
        raise ParseError(f"Cannot open Excel file: {exc}") from exc

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        result = _parse_sheet(ws, cliente_id, synonyms, scale)
        if result and result.get("meses"):
            return result

    raise ParseError("No recognizable P&L data found in any sheet.")


def _parse_sheet(ws, cliente_id: str, synonyms: dict, scale: float) -> dict | None:
    # Flatten merged regions: every cell gets the top-left value
    merge_map: dict[tuple, Any] = {}
    for merged in list(ws.merged_cells.ranges):
        top_left = ws.cell(merged.min_row, merged.min_col).value
        for r in range(merged.min_row, merged.max_row + 1):
            for c in range(merged.min_col, merged.max_col + 1):
                merge_map[(r, c)] = top_left

    max_row = ws.max_row

    def cell_val(r, c):
        return merge_map.get((r, c), ws.cell(r, c).value)

    # Locate header row (first row containing recognisable month names)
    header_row = None
    month_cols: dict[str, int] = {}

    for r in range(1, min(20, max_row + 1)):
        found = {}
        for c in range(1, ws.max_column + 1):
            v = cell_val(r, c)
            if v is None:
                continue
            months = detect_months([str(v)])
            if months:
                found[months[0]] = c
        if found:
            header_row = r
            month_cols = found
            break

    if not header_row or not month_cols:
        return None

    periodo = _infer_periodo(month_cols)
    meses_data: dict[str, dict] = {m: empty_month() for m in month_cols}

    current_section: str | None = None
    current_group: str | None = None
    # Tracks how many times each KPI label has been seen (for positional mapping)
    occurrence_counter: dict[str, int] = {}

    for r in range(header_row + 1, max_row + 1):
        label_raw = cell_val(r, 1) or ""
        label = str(label_raw).strip().upper()

        num_vals = {mes: cell_val(r, col) for mes, col in month_cols.items()}
        has_data = any(_cell_has_data(v) for v in num_vals.values())

        if not label and not has_data:
            continue  # empty separator

        # ── Section change (label-only rows) ─────────────────────────────────
        if not has_data:
            if _RE_SECTION_VENTAS.match(label):
                current_section = "ventas"
                current_group = None
                continue
            if _RE_SECTION_EGRESOS.match(label):
                current_section = "egresos"
                current_group = None
                continue

        if not current_section:
            continue

        # ── Group header (single letter A–E, value = group total) ────────────
        group_letter = _match_group_label(label)
        if group_letter:
            current_group = group_letter
            for mes, col in month_cols.items():
                raw = cell_val(r, col)
                if _cell_has_data(raw):
                    meses_data[mes][current_section][current_group]["total"] = (
                        _parse_cell(raw, scale)
                    )
            continue

        # ── Data row: subline or KPI summary ────────────────────────────────
        canonical = _resolve_label(label, synonyms)
        subline_key = (
            VENTAS_SYNONYMS.get(canonical.upper())
            if current_group and current_section in ("ventas", "egresos")
            else None
        )
        # Compute kpi_key once per row — advances the occurrence counter once
        kpi_key = _get_kpi_key(canonical.upper(), occurrence_counter)

        for mes, col in month_cols.items():
            raw = cell_val(r, col)
            if not _cell_has_data(raw):
                continue
            value = _parse_cell(raw, scale)

            if subline_key:
                meses_data[mes][current_section][current_group][subline_key] = value
            if kpi_key:
                meses_data[mes]["kpis"][kpi_key] = value

    for mes_data in meses_data.values():
        _derive_missing_totals(mes_data)

    return {
        "periodo": periodo,
        "fuente": "excel",
        "cliente_id": cliente_id,
        "meses": meses_data,
    }


def _derive_missing_totals(mes_data: dict) -> None:
    """
    Fill in aggregated KPIs only when they were NOT read from the file.
    total_ventas has no explicit row in the real format, so it is always derived.
    total_costo and total_gastos_operacion are read from the file; derived only as fallback.
    """
    k = mes_data["kpis"]
    k["total_ventas"] = round(sum(g["total"] for g in mes_data["ventas"].values()), 2)
    if k["total_costo"] == 0.0:
        k["total_costo"] = round(sum(g["total"] for g in mes_data["egresos"].values()), 2)
    if k["total_gastos_operacion"] == 0.0:
        k["total_gastos_operacion"] = round(
            k["nomina"] + k["gastos_comerciales"] + k["gastos_operativos"]
            + k["gastos_administrativos"] + k["viaticos"],
            2,
        )


def _get_kpi_key(label: str, counter: dict[str, int]) -> str | None:
    """
    Return the KPI field for this label, using occurrence order for duplicate labels.
    Increments the counter for this label regardless of whether a match is found,
    so the next call with the same label gets the next occurrence number.
    """
    n = counter.get(label, 0)
    counter[label] = n + 1
    positional = POSITIONAL_KPI_SYNONYMS.get((label, n))
    return positional if positional is not None else KPI_SYNONYMS.get(label)


def _parse_cell(raw, scale: float) -> float:
    """
    Convert a raw cell value to a normalised float.
    - Percentage strings ("30.26%") → divided by 100, rounded to 4 dp
    - Numeric percentage cells (float already in fraction form) are unchanged
    - Monetary values → multiplied by scale, rounded to 2 dp
    """
    if raw is None:
        return 0.0
    if isinstance(raw, bool):
        return 0.0
    if isinstance(raw, (int, float)):
        return round(float(raw) * scale, 2)
    text = str(raw).strip()
    if "%" in text:
        numeric = clean_currency(text.replace("%", ""))
        return round(numeric / 100, 4)
    return round(clean_currency(text) * scale, 2)


def _cell_has_data(v) -> bool:
    """True if the cell contains something parseable (number or percentage string)."""
    if v is None:
        return False
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    return bool(re.search(r"\d", str(v)))


def _match_group_label(label: str) -> str | None:
    clean = label.strip()
    if clean in ("A", "B", "C", "D", "E"):
        return clean
    m = re.fullmatch(r"(?:GRUPO\s+|GROUP\s+)?([A-E])", clean)
    return m.group(1) if m else None


def _resolve_label(label: str, synonyms: dict) -> str:
    return synonyms.get(label, synonyms.get(label.upper(), label))


def _infer_periodo(month_cols: dict) -> str:
    for m in month_cols:
        parts = m.split()
        if len(parts) == 2:
            return parts[1]
    return "DESCONOCIDO"
