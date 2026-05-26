from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .kpis import KPIReport
from .macro import MacroIndices


@dataclass
class HealthScoreReport:
    por_mes: Dict[str, Any]
    tendencia_score: Dict[str, Any]


def _score_higher_is_better(valor: float, benchmark: float) -> int:
    if valor >= benchmark * 1.10:
        return 100
    if valor >= benchmark * 1.00:
        return 80
    if valor >= benchmark * 0.90:
        return 60
    if valor >= benchmark * 0.75:
        return 40
    if valor >= benchmark * 0.60:
        return 20
    return 0


def _score_lower_is_better(valor: float, benchmark: float) -> int:
    if valor <= benchmark * 0.90:
        return 100
    if valor <= benchmark * 1.00:
        return 80
    if valor <= benchmark * 1.10:
        return 60
    if valor <= benchmark * 1.25:
        return 40
    if valor <= benchmark * 1.50:
        return 20
    return 0


def _score_presion_inflacionaria(valor: float) -> int:
    if valor <= 0.2:
        return 100
    if valor <= 0.5:
        return 80
    if valor <= 0.8:
        return 60
    if valor <= 1.2:
        return 40
    if valor <= 1.6:
        return 20
    return 0


def _score_tendencia_ingresos(tendencia: str, variacion_pct: Optional[float]) -> int:
    if tendencia == "insuficiente_datos":
        return 50
    if tendencia == "creciente":
        return 100 if (variacion_pct is not None and variacion_pct > 0.05) else 75
    if tendencia == "estable":
        return 50
    if tendencia == "decreciente":
        return 10 if (variacion_pct is not None and variacion_pct <= -0.05) else 30
    return 50


def _score_to_categoria(score: float) -> str:
    if score >= 75:
        return "saludable"
    if score >= 55:
        return "en_observacion"
    if score >= 35:
        return "en_riesgo"
    return "critico"


def _tendencia_scores(scores: List[float]) -> str:
    if len(scores) < 2:
        return "insuficiente_datos"
    first, last = scores[0], scores[-1]
    if first == 0:
        return "insuficiente_datos"
    variacion = (last - first) / abs(first)
    if variacion > 0.05:
        return "creciente"
    if variacion < -0.05:
        return "decreciente"
    return "estable"


def calcular_health_score(
    kpi_report: KPIReport,
    macro_indices: Optional[MacroIndices],
    config: Dict,
) -> HealthScoreReport:
    benchmarks = config.get("benchmarks", {})
    weights: Dict[str, float] = config.get(
        "health_score_weights",
        {
            "margen_bruto_vs_benchmark": 0.30,
            "nomina_vs_benchmark": 0.25,
            "gastos_financieros_vs_benchmark": 0.20,
            "presion_inflacionaria": 0.15,
            "tendencia_ingresos": 0.10,
        },
    )

    rev_tend = kpi_report.tendencias.get("revenue", {})
    tendencia_ingresos = rev_tend.get("tendencia", "insuficiente_datos")
    variacion_pct_ingresos: Optional[float] = rev_tend.get("variacion_pct")

    pi_score = 50  # neutral default when no macro data
    pi_val: Optional[float] = None
    if macro_indices is not None:
        pi_val = macro_indices.indice_presion_inflacionaria["valor"]
        pi_score = _score_presion_inflacionaria(pi_val)

    por_mes: Dict[str, Any] = {}
    score_history: List[float] = []

    for mes in kpi_report.meses_analizados:
        consolidado = kpi_report.por_mes[mes]["consolidado"]

        mb_val = consolidado.get("margen_bruto", 0.0)
        mb_bench = benchmarks.get("margen_bruto", 0.68)
        mb_peso = weights.get("margen_bruto_vs_benchmark", 0.30)
        mb_score = _score_higher_is_better(mb_val, mb_bench)

        nom_val = consolidado.get("nomina_pct", 0.0)
        nom_bench = benchmarks.get("nomina_pct", 0.28)
        nom_peso = weights.get("nomina_vs_benchmark", 0.25)
        nom_score = _score_lower_is_better(nom_val, nom_bench)

        gf_val = consolidado.get("gastos_financieros_pct", 0.0)
        gf_bench = benchmarks.get("gastos_financieros_pct", 0.05)
        gf_peso = weights.get("gastos_financieros_vs_benchmark", 0.20)
        gf_score = _score_lower_is_better(gf_val, gf_bench)

        pi_peso = weights.get("presion_inflacionaria", 0.15)

        ti_score = _score_tendencia_ingresos(tendencia_ingresos, variacion_pct_ingresos)
        ti_peso = weights.get("tendencia_ingresos", 0.10)

        dimensiones: Dict[str, Any] = {
            "margen_bruto_vs_benchmark": {
                "score": mb_score,
                "peso": mb_peso,
                "valor_base": mb_val,
                "benchmark": mb_bench,
                "contribucion": round(mb_score * mb_peso, 4),
            },
            "nomina_vs_benchmark": {
                "score": nom_score,
                "peso": nom_peso,
                "valor_base": nom_val,
                "benchmark": nom_bench,
                "contribucion": round(nom_score * nom_peso, 4),
            },
            "gastos_financieros_vs_benchmark": {
                "score": gf_score,
                "peso": gf_peso,
                "valor_base": gf_val,
                "benchmark": gf_bench,
                "contribucion": round(gf_score * gf_peso, 4),
            },
            "presion_inflacionaria": {
                "score": pi_score,
                "peso": pi_peso,
                "valor_base": pi_val,
                "benchmark": None,
                "contribucion": round(pi_score * pi_peso, 4),
            },
            "tendencia_ingresos": {
                "score": ti_score,
                "peso": ti_peso,
                "valor_base": tendencia_ingresos,
                "benchmark": None,
                "contribucion": round(ti_score * ti_peso, 4),
            },
        }

        score_total = round(sum(d["contribucion"] for d in dimensiones.values()), 4)
        score_history.append(score_total)

        dim_mas_debil = min(dimensiones, key=lambda k: dimensiones[k]["score"])
        dim_mas_fuerte = max(dimensiones, key=lambda k: dimensiones[k]["score"])

        por_mes[mes] = {
            "score_total": score_total,
            "categoria": _score_to_categoria(score_total),
            "dimensiones": dimensiones,
            "score_total_verificacion": score_total,
            "dimension_mas_debil": dim_mas_debil,
            "dimension_mas_fuerte": dim_mas_fuerte,
        }

    return HealthScoreReport(
        por_mes=por_mes,
        tendencia_score={
            "valores": score_history,
            "meses": list(kpi_report.meses_analizados),
            "tendencia": _tendencia_scores(score_history),
        },
    )
