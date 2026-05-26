import pytest
from src.pipeline.kpis import KPIReport
from src.pipeline.scenario import (
    ScenarioConfig,
    ScenarioResult,
    DistribucionMetrica,
    simular_escenario,
)

# ── fixture ───────────────────────────────────────────────────────────────────

_BENCHMARKS = {
    "margen_bruto": 0.68,
    "nomina_pct": 0.28,
    "gastos_financieros_pct": 0.05,
    "margen_neto": 0.10,
}


def _make_kpi_report(revenue=8_790_000.0, meses=None) -> KPIReport:
    meses = meses or ["ENERO 2026"]
    por_mes = {
        mes: {
            "consolidado": {
                "total_revenue": revenue,
                "total_costo_directo": revenue * 0.30,
                "utilidad_bruta": revenue * 0.70,
                "margen_bruto": 0.70,
                "nomina": revenue * 0.27,
                "gastos_financieros": revenue * 0.08,
                "total_gastos_operacion": revenue * 0.43,
                "ebitda": revenue * 0.27,
                "margen_ebitda": 0.27,
                "utilidad_neta": revenue * 0.19,
                "margen_neto": 0.19,
                "costo_directo_pct": 0.30,
                "nomina_pct": 0.27,
                "gastos_op_pct": 0.43,
                "gastos_financieros_pct": 0.08,
            },
            "vs_benchmark": {},
            "efficiency_ranking": [],
            "skus_bajo_rendimiento": [],
        }
        for mes in meses
    }
    return KPIReport(
        meses_analizados=meses,
        por_mes=por_mes,
        tendencias={},
        resumen_ejecutivo={},
    )


def _neutral_config(n=1_000) -> ScenarioConfig:
    return ScenarioConfig(variaciones={}, sigmas={}, n_simulaciones=n, semilla=42)


# ── return type ───────────────────────────────────────────────────────────────

def test_simular_returns_scenario_result():
    result = simular_escenario(_make_kpi_report(), _neutral_config(), _BENCHMARKS)
    assert isinstance(result, ScenarioResult)


def test_result_mes_base_matches_last_mes():
    kpi = _make_kpi_report(meses=["ENERO 2026", "FEBRERO 2026"])
    result = simular_escenario(kpi, _neutral_config(), _BENCHMARKS)
    assert result.mes_base == "FEBRERO 2026"


def test_n_simulaciones_in_result():
    result = simular_escenario(_make_kpi_report(), _neutral_config(n=500), _BENCHMARKS)
    assert result.n_simulaciones == 500


# ── distribuciones ────────────────────────────────────────────────────────────

def test_distribuciones_contain_expected_keys():
    result = simular_escenario(_make_kpi_report(), _neutral_config(), _BENCHMARKS)
    for key in ("revenue", "margen_bruto", "ebitda", "margen_ebitda", "margen_neto",
                "nomina_pct", "gastos_financieros_pct"):
        assert key in result.distribuciones, f"Missing key: {key}"


def test_distribucion_is_distrib_metrica():
    result = simular_escenario(_make_kpi_report(), _neutral_config(), _BENCHMARKS)
    assert isinstance(result.distribuciones["margen_bruto"], DistribucionMetrica)


def test_percentile_order_consistent():
    result = simular_escenario(_make_kpi_report(), _neutral_config(), _BENCHMARKS)
    d = result.distribuciones["margen_bruto"]
    assert d.p10 <= d.p25 <= d.p50 <= d.p75 <= d.p90


def test_valores_sample_nonempty():
    result = simular_escenario(_make_kpi_report(), _neutral_config(n=1_000), _BENCHMARKS)
    assert len(result.distribuciones["margen_bruto"].valores) > 0
    assert len(result.distribuciones["margen_bruto"].valores) <= 500


def test_desviacion_positive_with_nonzero_sigma():
    config = ScenarioConfig(variaciones={}, sigmas={"revenue": 0.10}, n_simulaciones=2_000, semilla=42)
    result = simular_escenario(_make_kpi_report(), config, _BENCHMARKS)
    assert result.distribuciones["margen_bruto"].desviacion > 0


def test_zero_sigma_gives_near_zero_desviacion():
    config = ScenarioConfig(
        variaciones={},
        sigmas={k: 0.0 for k in ("revenue", "costo_directo", "nomina", "gastos_financieros")},
        n_simulaciones=100,
        semilla=0,
    )
    result = simular_escenario(_make_kpi_report(), config, _BENCHMARKS)
    assert result.distribuciones["margen_bruto"].desviacion < 1e-9


# ── medians reflect expected shifts ───────────────────────────────────────────

def test_positive_revenue_shift_raises_revenue_median():
    base = simular_escenario(_make_kpi_report(), _neutral_config(n=5_000), _BENCHMARKS)
    up_cfg = ScenarioConfig(variaciones={"revenue": 0.20}, sigmas={k: 0.001 for k in ("revenue","costo_directo","nomina","gastos_financieros")}, n_simulaciones=5_000, semilla=42)
    up = simular_escenario(_make_kpi_report(), up_cfg, _BENCHMARKS)
    assert up.distribuciones["revenue"].p50 > base.distribuciones["revenue"].p50


def test_higher_cost_shift_lowers_margin_median():
    low_cfg = ScenarioConfig(variaciones={"costo_directo": 0.0}, sigmas={k: 0.001 for k in ("revenue","costo_directo","nomina","gastos_financieros")}, n_simulaciones=5_000, semilla=42)
    high_cfg = ScenarioConfig(variaciones={"costo_directo": 0.30}, sigmas={k: 0.001 for k in ("revenue","costo_directo","nomina","gastos_financieros")}, n_simulaciones=5_000, semilla=42)
    low = simular_escenario(_make_kpi_report(), low_cfg, _BENCHMARKS)
    high = simular_escenario(_make_kpi_report(), high_cfg, _BENCHMARKS)
    assert high.distribuciones["margen_bruto"].p50 < low.distribuciones["margen_bruto"].p50


def test_zero_shift_zero_sigma_median_close_to_base():
    kpi = _make_kpi_report()
    config = ScenarioConfig(
        variaciones={},
        sigmas={k: 0.0 for k in ("revenue", "costo_directo", "nomina", "gastos_financieros")},
        n_simulaciones=100,
        semilla=0,
    )
    result = simular_escenario(kpi, config, _BENCHMARKS)
    assert abs(result.distribuciones["margen_bruto"].p50 - 0.70) < 0.001


# ── probabilidades ────────────────────────────────────────────────────────────

def test_probabilidades_between_0_and_1():
    result = simular_escenario(_make_kpi_report(), _neutral_config(n=2_000), _BENCHMARKS)
    for k, v in result.probabilidades_benchmark.items():
        assert 0.0 <= v <= 1.0, f"{k}={v} out of [0,1]"


def test_probabilidades_contain_expected_keys():
    result = simular_escenario(_make_kpi_report(), _neutral_config(), _BENCHMARKS)
    for key in ("margen_bruto_sobre_benchmark", "nomina_bajo_benchmark",
                "gastos_fin_bajo_benchmark", "margen_neto_sobre_benchmark", "ebitda_positivo"):
        assert key in result.probabilidades_benchmark


def test_ebitda_positivo_high_when_healthy():
    result = simular_escenario(
        _make_kpi_report(),
        ScenarioConfig(variaciones={}, sigmas={k: 0.01 for k in ("revenue","costo_directo","nomina","gastos_financieros")}, n_simulaciones=5_000, semilla=42),
        _BENCHMARKS,
    )
    assert result.probabilidades_benchmark["ebitda_positivo"] > 0.90


# ── narrativa ─────────────────────────────────────────────────────────────────

def test_narrativa_nonempty():
    result = simular_escenario(_make_kpi_report(), _neutral_config(), _BENCHMARKS)
    assert isinstance(result.narrativa, str) and len(result.narrativa) > 20


def test_narrativa_in_spanish():
    result = simular_escenario(_make_kpi_report(), _neutral_config(), _BENCHMARKS)
    markers = ["el", "la", "de", "con", "una", "mediana", "margen", "proyectado"]
    assert any(m in result.narrativa.lower() for m in markers)


# ── variables_input stored ────────────────────────────────────────────────────

def test_variables_input_stored_in_result():
    config = ScenarioConfig(variaciones={"revenue": 0.05, "nomina": -0.02}, n_simulaciones=100, semilla=0)
    result = simular_escenario(_make_kpi_report(), config, _BENCHMARKS)
    assert result.variables_input["variaciones_esperadas"]["revenue"] == pytest.approx(0.05)
    assert result.variables_input["variaciones_esperadas"]["nomina"] == pytest.approx(-0.02)
