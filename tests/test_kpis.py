import json
import pytest
from pathlib import Path

from src.pipeline.parsers.parser_bd import parse_bd
from src.pipeline.parsers.parser_er import parse_er
from src.pipeline.integrator import integrate, FinancialData
from src.pipeline.kpis import calcular_kpis, KPIReport, _get_estado, _calc_tendencia

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG_PATH = Path(__file__).parent.parent / "configs" / "nama.json"

# Fixture revenue values (3 sucursales × 9 SKUs):
# total per month = 178800.0,  costo = 62820.0,  utilidad = 115980.0
# costo_directo_pct ≈ 0.35134


@pytest.fixture
def nama_config():
    return json.loads(CONFIG_PATH.read_text())


@pytest.fixture
def fd():
    bd = parse_bd(str(FIXTURES / "sample_bd.csv"))
    er = parse_er(str(FIXTURES / "sample_er.csv"))
    return integrate(bd, er)


@pytest.fixture
def kpi_report(fd, nama_config):
    return calcular_kpis(fd, nama_config)


# ── core KPI formulas ─────────────────────────────────────────────────────────

def test_ebitda_formula(kpi_report):
    for mes, md in kpi_report.por_mes.items():
        c = md["consolidado"]
        assert c["ebitda"] == pytest.approx(c["utilidad_bruta"] - c["total_gastos_operacion"])


def test_utilidad_neta_formula(kpi_report):
    for mes, md in kpi_report.por_mes.items():
        c = md["consolidado"]
        expected = c["ebitda"] - c["gastos_financieros"] - 0.0  # impuestos = 0 in fixture
        assert c["utilidad_neta"] == pytest.approx(expected)


def test_margen_bruto_equals_utilidad_over_revenue(kpi_report):
    for mes, md in kpi_report.por_mes.items():
        c = md["consolidado"]
        assert c["margen_bruto"] == pytest.approx(c["utilidad_bruta"] / c["total_revenue"])


# ── participacion revenue ─────────────────────────────────────────────────────

def test_participacion_revenue_sums_to_one(kpi_report):
    for mes, md in kpi_report.por_mes.items():
        total = sum(s["participacion_revenue"] for s in md["por_sucursal"].values())
        assert total == pytest.approx(1.0, abs=1e-9)


# ── vs_benchmark estados ──────────────────────────────────────────────────────

def test_vs_benchmark_en_rango(fd):
    # costo_directo_pct ≈ 0.3514 — set benchmark to 0.37 so excess ≈ -4.8% (better) → en_rango
    config = _make_config(costo_directo_pct=0.37)
    result = calcular_kpis(fd, config)
    estado = result.por_mes[result.meses_analizados[0]]["vs_benchmark"]["costo_directo_pct"]["estado"]
    assert estado == "en_rango"


def test_vs_benchmark_en_rango_within_5pct(fd):
    # costo_directo_pct ≈ 0.3514, benchmark = 0.34 → excess ≈ 3.4% → still en_rango
    config = _make_config(costo_directo_pct=0.34)
    result = calcular_kpis(fd, config)
    estado = result.por_mes[result.meses_analizados[0]]["vs_benchmark"]["costo_directo_pct"]["estado"]
    assert estado == "en_rango"


def test_vs_benchmark_alerta(fd):
    # costo_directo_pct ≈ 0.3514, benchmark = 0.33 → excess ≈ 6.5% → alerta
    config = _make_config(costo_directo_pct=0.33)
    result = calcular_kpis(fd, config)
    estado = result.por_mes[result.meses_analizados[0]]["vs_benchmark"]["costo_directo_pct"]["estado"]
    assert estado == "alerta"


def test_vs_benchmark_critico(fd):
    # costo_directo_pct ≈ 0.3514, benchmark = 0.28 → excess ≈ 25.5% → critico
    config = _make_config(costo_directo_pct=0.28)
    result = calcular_kpis(fd, config)
    estado = result.por_mes[result.meses_analizados[0]]["vs_benchmark"]["costo_directo_pct"]["estado"]
    assert estado == "critico"


def test_get_estado_lower_is_better_direct():
    assert _get_estado(0.30, 0.32, True) == "en_rango"   # better than benchmark
    assert _get_estado(0.34, 0.32, True) == "alerta"     # ~6% worse
    assert _get_estado(0.40, 0.32, True) == "critico"    # 25% worse


def test_get_estado_higher_is_better_direct():
    assert _get_estado(0.70, 0.68, False) == "en_rango"  # above benchmark
    assert _get_estado(0.60, 0.68, False) == "alerta"    # ~12% shortfall
    assert _get_estado(0.50, 0.68, False) == "critico"   # ~26% shortfall


# ── efficiency ranking ────────────────────────────────────────────────────────

def test_efficiency_ranking_sorted_desc(kpi_report):
    for mes, md in kpi_report.por_mes.items():
        multipliers = [r["multiplicador_eficiencia"] for r in md["efficiency_ranking"]]
        assert multipliers == sorted(multipliers, reverse=True)


def test_efficiency_ranking_donburi_first(kpi_report):
    first_mes = kpi_report.meses_analizados[0]
    top = kpi_report.por_mes[first_mes]["efficiency_ranking"][0]
    assert top["sku"] == "DONBURI"
    assert top["multiplicador_eficiencia"] == pytest.approx(9.0, rel=1e-4)


# ── tendencias ────────────────────────────────────────────────────────────────

def test_tendencia_insuficiente_datos_single_month():
    fd = _make_fd([100000.0])
    config = _make_config()
    result = calcular_kpis(fd, config)
    assert result.tendencias["revenue"]["tendencia"] == "insuficiente_datos"
    assert result.tendencias["revenue"]["variacion_pct"] is None


def test_tendencia_creciente():
    fd = _make_fd([100000.0, 105000.0, 112000.0])
    config = _make_config()
    result = calcular_kpis(fd, config)
    assert result.tendencias["revenue"]["tendencia"] == "creciente"
    assert result.tendencias["revenue"]["variacion_pct"] > 0.05


def test_tendencia_decreciente():
    fd = _make_fd([100000.0, 95000.0, 88000.0])
    config = _make_config()
    result = calcular_kpis(fd, config)
    assert result.tendencias["revenue"]["tendencia"] == "decreciente"
    assert result.tendencias["revenue"]["variacion_pct"] < -0.05


def test_tendencia_estable():
    fd = _make_fd([100000.0, 101000.0, 102000.0])
    config = _make_config()
    result = calcular_kpis(fd, config)
    assert result.tendencias["revenue"]["tendencia"] == "estable"


def test_calc_tendencia_direct():
    t = _calc_tendencia([100.0, 115.0], ["ENERO 2026", "FEBRERO 2026"])
    assert t["tendencia"] == "creciente"
    assert t["variacion_pct"] == pytest.approx(0.15)


# ── alertas ───────────────────────────────────────────────────────────────────

def test_alertas_fire_for_kpis_worse_than_benchmark(kpi_report):
    # With nama_config, fixture nomina_pct >> 0.28 → must have at least one alert
    first_mes = kpi_report.meses_analizados[0]
    alertas = kpi_report.por_mes[first_mes]["alertas"]
    assert len(alertas) > 0
    tipos = {a["tipo"] for a in alertas}
    assert "nomina_alta" in tipos  # nomina is massively over benchmark in small fixture


def test_alertas_empty_when_all_benchmarks_generous(fd):
    config = _make_config(
        costo_directo_pct=0.99, margen_bruto=0.0, nomina_pct=99.0,
        gastos_op_pct=99.0, gastos_financieros_pct=99.0, margen_neto=-99.0,
    )
    result = calcular_kpis(fd, config)
    for mes, md in result.por_mes.items():
        kpi_alertas = [a for a in md["alertas"] if a["entidad"] is None]
        assert len(kpi_alertas) == 0


# ── skus_bajo_rendimiento ─────────────────────────────────────────────────────

def test_skus_bajo_rendimiento_below_benchmark_only(kpi_report):
    bench = kpi_report.por_mes[kpi_report.meses_analizados[0]]["vs_benchmark"]["margen_bruto"]["benchmark"]
    for mes, md in kpi_report.por_mes.items():
        for sku in md["skus_bajo_rendimiento"]:
            assert sku["margen_bruto"] < bench


def test_skus_bajo_rendimiento_count(kpi_report):
    # 4 SKU types below 0.68 benchmark × 3 sucursales = 12 per month
    first_mes = kpi_report.meses_analizados[0]
    assert len(kpi_report.por_mes[first_mes]["skus_bajo_rendimiento"]) == 12


# ── resumen ejecutivo ─────────────────────────────────────────────────────────

def test_resumen_ejecutivo_fields(kpi_report):
    r = kpi_report.resumen_ejecutivo
    for key in ("mejor_sucursal_margen", "peor_sucursal_margen", "mejor_categoria_margen",
                "sku_top_multiplicador", "sku_top_revenue", "skus_bajo_rendimiento_count",
                "kpis_en_alerta", "total_alertas"):
        assert key in r


def test_resumen_sku_top_multiplicador(kpi_report):
    assert kpi_report.resumen_ejecutivo["sku_top_multiplicador"] == "DONBURI"


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_config(**overrides) -> dict:
    defaults = {
        "costo_directo_pct": 0.32, "margen_bruto": 0.68, "nomina_pct": 0.28,
        "gastos_op_pct": 0.38, "gastos_financieros_pct": 0.05, "margen_neto": 0.10,
    }
    defaults.update(overrides)
    return {"benchmarks": defaults}


def _make_fd(revenues: list) -> FinancialData:
    """Build a minimal FinancialData for tendencia testing."""
    month_names = ["ENERO 2026", "FEBRERO 2026", "MARZO 2026", "ABRIL 2026"]
    meses = month_names[: len(revenues)]
    por_mes = {}
    for mes, rev in zip(meses, revenues):
        por_mes[mes] = {
            "total_revenue": rev,
            "total_costo_directo": rev * 0.30,
            "utilidad_bruta_bd": rev * 0.70,
            "por_sucursal": {
                "ANT": {
                    "revenue": rev,
                    "costo_directo": rev * 0.30,
                    "utilidad_bruta": rev * 0.70,
                    "margen_bruto": 0.70,
                    "por_categoria": {},
                }
            },
            "por_sku": [],
            "gastos_operativos": {
                "nomina": rev * 0.20,
                "gastos_comerciales": 0.0,
                "gastos_operativos": 0.0,
                "gastos_administrativos": 0.0,
                "viaticos": 0.0,
                "total_gastos_operacion": rev * 0.30,
                "gastos_financieros": rev * 0.05,
                "costo_integral_financiamiento": rev * 0.05,
                "impuestos": 0.0,
            },
        }
    return FinancialData(meses=meses, por_mes=por_mes)
