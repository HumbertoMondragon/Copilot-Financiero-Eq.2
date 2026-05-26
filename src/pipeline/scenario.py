from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from .kpis import KPIReport

_SIGMA_DEFAULTS = {
    "revenue": 0.05,
    "costo_directo": 0.04,
    "nomina": 0.03,
    "gastos_financieros": 0.02,
}


@dataclass
class ScenarioConfig:
    variaciones: Dict[str, float]  # expected % shift per variable: {"revenue": 0.05, ...}
    sigmas: Dict[str, float] = field(default_factory=dict)  # uncertainty (std dev); uses defaults if missing
    n_simulaciones: int = 10_000
    semilla: Optional[int] = None


@dataclass
class DistribucionMetrica:
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    media: float
    desviacion: float
    valores: List[float] = field(default_factory=list)  # ~500 samples for histogram


@dataclass
class ScenarioResult:
    n_simulaciones: int
    mes_base: str
    variables_input: Dict[str, Any]
    distribuciones: Dict[str, DistribucionMetrica]
    probabilidades_benchmark: Dict[str, float]
    narrativa: str


def simular_escenario(
    kpi_report: KPIReport,
    config: ScenarioConfig,
    benchmarks: Optional[Dict[str, float]] = None,
) -> ScenarioResult:
    benchmarks = benchmarks or {}
    mes = kpi_report.meses_analizados[-1]
    con = kpi_report.por_mes[mes]["consolidado"]

    revenue_base = con.get("total_revenue", 0.0)
    costo_directo_base = con.get("total_costo_directo", 0.0)
    nomina_base = con.get("nomina", 0.0)
    gastos_fin_base = con.get("gastos_financieros", 0.0)
    total_gastos_op_base = con.get("total_gastos_operacion", 0.0)

    otros_gastos_op = total_gastos_op_base - nomina_base

    sigmas = {k: config.sigmas.get(k, _SIGMA_DEFAULTS[k]) for k in _SIGMA_DEFAULTS}
    n = config.n_simulaciones
    rng = np.random.default_rng(config.semilla)

    def _sample(key: str) -> np.ndarray:
        mu = config.variaciones.get(key, 0.0)
        sigma = sigmas[key]
        return 1.0 + mu + rng.normal(0.0, sigma, n)

    r_rev = _sample("revenue")
    r_cos = _sample("costo_directo")
    r_nom = _sample("nomina")
    r_gfin = _sample("gastos_financieros")

    revenue_sim = revenue_base * r_rev
    costo_directo_sim = costo_directo_base * r_cos
    utilidad_bruta_sim = revenue_sim - costo_directo_sim

    # Avoid division by zero in degenerate simulations
    safe_rev = np.where(revenue_sim <= 0, np.nan, revenue_sim)
    margen_bruto_sim = utilidad_bruta_sim / safe_rev

    nomina_sim = nomina_base * r_nom
    total_gastos_op_sim = nomina_sim + otros_gastos_op
    ebitda_sim = utilidad_bruta_sim - total_gastos_op_sim
    margen_ebitda_sim = ebitda_sim / safe_rev

    gastos_fin_sim = gastos_fin_base * r_gfin
    utilidad_neta_sim = ebitda_sim - gastos_fin_sim
    margen_neto_sim = utilidad_neta_sim / safe_rev

    nomina_pct_sim = nomina_sim / safe_rev
    gastos_fin_pct_sim = gastos_fin_sim / safe_rev

    def _dist(arr: np.ndarray) -> DistribucionMetrica:
        clean = arr[~np.isnan(arr)]
        if len(clean) == 0:
            z = 0.0
            return DistribucionMetrica(z, z, z, z, z, z, z, [])
        sample_idx = rng.choice(len(clean), size=min(500, len(clean)), replace=False)
        return DistribucionMetrica(
            p10=float(np.percentile(clean, 10)),
            p25=float(np.percentile(clean, 25)),
            p50=float(np.percentile(clean, 50)),
            p75=float(np.percentile(clean, 75)),
            p90=float(np.percentile(clean, 90)),
            media=float(np.mean(clean)),
            desviacion=float(np.std(clean)),
            valores=clean[sample_idx].tolist(),
        )

    distribuciones = {
        "revenue": _dist(revenue_sim),
        "margen_bruto": _dist(margen_bruto_sim),
        "ebitda": _dist(ebitda_sim),
        "margen_ebitda": _dist(margen_ebitda_sim),
        "margen_neto": _dist(margen_neto_sim),
        "nomina_pct": _dist(nomina_pct_sim),
        "gastos_financieros_pct": _dist(gastos_fin_pct_sim),
    }

    bench_mb = benchmarks.get("margen_bruto", 0.68)
    bench_nom = benchmarks.get("nomina_pct", 0.28)
    bench_gfin = benchmarks.get("gastos_financieros_pct", 0.05)
    bench_mn = benchmarks.get("margen_neto", 0.10)

    valid = ~np.isnan(margen_bruto_sim)
    probabilidades_benchmark = {
        "margen_bruto_sobre_benchmark": float(np.mean(margen_bruto_sim[valid] >= bench_mb)),
        "nomina_bajo_benchmark": float(np.mean(nomina_pct_sim[valid] <= bench_nom)),
        "gastos_fin_bajo_benchmark": float(np.mean(gastos_fin_pct_sim[valid] <= bench_gfin)),
        "margen_neto_sobre_benchmark": float(np.mean(margen_neto_sim[valid] >= bench_mn)),
        "ebitda_positivo": float(np.mean(ebitda_sim[valid] > 0)),
    }

    mb_med = distribuciones["margen_bruto"].p50
    ebitda_med = distribuciones["ebitda"].p50
    prob_mb = probabilidades_benchmark["margen_bruto_sobre_benchmark"]
    prob_ebitda = probabilidades_benchmark["ebitda_positivo"]

    narrativa = (
        f"Bajo el escenario simulado con {n:,} iteraciones, el margen bruto proyectado tiene "
        f"una mediana de {mb_med:.1%} con {prob_mb:.0%} de probabilidad de superar el "
        f"benchmark sectorial de {bench_mb:.1%}. "
        f"El EBITDA mediano proyectado es ${ebitda_med:,.0f}, "
        f"con {prob_ebitda:.0%} de probabilidad de mantenerse positivo. "
        f"La dispersión de resultados refleja la incertidumbre inherente en cada variable."
    )

    return ScenarioResult(
        n_simulaciones=n,
        mes_base=mes,
        variables_input={
            "variaciones_esperadas": config.variaciones,
            "sigmas_incertidumbre": sigmas,
        },
        distribuciones=distribuciones,
        probabilidades_benchmark=probabilidades_benchmark,
        narrativa=narrativa,
    )
