import re
from typing import List

MONTH_ALIASES = {
    "ENE": "ENERO", "FEB": "FEBRERO", "MAR": "MARZO", "ABR": "ABRIL",
    "MAY": "MAYO", "JUN": "JUNIO", "JUL": "JULIO", "AGO": "AGOSTO",
    "SEP": "SEPTIEMBRE", "SEPT": "SEPTIEMBRE", "OCT": "OCTUBRE",
    "NOV": "NOVIEMBRE", "DIC": "DICIEMBRE",
    "ENERO": "ENERO", "FEBRERO": "FEBRERO", "MARZO": "MARZO", "ABRIL": "ABRIL",
    "MAYO": "MAYO", "JUNIO": "JUNIO", "JULIO": "JULIO", "AGOSTO": "AGOSTO",
    "SEPTIEMBRE": "SEPTIEMBRE", "OCTUBRE": "OCTUBRE",
    "NOVIEMBRE": "NOVIEMBRE", "DICIEMBRE": "DICIEMBRE",
    "JANUARY": "ENERO", "FEBRUARY": "FEBRERO", "MARCH": "MARZO", "APRIL": "ABRIL",
    "MAY_EN": "MAYO", "JUNE": "JUNIO", "JULY": "JULIO", "AUGUST": "AGOSTO",
    "SEPTEMBER": "SEPTIEMBRE", "OCTOBER": "OCTUBRE",
    "NOVEMBER": "NOVIEMBRE", "DECEMBER": "DICIEMBRE",
}


def clean_currency(value: str) -> float:
    """Convert currency string to float. Handles $, commas, and (negative) notation."""
    if value is None:
        return 0.0
    text = str(value).strip()
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    text = re.sub(r"[$,\s]", "", text)
    if not text or text in ("-", ""):
        return 0.0
    try:
        result = float(text)
        return -result if negative else result
    except ValueError:
        return 0.0


def almost_equal(a: float, b: float, tolerance: float = 0.02) -> bool:
    """Return True if a and b differ by less than tolerance fraction of the larger."""
    if a == 0 and b == 0:
        return True
    base = max(abs(a), abs(b))
    if base == 0:
        return True
    return abs(a - b) / base <= tolerance


def detect_months(headers: List[str]) -> List[str]:
    """
    Given a list of header strings, return canonical month strings like 'ENERO 2026'.
    Accepts formats: 'Enero 2026', 'ENE-26', 'enero_2026', 'ENERO2026', etc.
    """
    results = []
    for h in headers:
        canonical = _parse_month_header(str(h).strip().upper())
        if canonical:
            results.append(canonical)
    return results


def _parse_month_header(text: str) -> str | None:
    # Normalize separators
    text = re.sub(r"[-_/]", " ", text).strip()

    # Try "MONTH YEAR" or "MONTH-YEAR"
    m = re.match(r"([A-Z]+)\s+(\d{2,4})$", text)
    if m:
        month_raw, year = m.group(1), m.group(2)
        month = MONTH_ALIASES.get(month_raw)
        if month:
            year = _normalize_year(year)
            return f"{month} {year}"

    # Try "MONTHYEAR" with no separator e.g. "ENERO2026"
    m = re.match(r"([A-Z]+)(\d{4})$", text)
    if m:
        month = MONTH_ALIASES.get(m.group(1))
        if month:
            return f"{month} {m.group(2)}"

    return None


def _normalize_year(year: str) -> str:
    if len(year) == 2:
        prefix = "20" if int(year) < 50 else "19"
        return prefix + year
    return year
