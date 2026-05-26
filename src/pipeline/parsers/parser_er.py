from dataclasses import dataclass, field
from typing import Dict, List

import pandas as pd

from . import ParseError
from .parser_utils import clean_currency, normalize_month, month_sort_key

# Maps CSV row labels (uppercased) to ERData field names
_KPI_MAP = {
    "NÓMINA": "nomina",
    "NOMINA": "nomina",
    "GASTOS COMERCIALES": "gastos_comerciales",
    "GASTOS OPERATIVOS": "gastos_operativos",
    "GASTOS ADMINISTRATIVOS": "gastos_administrativos",
    "VIÁTICOS": "viaticos",
    "VIATICOS": "viaticos",
    "TOTAL GASTOS DE OPERACIÓN": "total_gastos_operacion",
    "TOTAL GASTOS DE OPERACION": "total_gastos_operacion",
    "GASTOS FINANCIEROS": "gastos_financieros",
    "COSTO INTEGRAL DE FINANCIAMIENTO": "costo_integral_financiamiento",
    "IMPUESTOS": "impuestos",
}

_EMPTY_KPI: Dict[str, float] = {
    "nomina": 0.0,
    "gastos_comerciales": 0.0,
    "gastos_operativos": 0.0,
    "gastos_administrativos": 0.0,
    "viaticos": 0.0,
    "total_gastos_operacion": 0.0,
    "gastos_financieros": 0.0,
    "costo_integral_financiamiento": 0.0,
    "impuestos": 0.0,
}


@dataclass
class ERData:
    meses: List[str]
    gastos_operativos: Dict[str, Dict[str, float]]


def parse_er(filepath: str) -> ERData:
    try:
        df = pd.read_csv(filepath, header=None, encoding="utf-8-sig", dtype=str)
    except FileNotFoundError:
        raise ParseError(f"File not found: {filepath}")
    except Exception as e:
        raise ParseError(f"Error reading ER file: {e}")

    if len(df) < 2:
        raise ParseError("ER file has fewer than 2 rows")

    # Row 1 (index 1) contains month names in columns 1+
    header_row = df.iloc[1]
    month_cols: Dict[str, int] = {}
    for col_idx in range(1, len(header_row)):
        val = str(header_row.iloc[col_idx]).strip().upper()
        if val and val not in ("NAN", "ACUMULADO", ""):
            month_cols[val] = col_idx

    if not month_cols:
        raise ParseError("No month columns found in ER header row")

    meses = sorted(month_cols.keys(), key=month_sort_key)
    gastos_operativos: Dict[str, Dict[str, float]] = {
        mes: dict(_EMPTY_KPI) for mes in meses
    }

    kpis_found = 0
    for i in range(2, len(df)):
        label = str(df.iloc[i, 0]).strip().upper()
        field_name = _KPI_MAP.get(label)
        if field_name is None:
            continue
        kpis_found += 1
        for mes, col_idx in month_cols.items():
            raw = df.iloc[i, col_idx] if col_idx < len(df.columns) else None
            gastos_operativos[mes][field_name] = clean_currency(raw)

    if kpis_found == 0:
        raise ParseError("No KPI rows found in ER file")

    return ERData(meses=meses, gastos_operativos=gastos_operativos)
