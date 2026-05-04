"""
Text-based PDF parser using pdfplumber.
Attempts table extraction by spatial coordinates first;
falls back to line-by-line text extraction if no table structure detected.
"""
from __future__ import annotations

import re
from pathlib import Path

import pdfplumber

from . import ParseError
from ..profiles import GROUPS, empty_month, get_profile
from ..utils import clean_currency, detect_months


KPI_PATTERNS = [
    (r"ventas?\s+totales?|total\s+ventas?", "total_ventas"),
    (r"costo\s+de\s+ventas?|total\s+costo", "total_costo"),
    (r"utilidad\s+bruta", "utilidad_bruta"),
    (r"margen\s+bruto", "margen_bruto"),
    (r"n[oó]mina", "nomina"),
    (r"gastos?\s+comerciales?", "gastos_comerciales"),
    (r"gastos?\s+operativos?|gastos?\s+de\s+operaci[oó]n", "gastos_operativos"),
    (r"gastos?\s+administrativos?", "gastos_administrativos"),
    (r"vi[aá]ticos?", "viaticos"),
    (r"total\s+gastos?\s+(?:de\s+)?operaci[oó]n", "total_gastos_operacion"),
    (r"ebitda", "ebitda"),
    (r"margen\s+ebitda", "margen_ebitda"),
    (r"gastos?\s+financieros?", "gastos_financieros"),
    (r"impuestos?", "impuestos"),
    (r"utilidad\s+neta", "utilidad_neta"),
    (r"margen\s+neto", "margen_neto"),
]

VENTAS_PATTERNS = [
    (r"alimentos?", "Alimentos"),
    (r"bebidas?", "Bebidas"),
    (r"caf[eé](?:_inf)?", "Cafe_Inf"),
    (r"destilados?", "Destilados"),
    (r"vinos?", "Vinos"),
]


def parse(filepath: str | Path, cliente_id: str = "default") -> dict:
    profile = get_profile(cliente_id)
    scale = profile.get("scale", 1.0)

    try:
        with pdfplumber.open(str(filepath)) as pdf:
            # Try table extraction first
            result = _try_table_extraction(pdf, cliente_id, scale)
            if result and result.get("meses"):
                return result
            # Fall back to line-by-line
            full_text = "\n".join(
                page.extract_text() or "" for page in pdf.pages
            )
    except Exception as exc:
        raise ParseError(f"Cannot open PDF: {exc}") from exc

    if not full_text.strip():
        raise ParseError("PDF contains no extractable text (possibly scanned).")

    return _parse_text(full_text, cliente_id, scale)


def _try_table_extraction(pdf, cliente_id: str, scale: float) -> dict | None:
    all_tables = []
    for page in pdf.pages:
        tables = page.extract_tables()
        if tables:
            all_tables.extend(tables)

    if not all_tables:
        return None

    # Find the table with month-like headers
    for table in all_tables:
        if not table or len(table) < 2:
            continue
        header_row = table[0]
        months = detect_months([str(c) for c in header_row if c])
        if not months:
            continue

        month_indices = {}
        for i, cell in enumerate(header_row):
            if cell is None:
                continue
            m = detect_months([str(cell)])
            if m:
                month_indices[m[0]] = i

        if not month_indices:
            continue

        periodo = _infer_periodo(month_indices)
        meses_data = {m: empty_month() for m in month_indices}

        for row in table[1:]:
            if not row or not row[0]:
                continue
            label = str(row[0]).strip()
            for mes, col_idx in month_indices.items():
                if col_idx >= len(row):
                    continue
                value = clean_currency(str(row[col_idx])) * scale
                _assign_kpi(label, value, meses_data[mes]["kpis"])

        return {
            "periodo": periodo,
            "fuente": "pdf_texto",
            "cliente_id": cliente_id,
            "meses": meses_data,
        }

    return None


def _parse_text(text: str, cliente_id: str, scale: float) -> dict:
    lines = text.splitlines()

    # Detect months from header lines
    month_order: list[str] = []
    for line in lines[:30]:
        found = detect_months(line.split())
        month_order.extend(m for m in found if m not in month_order)

    if not month_order:
        # Try entire document for months
        for line in lines:
            found = detect_months(line.split())
            month_order.extend(m for m in found if m not in month_order)

    if not month_order:
        raise ParseError("No month headers detected in PDF text.")

    periodo = _infer_periodo({m: i for i, m in enumerate(month_order)})
    meses_data = {m: empty_month() for m in month_order}

    current_group_idx = {"ventas": 0, "egresos": 0}
    current_section = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()

        if re.search(r"ventas|ingresos", lower) and not re.search(r"total|costo", lower):
            current_section = "ventas"
        elif re.search(r"egresos|costos", lower) and current_section != "egresos":
            current_section = "egresos"

        # Extract all numbers from this line
        numbers = [clean_currency(n) * scale
                   for n in re.findall(r"[\$]?[\d,]+(?:\.\d+)?|\([\d,]+(?:\.\d+)?\)", stripped)]

        if not numbers:
            continue

        # Match KPIs
        for pattern, kpi_key in KPI_PATTERNS:
            if re.search(pattern, lower):
                for mes, val in zip(month_order, numbers):
                    meses_data[mes]["kpis"][kpi_key] = val
                break

        # Match ventas sublines
        if current_section == "ventas":
            for pattern, subline_key in VENTAS_PATTERNS:
                if re.search(pattern, lower):
                    grp_idx = current_group_idx["ventas"]
                    if grp_idx < len(GROUPS):
                        group = GROUPS[grp_idx]
                        for mes, val in zip(month_order, numbers):
                            meses_data[mes]["ventas"][group][subline_key] = val
                    break

    return {
        "periodo": periodo,
        "fuente": "pdf_texto",
        "cliente_id": cliente_id,
        "meses": meses_data,
    }


def _infer_periodo(month_cols: dict) -> str:
    for m in month_cols:
        parts = m.split()
        if len(parts) == 2:
            return parts[1]
    return "DESCONOCIDO"


def _assign_kpi(label: str, value: float, kpis: dict) -> None:
    lower = label.lower()
    for pattern, key in KPI_PATTERNS:
        if re.search(pattern, lower):
            kpis[key] = value
            return
