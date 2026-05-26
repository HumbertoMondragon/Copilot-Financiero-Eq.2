import pytest
from pathlib import Path

from src.pipeline.parsers.parser_bd import BDData, parse_bd
from src.pipeline.parsers.parser_er import ERData, parse_er
from src.pipeline.integrator import integrate, FinancialData

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def bd(tmp_path):
    return parse_bd(str(FIXTURES / "sample_bd.csv"))


@pytest.fixture
def er(tmp_path):
    return parse_er(str(FIXTURES / "sample_er.csv"))


@pytest.fixture
def fd(bd, er):
    return integrate(bd, er)


# ── month intersection ────────────────────────────────────────────────────────

def test_integrate_only_common_months():
    """Months present only in BD (not ER) must be excluded."""
    bd = BDData(
        meses=["ENERO 2026", "FEBRERO 2026", "MARZO 2026"],
        sucursales=["ANT"],
        categorias=["Alimentos"],
        registros=[
            _make_registro("ENERO 2026"), _make_registro("FEBRERO 2026"), _make_registro("MARZO 2026"),
        ],
    )
    er = ERData(
        meses=["ENERO 2026", "FEBRERO 2026"],
        gastos_operativos={
            "ENERO 2026": _make_gastos(),
            "FEBRERO 2026": _make_gastos(),
        },
    )
    result = integrate(bd, er)
    assert result.meses == ["ENERO 2026", "FEBRERO 2026"]
    assert "MARZO 2026" not in result.por_mes


def test_integrate_month_only_in_er_excluded():
    bd = BDData(
        meses=["ENERO 2026"],
        sucursales=["ANT"],
        categorias=["Alimentos"],
        registros=[_make_registro("ENERO 2026")],
    )
    er = ERData(
        meses=["ENERO 2026", "FEBRERO 2026"],
        gastos_operativos={
            "ENERO 2026": _make_gastos(),
            "FEBRERO 2026": _make_gastos(),
        },
    )
    result = integrate(bd, er)
    assert result.meses == ["ENERO 2026"]
    assert "FEBRERO 2026" not in result.por_mes


# ── por_sku ───────────────────────────────────────────────────────────────────

def test_integrate_por_sku_count(fd, bd):
    """por_sku must contain every non-zero-cost record for that month."""
    for mes in fd.meses:
        expected = sum(1 for r in bd.registros if r["mes"] == mes)
        assert len(fd.por_mes[mes]["por_sku"]) == expected


def test_integrate_multiplicador_preserved(fd):
    """multiplicador_eficiencia from BD must survive into por_sku."""
    for mes in fd.meses:
        donburi = next((r for r in fd.por_mes[mes]["por_sku"] if r["sku"] == "DONBURI"), None)
        assert donburi is not None
        assert donburi["multiplicador_eficiencia"] == pytest.approx(9.0, rel=1e-4)


# ── revenue aggregation ───────────────────────────────────────────────────────

def test_integrate_revenue_aggregated_by_sucursal(fd, bd):
    """por_sucursal revenue must equal sum of subtotals for that sucursal/month."""
    for mes in fd.meses:
        for suc in fd.por_mes[mes]["por_sucursal"]:
            expected = sum(
                r["subtotal"] for r in bd.registros
                if r["mes"] == mes and r["sucursal"] == suc
            )
            assert fd.por_mes[mes]["por_sucursal"][suc]["revenue"] == pytest.approx(expected)


def test_integrate_total_revenue_is_sum_of_sucursales(fd):
    for mes in fd.meses:
        md = fd.por_mes[mes]
        suc_sum = sum(s["revenue"] for s in md["por_sucursal"].values())
        assert md["total_revenue"] == pytest.approx(suc_sum)


# ── gastos operativos ─────────────────────────────────────────────────────────

def test_integrate_gastos_operativos_from_er(fd, er):
    for mes in fd.meses:
        assert fd.por_mes[mes]["gastos_operativos"] == er.gastos_operativos[mes]


# ── derived fields ────────────────────────────────────────────────────────────

def test_integrate_margen_bruto_per_sucursal(fd):
    for mes in fd.meses:
        for sdata in fd.por_mes[mes]["por_sucursal"].values():
            rev = sdata["revenue"]
            expected_margen = sdata["utilidad_bruta"] / rev if rev else 0.0
            assert sdata["margen_bruto"] == pytest.approx(expected_margen, rel=1e-6)


def test_integrate_categoria_revenue_sums_to_sucursal(fd):
    for mes in fd.meses:
        for suc, sdata in fd.por_mes[mes]["por_sucursal"].items():
            cat_sum = sum(c["revenue"] for c in sdata["por_categoria"].values())
            assert sdata["revenue"] == pytest.approx(cat_sum)


def test_integrate_meses_chronological(fd):
    assert fd.meses == ["ENERO 2026", "FEBRERO 2026", "MARZO 2026"]


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_registro(mes: str) -> dict:
    return {
        "mes": mes, "sucursal": "ANT", "categoria": "Alimentos", "sku": "TEST",
        "cantidad": 10, "subtotal": 1000.0, "total": 1160.0,
        "costo_sin_iva": 300.0, "costo_con_iva": 348.0,
        "utilidad_bruta": 700.0, "margen_bruto": 0.70,
        "multiplicador_eficiencia": 2.333, "tag_menu_1": "", "tag_menu_2": "",
    }


def _make_gastos() -> dict:
    return {
        "nomina": 500000.0, "gastos_comerciales": 20000.0,
        "gastos_operativos": 100000.0, "gastos_administrativos": 30000.0,
        "viaticos": 10000.0, "total_gastos_operacion": 660000.0,
        "gastos_financieros": 50000.0, "costo_integral_financiamiento": 50000.0,
        "impuestos": 0.0,
    }
