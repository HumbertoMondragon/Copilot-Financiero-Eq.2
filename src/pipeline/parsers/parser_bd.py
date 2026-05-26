from dataclasses import dataclass, field
from typing import List, Dict

import pandas as pd

from . import ParseError
from .parser_utils import clean_currency, clean_int, normalize_month, month_sort_key

REQUIRED_COLUMNS = {
    "MES",
    "LÍNEA DE NEGOCIO",
    "SUBCATEGORÍA 1",
    "SUBCATEGORÍA 2",
    "CANTIDAD",
    "SUBTOTAL",
    "TOTAL",
    "COSTO TOTAL SIN IVA",
    "COSTO TOTAL DEL SERVICIO",
    "UTILIDAD BRUTA",
    "MARGEN BRUTO",
}


@dataclass
class BDData:
    meses: List[str]
    sucursales: List[str]
    categorias: List[str]
    registros: List[Dict]


def _get_str(row, col: str) -> str:
    val = row.get(col, "")
    if val is None:
        return ""
    s = str(val).strip()
    return "" if s.lower() == "nan" else s


def parse_bd(filepath: str) -> BDData:
    try:
        df = pd.read_csv(filepath, encoding="utf-8-sig", dtype=str)
    except FileNotFoundError:
        raise ParseError(f"File not found: {filepath}")
    except Exception as e:
        raise ParseError(f"Error reading BD file: {e}")

    df.columns = [c.strip() for c in df.columns]

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ParseError(f"Missing required columns: {missing}")

    registros = []
    for _, row in df.iterrows():
        mes = normalize_month(_get_str(row, "MES"))
        if not mes:
            continue

        cantidad = clean_int(_get_str(row, "CANTIDAD"))
        costo_sin_iva = clean_currency(_get_str(row, "COSTO TOTAL SIN IVA"))

        if cantidad == 0 or costo_sin_iva == 0.0:
            continue

        subtotal = clean_currency(_get_str(row, "SUBTOTAL"))
        utilidad_bruta = clean_currency(_get_str(row, "UTILIDAD BRUTA"))

        margen_raw = clean_currency(_get_str(row, "MARGEN BRUTO"))
        margen_bruto = margen_raw / 100.0 if margen_raw > 1.0 else margen_raw

        multiplicador = round(utilidad_bruta / costo_sin_iva, 6) if costo_sin_iva else 0.0

        registros.append(
            {
                "mes": mes,
                "sucursal": _get_str(row, "LÍNEA DE NEGOCIO").upper(),
                "categoria": _get_str(row, "SUBCATEGORÍA 1"),
                "sku": _get_str(row, "SUBCATEGORÍA 2"),
                "cantidad": cantidad,
                "subtotal": subtotal,
                "total": clean_currency(_get_str(row, "TOTAL")),
                "costo_sin_iva": costo_sin_iva,
                "costo_con_iva": clean_currency(_get_str(row, "COSTO TOTAL DEL SERVICIO")),
                "utilidad_bruta": utilidad_bruta,
                "margen_bruto": margen_bruto,
                "multiplicador_eficiencia": multiplicador,
                "tag_menu_1": _get_str(row, "COL ESPECIAL 1") if "COL ESPECIAL 1" in df.columns else "",
                "tag_menu_2": _get_str(row, "COL ESPECIAL 2") if "COL ESPECIAL 2" in df.columns else "",
            }
        )

    if not registros:
        raise ParseError("No valid rows parsed from BD file (all rows had zero cost or quantity)")

    meses = sorted(set(r["mes"] for r in registros), key=month_sort_key)
    sucursales = sorted(set(r["sucursal"] for r in registros))
    categorias = sorted(set(r["categoria"] for r in registros))

    return BDData(meses=meses, sucursales=sucursales, categorias=categorias, registros=registros)
