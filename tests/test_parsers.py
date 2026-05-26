import io
import pytest
from pathlib import Path

from src.pipeline.parsers import ParseError
from src.pipeline.parsers.parser_utils import clean_currency, clean_pct, clean_int
from src.pipeline.parsers.parser_bd import parse_bd
from src.pipeline.parsers.parser_er import parse_er

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def bd_path():
    return str(FIXTURES / "sample_bd.csv")


@pytest.fixture
def er_path():
    return str(FIXTURES / "sample_er.csv")


# ── parser_utils ────────────────────────────────────────────────────────────

def test_clean_currency_positive():
    assert clean_currency("$15,000.00") == pytest.approx(15000.0)


def test_clean_currency_negative_parentheses():
    assert clean_currency("($1,234.56)") == pytest.approx(-1234.56)


def test_clean_currency_decimal_fraction():
    assert clean_currency("$0.76") == pytest.approx(0.76)


def test_clean_currency_plain_number():
    assert clean_currency("800.00") == pytest.approx(800.0)


def test_clean_pct_converts_percentage_string():
    assert clean_pct("30.26%") == pytest.approx(0.3026)


def test_clean_pct_zero():
    assert clean_pct("0%") == pytest.approx(0.0)


def test_clean_int_with_commas():
    assert clean_int("1,238") == 1238


def test_clean_int_plain():
    assert clean_int("100") == 100


# ── parse_bd ─────────────────────────────────────────────────────────────────

def test_parse_bd_reads_all_rows(bd_path):
    result = parse_bd(bd_path)
    assert len(result.registros) == 81


def test_parse_bd_currency_to_float(bd_path):
    result = parse_bd(bd_path)
    r = result.registros[0]
    assert isinstance(r["subtotal"], float)
    assert isinstance(r["costo_sin_iva"], float)


def test_parse_bd_margen_stored_as_decimal(bd_path):
    result = parse_bd(bd_path)
    for r in result.registros:
        assert 0.0 < r["margen_bruto"] <= 1.0, f"margen_bruto out of range: {r['margen_bruto']}"


def test_parse_bd_multiplicador_eficiencia(bd_path):
    result = parse_bd(bd_path)
    donburi = next(r for r in result.registros if r["sku"] == "DONBURI")
    expected = donburi["utilidad_bruta"] / donburi["costo_sin_iva"]
    assert donburi["multiplicador_eficiencia"] == pytest.approx(expected, rel=1e-4)
    assert donburi["multiplicador_eficiencia"] == pytest.approx(9.0, rel=1e-4)


def test_parse_bd_skips_zero_cost_rows(tmp_path):
    header = (
        "MES,FECHA VENTA,LÍNEA DE NEGOCIO,SUBCATEGORÍA 1,SUBCATEGORÍA 2,"
        "CANTIDAD,SUBTOTAL,TOTAL,COSTO 1,COSTO TOTAL SIN IVA,COSTO TOTAL DEL SERVICIO,"
        "UTILIDAD BRUTA,MARGEN BRUTO,COL ESPECIAL 1,COL ESPECIAL 2\n"
    )
    valid = "ENERO 2026,,ANT,Alimentos,DONBURI,50,$8000.00,$9280.00,,$800.00,$928.00,$7200.00,$0.90,CALIENTE,CALIENTE\n"
    zero_cost = "ENERO 2026,,ANT,Alimentos,ZERO ITEM,10,$500.00,$580.00,,$0.00,$0.00,$500.00,$1.00,CALIENTE,\n"
    zero_qty = "ENERO 2026,,ANT,Alimentos,ZERO QTY,0,$500.00,$580.00,,$200.00,$232.00,$300.00,$0.60,CALIENTE,\n"
    p = tmp_path / "bd_zeros.csv"
    p.write_text(header + valid + zero_cost + zero_qty, encoding="utf-8")
    result = parse_bd(str(p))
    assert len(result.registros) == 1
    assert result.registros[0]["sku"] == "DONBURI"


def test_parse_bd_sorts_meses_chronologically(bd_path):
    result = parse_bd(bd_path)
    assert result.meses == ["ENERO 2026", "FEBRERO 2026", "MARZO 2026"]


def test_parse_bd_raises_on_missing_file():
    with pytest.raises(ParseError):
        parse_bd("nonexistent_file.csv")


def test_parse_bd_raises_on_missing_columns(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("COL_A,COL_B\nval1,val2\n", encoding="utf-8")
    with pytest.raises(ParseError):
        parse_bd(str(p))


def test_parse_bd_sucursales_sorted(bd_path):
    result = parse_bd(bd_path)
    assert result.sucursales == sorted(result.sucursales)


def test_parse_bd_categorias_present(bd_path):
    result = parse_bd(bd_path)
    assert set(result.categorias) == {"Alimentos", "Bebidas", "Destilados"}


# ── parse_er ─────────────────────────────────────────────────────────────────

def test_parse_er_extracts_nomina(er_path):
    result = parse_er(er_path)
    assert result.gastos_operativos["ENERO 2026"]["nomina"] == pytest.approx(2301832.96)
    assert result.gastos_operativos["FEBRERO 2026"]["nomina"] == pytest.approx(2150000.0)
    assert result.gastos_operativos["MARZO 2026"]["nomina"] == pytest.approx(2400000.0)


def test_parse_er_extracts_gastos_financieros(er_path):
    result = parse_er(er_path)
    assert result.gastos_operativos["ENERO 2026"]["gastos_financieros"] == pytest.approx(691459.78)
    assert result.gastos_operativos["FEBRERO 2026"]["gastos_financieros"] == pytest.approx(685000.0)


def test_parse_er_ignores_ventas_egresos(er_path):
    result = parse_er(er_path)
    expected_keys = {
        "nomina", "gastos_comerciales", "gastos_operativos",
        "gastos_administrativos", "viaticos", "total_gastos_operacion",
        "gastos_financieros", "costo_integral_financiamiento", "impuestos",
    }
    for mes_data in result.gastos_operativos.values():
        assert set(mes_data.keys()) == expected_keys


def test_parse_er_sorts_meses_chronologically(er_path):
    result = parse_er(er_path)
    assert result.meses == ["ENERO 2026", "FEBRERO 2026", "MARZO 2026"]


def test_parse_er_raises_on_missing_file():
    with pytest.raises(ParseError):
        parse_er("nonexistent_er.csv")


def test_parse_er_raises_if_no_kpi_rows(tmp_path):
    content = (
        "Estado de Resultados,,\n"
        ",ENERO 2026,FEBRERO 2026\n"
        "VENTAS,,\n"
        "ANT,$0,$0\n"
    )
    p = tmp_path / "no_kpis.csv"
    p.write_text(content, encoding="utf-8")
    with pytest.raises(ParseError):
        parse_er(str(p))


def test_parse_er_all_months_present(er_path):
    result = parse_er(er_path)
    assert set(result.meses) == {"ENERO 2026", "FEBRERO 2026", "MARZO 2026"}


def test_parse_er_total_gastos_operacion(er_path):
    result = parse_er(er_path)
    assert result.gastos_operativos["ENERO 2026"]["total_gastos_operacion"] == pytest.approx(4031746.30)
