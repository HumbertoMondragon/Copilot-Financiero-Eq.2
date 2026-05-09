"""
Financial indicators calculator.
Pure Python — no LLM calls, no external APIs.
Operates on the normalized schema produced by the parsing pipeline.
"""
from __future__ import annotations

# ── Alert thresholds ──────────────────────────────────────────────────────────
UMBRAL_MARGEN_BRUTO = 0.40
UMBRAL_EBITDA = 0.10
UMBRAL_MARGEN_NETO = 0.05
UMBRAL_MARGEN_SUCURSAL = 0.40

_GRUPOS = ["A", "B", "C", "D", "E"]
_SUBLINEAS = ["Alimentos", "Bebidas", "Cafe_Inf", "Destilados", "Vinos"]

_MONTH_ORDER: dict[str, int] = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4,
    "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
    "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}


# ── Public API ────────────────────────────────────────────────────────────────

def calcular_indicadores_mes(mes_data: dict, mes_nombre: str) -> dict:
    """
    Compute financial indicators for a single month.
    Safe against zero total_ventas — never raises ZeroDivisionError.
    """
    kpis = mes_data.get("kpis", {})
    ventas = mes_data.get("ventas", {})
    egresos = mes_data.get("egresos", {})

    tv = kpis.get("total_ventas", 0.0)

    # ── Rentabilidad ──────────────────────────────────────────────────────────
    mb = kpis.get("margen_bruto", 0.0)
    me = kpis.get("margen_ebitda", 0.0)
    mn = kpis.get("margen_neto", 0.0)

    rentabilidad = {
        "margen_bruto": mb,
        "margen_ebitda": me,
        "margen_neto": mn,
        "alerta_margen_bruto": mb < UMBRAL_MARGEN_BRUTO,
        "alerta_ebitda": me < UMBRAL_EBITDA,
        "alerta_neto": mn < UMBRAL_MARGEN_NETO,
    }

    # ── Estructura de costos ──────────────────────────────────────────────────
    egreso_por_categoria: dict[str, float] = {s: 0.0 for s in _SUBLINEAS}
    for grp in _GRUPOS:
        for sub in _SUBLINEAS:
            egreso_por_categoria[sub] += egresos.get(grp, {}).get(sub, 0.0)

    nonzero = {k: v for k, v in egreso_por_categoria.items() if v > 0}
    categoria_mayor = max(nonzero, key=nonzero.__getitem__) if nonzero else None
    categoria_menor = min(nonzero, key=nonzero.__getitem__) if nonzero else None

    estructura_costos = {
        "costo_sobre_ventas": _div(kpis.get("total_costo", 0.0), tv),
        "nomina_sobre_ventas": _div(kpis.get("nomina", 0.0), tv),
        "gastos_op_sobre_ventas": _div(kpis.get("total_gastos_operacion", 0.0), tv),
        "categoria_mayor_egreso": categoria_mayor,
        "categoria_menor_egreso": categoria_menor,
    }

    # ── Sucursales ────────────────────────────────────────────────────────────
    sucursales: dict[str, dict] = {}
    for grp in _GRUPOS:
        v = ventas.get(grp, {}).get("total", 0.0)
        e = egresos.get(grp, {}).get("total", 0.0)
        ub = round(v - e, 2)
        margen = _div(ub, v)
        sucursales[grp] = {
            "venta": round(v, 2),
            "egreso": round(e, 2),
            "utilidad_bruta": ub,
            "margen": margen,
            "participacion_ventas": _div(v, tv),
            "alerta_margen": margen < UMBRAL_MARGEN_SUCURSAL,
        }

    ranking = sorted(_GRUPOS, key=lambda g: sucursales[g]["margen"], reverse=True)

    # ── Alertas ───────────────────────────────────────────────────────────────
    alertas: list[dict] = []

    if rentabilidad["alerta_margen_bruto"]:
        alertas.append(_alerta(
            "margen_bruto", mb, UMBRAL_MARGEN_BRUTO,
            f"Margen bruto de {mb*100:.1f}%, por debajo del umbral de {UMBRAL_MARGEN_BRUTO*100:.0f}%",
        ))
    if rentabilidad["alerta_ebitda"]:
        alertas.append(_alerta(
            "ebitda", me, UMBRAL_EBITDA,
            f"Margen EBITDA de {me*100:.1f}%, por debajo del umbral de {UMBRAL_EBITDA*100:.0f}%",
        ))
    if rentabilidad["alerta_neto"]:
        alertas.append(_alerta(
            "margen_neto", mn, UMBRAL_MARGEN_NETO,
            f"Margen neto de {mn*100:.1f}%, por debajo del umbral de {UMBRAL_MARGEN_NETO*100:.0f}%",
        ))
    for grp in _GRUPOS:
        s = sucursales[grp]
        if s["alerta_margen"]:
            alertas.append(_alerta(
                "margen_sucursal", s["margen"], UMBRAL_MARGEN_SUCURSAL,
                f"Sucursal {grp} tiene margen de {s['margen']*100:.1f}%, "
                f"por debajo del umbral de {UMBRAL_MARGEN_SUCURSAL*100:.0f}%",
            ))

    return {
        "mes": mes_nombre,
        "rentabilidad": rentabilidad,
        "estructura_costos": estructura_costos,
        "sucursales": sucursales,
        "ranking_sucursales": ranking,
        "alertas": alertas,
    }


def calcular_tendencias(meses_data: dict) -> dict:
    """
    Month-over-month trends across all months with data (total_ventas > 0).
    Returns "insuficiente_datos" for any series with fewer than 2 data points.
    """
    ordered = sorted(
        [(k, v) for k, v in meses_data.items()
         if v.get("kpis", {}).get("total_ventas", 0.0) > 0],
        key=lambda x: _month_sort_key(x[0]),
    )
    nombres = [k for k, _ in ordered]

    ventas_vals = [m["kpis"].get("total_ventas", 0.0) for _, m in ordered]
    ebitda_vals = [m["kpis"].get("ebitda", 0.0) for _, m in ordered]
    mn_vals = [m["kpis"].get("margen_neto", 0.0) for _, m in ordered]

    sucursales_tend: dict[str, dict] = {}
    for grp in _GRUPOS:
        v_vals = [m.get("ventas", {}).get(grp, {}).get("total", 0.0) for _, m in ordered]
        margen_vals = [_margen_grupo(m, grp) for _, m in ordered]
        s = _serie(margen_vals)
        sucursales_tend[grp] = {
            "ventas": v_vals,
            "margen": margen_vals,
            "tendencia_margen": s["tendencia"],
        }

    return {
        "meses_con_datos": nombres,
        "ventas": _serie(ventas_vals),
        "ebitda": _serie(ebitda_vals),
        "margen_neto": _serie(mn_vals),
        "sucursales": sucursales_tend,
    }


def analizar(normalized_json: dict) -> dict:
    """
    Main entry point. Returns per-month indicators, trends, and executive summary.
    Months with total_ventas = 0 are excluded from all calculations.
    """
    cliente_id = normalized_json.get("cliente_id", "default")
    periodo = normalized_json.get("periodo", "")
    meses_data = normalized_json.get("meses", {})

    por_mes: dict[str, dict] = {}
    for mes_nombre, mes_data in meses_data.items():
        if mes_data.get("kpis", {}).get("total_ventas", 0.0) > 0:
            por_mes[mes_nombre] = calcular_indicadores_mes(mes_data, mes_nombre)

    tendencias = calcular_tendencias(meses_data)

    meses_activos = list(por_mes)
    if meses_activos:
        mejor_ebitda = max(meses_activos, key=lambda m: por_mes[m]["rentabilidad"]["margen_ebitda"])
        peor_ebitda = min(meses_activos, key=lambda m: por_mes[m]["rentabilidad"]["margen_ebitda"])
        avg_margen = {
            grp: sum(por_mes[m]["sucursales"][grp]["margen"] for m in meses_activos) / len(meses_activos)
            for grp in _GRUPOS
        }
        mejor_suc = max(_GRUPOS, key=avg_margen.__getitem__)
        peor_suc = min(_GRUPOS, key=avg_margen.__getitem__)
    else:
        mejor_ebitda = peor_ebitda = mejor_suc = peor_suc = None

    total_alertas = sum(len(por_mes[m]["alertas"]) for m in meses_activos)

    return {
        "cliente_id": cliente_id,
        "periodo": periodo,
        "por_mes": por_mes,
        "tendencias": tendencias,
        "resumen_ejecutivo": {
            "meses_analizados": len(meses_activos),
            "mejor_mes_ebitda": mejor_ebitda,
            "peor_mes_ebitda": peor_ebitda,
            "mejor_sucursal_promedio": mejor_suc,
            "peor_sucursal_promedio": peor_suc,
            "total_alertas_activas": total_alertas,
        },
    }


# ── Private helpers ───────────────────────────────────────────────────────────

def _div(numerator: float, denominator: float) -> float:
    """Safe division, rounded to 4 dp. Returns 0.0 when denominator is zero."""
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def _severidad(valor: float, umbral: float) -> str:
    if umbral == 0:
        return "baja"
    ratio = valor / umbral
    if ratio < 0.5:
        return "alta"
    if ratio < 0.75:
        return "media"
    return "baja"


def _alerta(tipo: str, valor: float, umbral: float, descripcion: str) -> dict:
    return {
        "tipo": tipo,
        "severidad": _severidad(valor, umbral),
        "descripcion": descripcion,
        "valor": valor,
        "umbral": umbral,
    }


def _serie(values: list[float]) -> dict:
    """Build a trend series. Needs at least 2 points to compute tendency."""
    if len(values) < 2:
        return {"valores": values, "tendencia": "insuficiente_datos", "variacion_pct_ultimo_mes": None}

    variacion = None
    if values[-2] != 0:
        variacion = round((values[-1] - values[-2]) / abs(values[-2]), 4)

    first, last = values[0], values[-1]
    if first == 0:
        tendencia = "creciente" if last > 0 else "estable"
    else:
        cambio = (last - first) / abs(first)
        if cambio > 0.05:
            tendencia = "creciente"
        elif cambio < -0.05:
            tendencia = "decreciente"
        else:
            tendencia = "estable"

    return {"valores": values, "tendencia": tendencia, "variacion_pct_ultimo_mes": variacion}


def _month_sort_key(mes_nombre: str) -> tuple[int, int]:
    parts = mes_nombre.strip().upper().split()
    month_num = _MONTH_ORDER.get(parts[0], 0) if parts else 0
    year = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    return (year, month_num)


def _margen_grupo(mes_data: dict, grp: str) -> float:
    v = mes_data.get("ventas", {}).get(grp, {}).get("total", 0.0)
    e = mes_data.get("egresos", {}).get(grp, {}).get("total", 0.0)
    return _div(v - e, v)
