from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .integrator import FinancialData
from .parsers.parser_utils import month_sort_key


@dataclass
class KPIReport:
    meses_analizados: List[str]
    por_mes: Dict[str, Any]
    tendencias: Dict[str, Any]
    resumen_ejecutivo: Dict[str, Any]


# KPIs where a lower value is better
_LOWER_IS_BETTER = {"costo_directo_pct", "nomina_pct", "gastos_op_pct", "gastos_financieros_pct"}


def _get_estado(valor: float, benchmark: float, lower_is_better: bool) -> str:
    if benchmark == 0:
        return "en_rango"
    if lower_is_better:
        if valor <= benchmark:
            return "en_rango"
        excess = (valor - benchmark) / abs(benchmark)
        if excess <= 0.05:
            return "en_rango"
        elif excess <= 0.15:
            return "alerta"
        else:
            return "critico"
    else:
        if valor >= benchmark:
            return "en_rango"
        shortfall = (benchmark - valor) / abs(benchmark)
        if shortfall <= 0.05:
            return "en_rango"
        elif shortfall <= 0.15:
            return "alerta"
        else:
            return "critico"


def _calc_tendencia(valores: List[float], meses: List[str]) -> Dict[str, Any]:
    if len(valores) < 2 or valores[0] == 0:
        return {"valores": valores, "meses": meses, "tendencia": "insuficiente_datos", "variacion_pct": None}
    variacion_pct = (valores[-1] - valores[0]) / valores[0]
    if variacion_pct > 0.05:
        tendencia = "creciente"
    elif variacion_pct < -0.05:
        tendencia = "decreciente"
    else:
        tendencia = "estable"
    return {"valores": valores, "meses": meses, "tendencia": tendencia, "variacion_pct": variacion_pct}


def calcular_kpis(financial_data: FinancialData, config: Dict) -> KPIReport:
    benchmarks = config.get("benchmarks", {})
    meses = financial_data.meses

    por_mes: Dict[str, Any] = {}
    revenue_vals: List[float] = []
    margen_bruto_vals: List[float] = []
    ebitda_vals: List[float] = []
    margen_neto_vals: List[float] = []
    suc_revenue: Dict[str, List[float]] = {}
    suc_margen: Dict[str, List[float]] = {}

    for mes in meses:
        md = financial_data.por_mes[mes]
        gastos = md["gastos_operativos"]

        total_revenue = md["total_revenue"]
        total_costo_directo = md["total_costo_directo"]
        utilidad_bruta = md["utilidad_bruta_bd"]
        nomina = gastos.get("nomina", 0.0)
        gastos_financieros = gastos.get("gastos_financieros", 0.0)
        total_gastos_op = gastos.get("total_gastos_operacion", 0.0)
        impuestos = gastos.get("impuestos", 0.0)

        ebitda = utilidad_bruta - total_gastos_op
        utilidad_neta = ebitda - gastos_financieros - impuestos

        def _safe_div(n, d):
            return n / d if d else 0.0

        margen_bruto = _safe_div(utilidad_bruta, total_revenue)
        margen_ebitda = _safe_div(ebitda, total_revenue)
        margen_neto = _safe_div(utilidad_neta, total_revenue)
        costo_directo_pct = _safe_div(total_costo_directo, total_revenue)
        nomina_pct = _safe_div(nomina, total_revenue)
        gastos_op_pct = _safe_div(total_gastos_op, total_revenue)
        gastos_financieros_pct = _safe_div(gastos_financieros, total_revenue)

        consolidado = {
            "total_revenue": total_revenue,
            "total_costo_directo": total_costo_directo,
            "utilidad_bruta": utilidad_bruta,
            "margen_bruto": margen_bruto,
            "nomina": nomina,
            "gastos_financieros": gastos_financieros,
            "total_gastos_operacion": total_gastos_op,
            "ebitda": ebitda,
            "margen_ebitda": margen_ebitda,
            "utilidad_neta": utilidad_neta,
            "margen_neto": margen_neto,
            "costo_directo_pct": costo_directo_pct,
            "nomina_pct": nomina_pct,
            "gastos_op_pct": gastos_op_pct,
            "gastos_financieros_pct": gastos_financieros_pct,
        }

        def _vs(valor, key, lib):
            bench = benchmarks.get(key, 0.0)
            return {
                "valor": valor,
                "benchmark": bench,
                "diferencia": valor - bench,
                "estado": _get_estado(valor, bench, lib),
            }

        vs_benchmark = {
            "costo_directo_pct": _vs(costo_directo_pct, "costo_directo_pct", True),
            "margen_bruto": _vs(margen_bruto, "margen_bruto", False),
            "nomina_pct": _vs(nomina_pct, "nomina_pct", True),
            "gastos_op_pct": _vs(gastos_op_pct, "gastos_op_pct", True),
            "gastos_financieros_pct": _vs(gastos_financieros_pct, "gastos_financieros_pct", True),
            "margen_neto": _vs(margen_neto, "margen_neto", False),
        }

        # Por sucursal (ranked by revenue desc)
        suc_raw = md["por_sucursal"]
        suc_sorted = sorted(suc_raw.items(), key=lambda x: -x[1]["revenue"])
        por_sucursal: Dict[str, Any] = {}
        for rank, (suc, sdata) in enumerate(suc_sorted, 1):
            por_sucursal[suc] = {
                "revenue": sdata["revenue"],
                "costo_directo": sdata["costo_directo"],
                "utilidad_bruta": sdata["utilidad_bruta"],
                "margen_bruto": sdata["margen_bruto"],
                "participacion_revenue": _safe_div(sdata["revenue"], total_revenue),
                "ranking": rank,
            }

        # Por categoria (aggregated across all sucursales)
        cat_agg: Dict[str, Any] = {}
        for sdata in suc_raw.values():
            for cat, cdata in sdata["por_categoria"].items():
                if cat not in cat_agg:
                    cat_agg[cat] = {"revenue": 0.0, "costo": 0.0, "utilidad": 0.0, "unidades": 0}
                cat_agg[cat]["revenue"] += cdata["revenue"]
                cat_agg[cat]["costo"] += cdata["costo"]
                cat_agg[cat]["utilidad"] += cdata["utilidad"]
                cat_agg[cat]["unidades"] += cdata["unidades"]

        por_categoria: Dict[str, Any] = {
            cat: {
                "revenue": d["revenue"],
                "costo": d["costo"],
                "utilidad_bruta": d["utilidad"],
                "margen_bruto": _safe_div(d["utilidad"], d["revenue"]),
                "participacion_revenue": _safe_div(d["revenue"], total_revenue),
                "unidades_vendidas": d["unidades"],
            }
            for cat, d in cat_agg.items()
        }

        # Efficiency ranking — all SKUs sorted by multiplicador desc
        skus = md["por_sku"]
        efficiency_ranking = sorted(
            [
                {
                    "sku": r["sku"],
                    "sucursal": r["sucursal"],
                    "categoria": r["categoria"],
                    "multiplicador_eficiencia": r["multiplicador_eficiencia"],
                    "margen_bruto": r["margen_bruto"],
                    "revenue": r["subtotal"],
                }
                for r in skus
            ],
            key=lambda x: -x["multiplicador_eficiencia"],
        )
        for i, item in enumerate(efficiency_ranking, 1):
            item["ranking"] = i

        top_skus_revenue = sorted(
            [{"sku": r["sku"], "sucursal": r["sucursal"], "categoria": r["categoria"],
              "revenue": r["subtotal"], "margen_bruto": r["margen_bruto"]}
             for r in skus],
            key=lambda x: -x["revenue"],
        )[:10]

        bench_margen = benchmarks.get("margen_bruto", 0.0)
        skus_bajo = [
            {"sku": r["sku"], "sucursal": r["sucursal"], "categoria": r["categoria"],
             "margen_bruto": r["margen_bruto"], "revenue": r["subtotal"]}
            for r in skus
            if r["margen_bruto"] < bench_margen
        ]

        # Alertas — KPI level
        alertas: List[Dict] = []
        kpi_alert_cfg = [
            ("costo_directo_pct", "costo_directo_alto", True),
            ("nomina_pct", "nomina_alta", True),
            ("gastos_op_pct", "gastos_op_altos", True),
            ("gastos_financieros_pct", "gastos_financieros_altos", True),
            ("margen_bruto", "margen_bruto_bajo", False),
            ("margen_neto", "margen_neto_bajo", False),
        ]
        for kpi_key, tipo, lib in kpi_alert_cfg:
            item = vs_benchmark[kpi_key]
            if item["estado"] in ("alerta", "critico"):
                direction = "por encima" if lib else "por debajo"
                alertas.append({
                    "tipo": tipo,
                    "severidad": "alta" if item["estado"] == "critico" else "media",
                    "entidad": None,
                    "descripcion": (
                        f"{kpi_key} ({item['valor']:.2%}) está {direction} "
                        f"del benchmark ({item['benchmark']:.2%})"
                    ),
                    "valor": item["valor"],
                    "benchmark": item["benchmark"],
                    "diferencia_pct": item["diferencia"],
                })

        # Sucursal margen alerts
        for suc, sdata in por_sucursal.items():
            if sdata["margen_bruto"] < bench_margen:
                shortfall = _safe_div(bench_margen - sdata["margen_bruto"], bench_margen)
                sev = "alta" if shortfall > 0.15 else "media" if shortfall > 0.05 else "baja"
                alertas.append({
                    "tipo": "margen_sucursal",
                    "severidad": sev,
                    "entidad": suc,
                    "descripcion": f"Sucursal {suc} margen {sdata['margen_bruto']:.2%} bajo benchmark {bench_margen:.2%}",
                    "valor": sdata["margen_bruto"],
                    "benchmark": bench_margen,
                    "diferencia_pct": sdata["margen_bruto"] - bench_margen,
                })

        por_mes[mes] = {
            "consolidado": consolidado,
            "vs_benchmark": vs_benchmark,
            "por_sucursal": por_sucursal,
            "por_categoria": por_categoria,
            "efficiency_ranking": efficiency_ranking,
            "top_skus_revenue": top_skus_revenue,
            "skus_bajo_rendimiento": skus_bajo,
            "alertas": alertas,
        }

        # Accumulate tendencia series
        revenue_vals.append(total_revenue)
        margen_bruto_vals.append(margen_bruto)
        ebitda_vals.append(ebitda)
        margen_neto_vals.append(margen_neto)
        for suc, sdata in suc_raw.items():
            suc_revenue.setdefault(suc, []).append(sdata["revenue"])
            suc_margen.setdefault(suc, []).append(sdata["margen_bruto"])

    tendencias: Dict[str, Any] = {
        "revenue": _calc_tendencia(revenue_vals, meses),
        "margen_bruto": _calc_tendencia(margen_bruto_vals, meses),
        "ebitda": _calc_tendencia(ebitda_vals, meses),
        "margen_neto": _calc_tendencia(margen_neto_vals, meses),
        "por_sucursal": {
            suc: {
                "revenue": _calc_tendencia(suc_revenue[suc], meses),
                "margen_bruto": _calc_tendencia(suc_margen[suc], meses),
            }
            for suc in suc_revenue
        },
    }

    # Resumen ejecutivo — derived from last month
    resumen: Dict[str, Any] = {}
    if meses:
        lm = por_mes[meses[-1]]
        suc_by_margen = sorted(lm["por_sucursal"].items(), key=lambda x: x[1]["margen_bruto"])
        cat_by_margen = sorted(lm["por_categoria"].items(), key=lambda x: x[1]["margen_bruto"])
        resumen = {
            "mejor_sucursal_margen": suc_by_margen[-1][0] if suc_by_margen else None,
            "peor_sucursal_margen": suc_by_margen[0][0] if suc_by_margen else None,
            "mejor_categoria_margen": cat_by_margen[-1][0] if cat_by_margen else None,
            "sku_top_multiplicador": lm["efficiency_ranking"][0]["sku"] if lm["efficiency_ranking"] else None,
            "sku_top_revenue": lm["top_skus_revenue"][0]["sku"] if lm["top_skus_revenue"] else None,
            "skus_bajo_rendimiento_count": len(lm["skus_bajo_rendimiento"]),
            "kpis_en_alerta": [k for k, v in lm["vs_benchmark"].items() if v["estado"] != "en_rango"],
            "total_alertas": len(lm["alertas"]),
        }

    return KPIReport(
        meses_analizados=meses,
        por_mes=por_mes,
        tendencias=tendencias,
        resumen_ejecutivo=resumen,
    )
