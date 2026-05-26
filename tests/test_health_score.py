import pytest
from typing import Optional

from src.pipeline.kpis import KPIReport
from src.pipeline.macro import MacroIndices
from src.pipeline.health_score import calcular_health_score, HealthScoreReport

_CONFIG = {
    "benchmarks": {
        "margen_bruto": 0.68,
        "nomina_pct": 0.28,
        "gastos_financieros_pct": 0.05,
    },
    "health_score_weights": {
        "margen_bruto_vs_benchmark": 0.30,
        "nomina_vs_benchmark": 0.25,
        "gastos_financieros_vs_benchmark": 0.20,
        "presion_inflacionaria": 0.15,
        "tendencia_ingresos": 0.10,
    },
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_kpi(
    margen_bruto=0.68,
    nomina_pct=0.28,
    gastos_fin_pct=0.05,
    tendencia="estable",
    variacion_pct=0.0,
    meses=None,
) -> KPIReport:
    meses = meses or ["ENERO 2026"]
    por_mes = {
        mes: {
            "consolidado": {
                "margen_bruto": margen_bruto,
                "nomina_pct": nomina_pct,
                "gastos_financieros_pct": gastos_fin_pct,
                "total_revenue": 1_000_000.0,
                "ebitda": 100_000.0,
                "utilidad_neta": 50_000.0,
            }
        }
        for mes in meses
    }
    return KPIReport(
        meses_analizados=meses,
        por_mes=por_mes,
        tendencias={
            "revenue": {
                "valores": [1_000_000.0] * len(meses),
                "meses": meses,
                "tendencia": tendencia,
                "variacion_pct": variacion_pct,
            }
        },
        resumen_ejecutivo={},
    )


def _make_macro(presion_inflacionaria_valor: float) -> MacroIndices:
    return MacroIndices(
        indice_presion_inflacionaria={
            "valor": presion_inflacionaria_valor,
            "interpretacion": "moderada",
            "componentes": {},
            "descripcion": "",
        },
        indice_entorno_economico={"valor": 0.5, "interpretacion": "neutral", "descripcion": ""},
        indice_presion_financiera={"valor": 0.6, "interpretacion": "moderada", "descripcion": ""},
        narrativa_consolidada="Narrativa de prueba.",
    )


# ── score arithmetic ──────────────────────────────────────────────────────────

def test_score_total_equals_sum_of_contributions():
    kpi = _make_kpi()
    result = calcular_health_score(kpi, None, _CONFIG)
    for mes, data in result.por_mes.items():
        expected = sum(d["contribucion"] for d in data["dimensiones"].values())
        assert abs(data["score_total"] - expected) < 0.001


def test_contribuciones_sum_to_score_total():
    kpi = _make_kpi(margen_bruto=0.70, nomina_pct=0.30, gastos_fin_pct=0.08)
    macro = _make_macro(0.6)
    result = calcular_health_score(kpi, macro, _CONFIG)
    for mes, data in result.por_mes.items():
        total_contribs = sum(d["contribucion"] for d in data["dimensiones"].values())
        assert abs(total_contribs - data["score_total_verificacion"]) < 0.001


def test_score_total_between_0_and_100():
    for mb, nom, gf in [(0.0, 1.0, 1.0), (1.0, 0.0, 0.0), (0.68, 0.28, 0.05)]:
        kpi = _make_kpi(margen_bruto=mb, nomina_pct=nom, gastos_fin_pct=gf)
        result = calcular_health_score(kpi, None, _CONFIG)
        score = result.por_mes["ENERO 2026"]["score_total"]
        assert 0.0 <= score <= 100.0


# ── categoria thresholds ──────────────────────────────────────────────────────

def test_categoria_saludable_when_score_gte_75():
    # Excellent financials: margen well above benchmark, nomina/gastos well below
    kpi = _make_kpi(
        margen_bruto=0.80,   # 80% vs 68% benchmark → score 100
        nomina_pct=0.20,     # 20% vs 28% benchmark → score 100
        gastos_fin_pct=0.03, # 3% vs 5% benchmark → score 100
        tendencia="creciente",
        variacion_pct=0.10,
    )
    macro = _make_macro(0.1)  # baja presión → score 100
    result = calcular_health_score(kpi, macro, _CONFIG)
    assert result.por_mes["ENERO 2026"]["categoria"] == "saludable"
    assert result.por_mes["ENERO 2026"]["score_total"] >= 75


def test_categoria_critico_when_score_lt_35():
    # Terrible financials
    kpi = _make_kpi(
        margen_bruto=0.20,   # far below benchmark → score 0
        nomina_pct=0.60,     # double the benchmark → score 0
        gastos_fin_pct=0.20, # 4× benchmark → score 0
        tendencia="decreciente",
        variacion_pct=-0.15,
    )
    macro = _make_macro(2.0)  # alta presión → score 0
    result = calcular_health_score(kpi, macro, _CONFIG)
    assert result.por_mes["ENERO 2026"]["categoria"] == "critico"
    assert result.por_mes["ENERO 2026"]["score_total"] < 35


def test_categoria_en_observacion_when_score_55_to_74():
    # At-benchmark financials → margen=80, nomina=80, gastos_fin=80, presion=50, tendencia=50
    # weighted: 80*0.30 + 80*0.25 + 80*0.20 + 50*0.15 + 50*0.10 = 24+20+16+7.5+5 = 72.5
    # Wait that's saludable. Let me pick values that land in 55-74.
    # margen=60, nomina=60, gastos_fin=60, presion=50, tendencia=50
    # weighted: 60*0.30 + 60*0.25 + 60*0.20 + 50*0.15 + 50*0.10 = 18+15+12+7.5+5 = 57.5
    kpi = _make_kpi(
        margen_bruto=0.68 * 0.95,  # slightly below → score 60
        nomina_pct=0.28 * 1.05,    # slightly above → score 60
        gastos_fin_pct=0.05 * 1.05,  # slightly above → score 60
        tendencia="estable",
        variacion_pct=0.0,
    )
    result = calcular_health_score(kpi, None, _CONFIG)
    score = result.por_mes["ENERO 2026"]["score_total"]
    assert 55 <= score < 75
    assert result.por_mes["ENERO 2026"]["categoria"] == "en_observacion"


def test_categoria_en_riesgo_when_score_35_to_54():
    # margen_bruto below 75% of benchmark → score 40
    # nomina at 1.25× benchmark → score 40
    # gastos_fin at 1.25× benchmark → score 40
    # presion=50 (no macro), tendencia=50
    # 40*0.30 + 40*0.25 + 40*0.20 + 50*0.15 + 50*0.10 = 12+10+8+7.5+5 = 42.5
    kpi = _make_kpi(
        margen_bruto=0.68 * 0.77,   # between 75%-90% of benchmark → score 40
        nomina_pct=0.28 * 1.20,     # between 110%-125% of benchmark → score 40
        gastos_fin_pct=0.05 * 1.20, # between 110%-125% of benchmark → score 40
        tendencia="estable",
        variacion_pct=0.0,
    )
    result = calcular_health_score(kpi, None, _CONFIG)
    score = result.por_mes["ENERO 2026"]["score_total"]
    assert 35 <= score < 55
    assert result.por_mes["ENERO 2026"]["categoria"] == "en_riesgo"


# ── dimension identification ──────────────────────────────────────────────────

def test_dimension_mas_debil_has_lowest_score():
    # Force gastos_financieros to have score 0 (far above benchmark)
    kpi = _make_kpi(
        margen_bruto=0.68,       # at benchmark → score 80
        nomina_pct=0.28,         # at benchmark → score 80
        gastos_fin_pct=0.50,     # 10× benchmark → score 0
        tendencia="estable",
    )
    result = calcular_health_score(kpi, None, _CONFIG)
    data = result.por_mes["ENERO 2026"]
    assert data["dimension_mas_debil"] == "gastos_financieros_vs_benchmark"
    assert data["dimensiones"]["gastos_financieros_vs_benchmark"]["score"] == 0


def test_dimension_mas_fuerte_has_highest_score():
    # Force margen_bruto to have score 100 (well above benchmark)
    kpi = _make_kpi(
        margen_bruto=0.68 * 1.15,  # above 1.1× benchmark → score 100
        nomina_pct=0.28,            # at benchmark → score 80
        gastos_fin_pct=0.05,        # at benchmark → score 80
        tendencia="estable",
    )
    result = calcular_health_score(kpi, None, _CONFIG)
    data = result.por_mes["ENERO 2026"]
    assert data["dimension_mas_fuerte"] == "margen_bruto_vs_benchmark"
    assert data["dimensiones"]["margen_bruto_vs_benchmark"]["score"] == 100


# ── macro handling ────────────────────────────────────────────────────────────

def test_presion_inflacionaria_none_macro_gives_score_50():
    kpi = _make_kpi()
    result = calcular_health_score(kpi, None, _CONFIG)
    pi_dim = result.por_mes["ENERO 2026"]["dimensiones"]["presion_inflacionaria"]
    assert pi_dim["score"] == 50
    assert pi_dim["valor_base"] is None


def test_presion_inflacionaria_uses_macro_when_provided():
    kpi = _make_kpi()
    macro_low = _make_macro(0.1)   # ≤ 0.2 → score 100
    macro_high = _make_macro(2.0)  # > 1.6 → score 0
    r_low = calcular_health_score(kpi, macro_low, _CONFIG)
    r_high = calcular_health_score(kpi, macro_high, _CONFIG)
    assert r_low.por_mes["ENERO 2026"]["dimensiones"]["presion_inflacionaria"]["score"] == 100
    assert r_high.por_mes["ENERO 2026"]["dimensiones"]["presion_inflacionaria"]["score"] == 0


# ── tendencia_ingresos handling ───────────────────────────────────────────────

def test_tendencia_ingresos_insuficiente_datos_gives_50():
    kpi = _make_kpi(tendencia="insuficiente_datos", variacion_pct=None)
    result = calcular_health_score(kpi, None, _CONFIG)
    ti = result.por_mes["ENERO 2026"]["dimensiones"]["tendencia_ingresos"]
    assert ti["score"] == 50


def test_tendencia_ingresos_creciente_strong_gives_100():
    kpi = _make_kpi(tendencia="creciente", variacion_pct=0.10)
    result = calcular_health_score(kpi, None, _CONFIG)
    ti = result.por_mes["ENERO 2026"]["dimensiones"]["tendencia_ingresos"]
    assert ti["score"] == 100


def test_tendencia_ingresos_decreciente_strong_gives_10():
    kpi = _make_kpi(tendencia="decreciente", variacion_pct=-0.08)
    result = calcular_health_score(kpi, None, _CONFIG)
    ti = result.por_mes["ENERO 2026"]["dimensiones"]["tendencia_ingresos"]
    assert ti["score"] == 10


# ── config weights ────────────────────────────────────────────────────────────

def test_weights_read_from_config_not_hardcoded():
    kpi = _make_kpi(margen_bruto=0.68 * 1.15)  # margen score = 100
    # Double the margen weight, reduce others proportionally
    config_custom = {
        "benchmarks": _CONFIG["benchmarks"],
        "health_score_weights": {
            "margen_bruto_vs_benchmark": 0.60,
            "nomina_vs_benchmark": 0.10,
            "gastos_financieros_vs_benchmark": 0.10,
            "presion_inflacionaria": 0.10,
            "tendencia_ingresos": 0.10,
        },
    }
    r_default = calcular_health_score(kpi, None, _CONFIG)
    r_custom = calcular_health_score(kpi, None, config_custom)
    # Margen score=100 contributes more under custom config → higher total
    assert (
        r_custom.por_mes["ENERO 2026"]["score_total"]
        > r_default.por_mes["ENERO 2026"]["score_total"]
    )


def test_changing_weights_changes_score_proportionally():
    kpi = _make_kpi(
        margen_bruto=0.68 * 1.15,  # score 100
        nomina_pct=0.28 * 1.60,    # score 0
        gastos_fin_pct=0.05,
        tendencia="estable",
    )
    # Equal weights across all 5 → 0.20 each
    config_equal = {
        "benchmarks": _CONFIG["benchmarks"],
        "health_score_weights": {
            "margen_bruto_vs_benchmark": 0.20,
            "nomina_vs_benchmark": 0.20,
            "gastos_financieros_vs_benchmark": 0.20,
            "presion_inflacionaria": 0.20,
            "tendencia_ingresos": 0.20,
        },
    }
    # Heavy margen weight
    config_margen_heavy = {
        "benchmarks": _CONFIG["benchmarks"],
        "health_score_weights": {
            "margen_bruto_vs_benchmark": 0.80,
            "nomina_vs_benchmark": 0.05,
            "gastos_financieros_vs_benchmark": 0.05,
            "presion_inflacionaria": 0.05,
            "tendencia_ingresos": 0.05,
        },
    }
    r_equal = calcular_health_score(kpi, None, config_equal)
    r_heavy = calcular_health_score(kpi, None, config_margen_heavy)
    # margen score=100, nomina score=0 — heavy margen weight raises total
    assert (
        r_heavy.por_mes["ENERO 2026"]["score_total"]
        > r_equal.por_mes["ENERO 2026"]["score_total"]
    )


# ── tendencia_score ───────────────────────────────────────────────────────────

def test_single_month_tendencia_score_is_insuficiente_datos():
    kpi = _make_kpi(meses=["ENERO 2026"])
    result = calcular_health_score(kpi, None, _CONFIG)
    assert result.tendencia_score["tendencia"] == "insuficiente_datos"


def test_multiple_months_tendencia_score_computed():
    meses = ["ENERO 2026", "FEBRERO 2026", "MARZO 2026"]
    kpi = _make_kpi(
        margen_bruto=0.68,
        nomina_pct=0.28,
        gastos_fin_pct=0.05,
        tendencia="estable",
        meses=meses,
    )
    result = calcular_health_score(kpi, None, _CONFIG)
    ts = result.tendencia_score
    assert len(ts["valores"]) == 3
    assert len(ts["meses"]) == 3
    assert ts["tendencia"] in ("creciente", "decreciente", "estable", "insuficiente_datos")


def test_health_score_report_instance():
    kpi = _make_kpi()
    result = calcular_health_score(kpi, None, _CONFIG)
    assert isinstance(result, HealthScoreReport)
    assert "ENERO 2026" in result.por_mes
    assert "score_total" in result.por_mes["ENERO 2026"]
    assert "dimensiones" in result.por_mes["ENERO 2026"]
