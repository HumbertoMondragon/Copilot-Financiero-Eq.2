from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np

from .kpis import KPIReport
from .parsers.parser_utils import MONTH_ORDER

_MONTH_NAMES = {v: k for k, v in MONTH_ORDER.items()}


@dataclass
class ForecastResult:
    mes_proyectado: str
    revenue_proyectado: float
    tendencia: str
    variacion_pct_esperada: Optional[float]
    confianza: str
    advertencia: str
    metodo: str
    puntos_usados: int
    por_sucursal: Dict[str, Any]


def _next_month(last: str) -> str:
    parts = last.split()
    if len(parts) < 2:
        return "MES SIGUIENTE"
    num = MONTH_ORDER.get(parts[0], 1)
    year = int(parts[1])
    if num == 12:
        return f"ENERO {year + 1}"
    return f"{_MONTH_NAMES[num + 1]} {year}"


def _linear_proj(values: List[float]) -> Dict[str, Any]:
    n = len(values)
    if n < 2:
        return {
            "revenue_proyectado": float(values[0]) if values else 0.0,
            "tendencia": "insuficiente_datos",
            "variacion_pct_esperada": None,
        }
    x = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(x, values, 1)
    projected = float(slope * n + intercept)
    last = float(values[-1])
    if last == 0:
        variacion_pct: Optional[float] = None
        tendencia = "insuficiente_datos"
    else:
        variacion_pct = (projected - last) / abs(last)
        if variacion_pct > 0.05:
            tendencia = "creciente"
        elif variacion_pct < -0.05:
            tendencia = "decreciente"
        else:
            tendencia = "estable"
    return {
        "revenue_proyectado": projected,
        "tendencia": tendencia,
        "variacion_pct_esperada": variacion_pct,
    }


def forecast_revenue(kpi_report: KPIReport) -> ForecastResult:
    meses = kpi_report.meses_analizados
    n = len(meses)
    revenues: List[float] = kpi_report.tendencias["revenue"]["valores"]

    confianza = "alta" if n > 8 else "media" if n >= 4 else "baja"
    advertencia = (
        f"Proyección basada en {n} mes{'es' if n != 1 else ''} de datos. "
        "Solo indica dirección, no precisión."
    )

    if n < 2:
        return ForecastResult(
            mes_proyectado=_next_month(meses[-1]) if meses else "MES SIGUIENTE",
            revenue_proyectado=float(revenues[0]) if revenues else 0.0,
            tendencia="insuficiente_datos",
            variacion_pct_esperada=None,
            confianza=confianza,
            advertencia=advertencia,
            metodo="regresion_lineal",
            puntos_usados=n,
            por_sucursal={},
        )

    proj = _linear_proj(revenues)

    por_sucursal: Dict[str, Any] = {}
    for suc, sdata in kpi_report.tendencias.get("por_sucursal", {}).items():
        suc_revs: List[float] = sdata["revenue"]["valores"]
        if len(suc_revs) >= 2:
            sp = _linear_proj(suc_revs)
            por_sucursal[suc] = {
                "revenue_proyectado": sp["revenue_proyectado"],
                "tendencia": sp["tendencia"],
                "variacion_pct_esperada": sp["variacion_pct_esperada"],
            }

    return ForecastResult(
        mes_proyectado=_next_month(meses[-1]),
        revenue_proyectado=proj["revenue_proyectado"],
        tendencia=proj["tendencia"],
        variacion_pct_esperada=proj["variacion_pct_esperada"],
        confianza=confianza,
        advertencia=advertencia,
        metodo="regresion_lineal",
        puntos_usados=n,
        por_sucursal=por_sucursal,
    )
