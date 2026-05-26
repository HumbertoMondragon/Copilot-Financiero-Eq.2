import math
import re

MONTH_ORDER = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4,
    "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
    "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}


def clean_currency(s) -> float:
    if s is None:
        return 0.0
    if isinstance(s, (int, float)):
        v = float(s)
        return 0.0 if math.isnan(v) else v
    s = str(s).strip()
    if not s or s.lower() == "nan":
        return 0.0
    negative = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[()\$,]", "", s).strip()
    try:
        val = float(s)
    except ValueError:
        return 0.0
    return -val if negative else val


def clean_pct(s) -> float:
    if s is None:
        return 0.0
    if isinstance(s, float):
        return 0.0 if math.isnan(s) else s
    s = str(s).strip().replace("%", "").strip()
    if not s or s.lower() == "nan":
        return 0.0
    try:
        return float(s) / 100.0
    except ValueError:
        return 0.0


def clean_int(s) -> int:
    if s is None:
        return 0
    if isinstance(s, float):
        return 0 if math.isnan(s) else int(s)
    if isinstance(s, int):
        return s
    s = str(s).strip().replace(",", "").strip()
    if not s or s.lower() == "nan":
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def normalize_month(s) -> str:
    if s is None:
        return ""
    return str(s).strip().upper()


def month_sort_key(m: str):
    parts = m.split()
    if len(parts) >= 2:
        return (parts[1], MONTH_ORDER.get(parts[0], 0))
    return (m, 0)
