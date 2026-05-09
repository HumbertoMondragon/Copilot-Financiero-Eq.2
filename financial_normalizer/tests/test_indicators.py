"""
Tests for financial_normalizer/indicators.py.
Uses the synthetic fixture data from fixtures.py for deterministic assertions.
"""
import copy
import pytest

from financial_normalizer.indicators import (
    calcular_indicadores_mes,
    calcular_tendencias,
    analizar,
    UMBRAL_MARGEN_BRUTO,
    UMBRAL_EBITDA,
    UMBRAL_MARGEN_NETO,
    UMBRAL_MARGEN_SUCURSAL,
)
from financial_normalizer.tests.fixtures import build_normalized_doc, build_normalized_month
from financial_normalizer.profiles import empty_month


# ── Shared helpers ────────────────────────────────────────────────────────────

def _scaled_month(mes_data: dict, factor: float) -> dict:
    """Return a deep copy of mes_data with all monetary values multiplied by factor."""
    m = copy.deepcopy(mes_data)
    ratio_keys = {"margen_bruto", "margen_costo", "margen_operacion",
                  "margen_ebitda", "margen_neto"}
    for k in m["kpis"]:
        if k not in ratio_keys:
            m["kpis"][k] = round(m["kpis"][k] * factor, 2)
    for section in ("ventas", "egresos"):
        for grp_data in m[section].values():
            for k in list(grp_data):
                grp_data[k] = round(grp_data[k] * factor, 2)
    return m


def _low_margin_mes() -> dict:
    """Month with margins below every threshold to trigger all alerts."""
    mes = empty_month()
    mes["kpis"]["total_ventas"] = 1_000_000.0
    mes["kpis"]["margen_bruto"] = 0.30    # < UMBRAL_MARGEN_BRUTO (0.40)
    mes["kpis"]["margen_ebitda"] = 0.04   # < UMBRAL_EBITDA (0.10)
    mes["kpis"]["margen_neto"] = 0.02     # < UMBRAL_MARGEN_NETO (0.05)
    mes["ventas"]["A"]["total"] = 500_000.0
    mes["egresos"]["A"]["total"] = 400_000.0  # sucursal A margen = 0.20 < 0.40
    return mes


# ── calcular_indicadores_mes ──────────────────────────────────────────────────

class TestCalcularIndicadoresMes:

    @pytest.fixture
    def result(self):
        return calcular_indicadores_mes(build_normalized_month(), "ENERO 2026")

    # --- Structure ---

    def test_top_level_keys(self, result):
        for key in ("mes", "rentabilidad", "estructura_costos",
                    "sucursales", "ranking_sucursales", "alertas"):
            assert key in result

    def test_mes_nombre(self, result):
        assert result["mes"] == "ENERO 2026"

    def test_rentabilidad_keys(self, result):
        r = result["rentabilidad"]
        for key in ("margen_bruto", "margen_ebitda", "margen_neto",
                    "alerta_margen_bruto", "alerta_ebitda", "alerta_neto"):
            assert key in r

    def test_estructura_costos_keys(self, result):
        ec = result["estructura_costos"]
        for key in ("costo_sobre_ventas", "nomina_sobre_ventas",
                    "gastos_op_sobre_ventas", "categoria_mayor_egreso",
                    "categoria_menor_egreso"):
            assert key in ec

    def test_sucursales_all_groups(self, result):
        assert set(result["sucursales"].keys()) == {"A", "B", "C", "D", "E"}

    def test_sucursal_keys(self, result):
        s = result["sucursales"]["A"]
        for key in ("venta", "egreso", "utilidad_bruta", "margen",
                    "participacion_ventas", "alerta_margen"):
            assert key in s

    # --- Values ---

    def test_rentabilidad_values_match_fixture(self, result):
        from financial_normalizer.tests.fixtures import MARGEN_BRUTO, MARGEN_EBITDA, MARGEN_NETO
        r = result["rentabilidad"]
        assert r["margen_bruto"] == pytest.approx(MARGEN_BRUTO, rel=1e-3)
        assert r["margen_ebitda"] == pytest.approx(MARGEN_EBITDA, rel=1e-3)
        assert r["margen_neto"] == pytest.approx(MARGEN_NETO, rel=1e-3)

    def test_sucursal_venta_matches_fixture(self, result):
        from financial_normalizer.tests.fixtures import VENTAS
        for grp in "ABCDE":
            assert result["sucursales"][grp]["venta"] == pytest.approx(VENTAS[grp]["total"])

    def test_sucursal_utilidad_bruta(self, result):
        for grp in "ABCDE":
            s = result["sucursales"][grp]
            assert s["utilidad_bruta"] == pytest.approx(s["venta"] - s["egreso"])

    def test_participacion_ventas_sums_to_one(self, result):
        total_part = sum(result["sucursales"][g]["participacion_ventas"] for g in "ABCDE")
        assert total_part == pytest.approx(1.0, abs=0.001)

    def test_categoria_mayor_egreso(self, result):
        assert result["estructura_costos"]["categoria_mayor_egreso"] == "Alimentos"

    def test_categoria_menor_egreso(self, result):
        assert result["estructura_costos"]["categoria_menor_egreso"] == "Vinos"

    # --- Ranking ---

    def test_ranking_contains_all_groups(self, result):
        assert set(result["ranking_sucursales"]) == {"A", "B", "C", "D", "E"}

    def test_ranking_sorted_descending(self, result):
        ranking = result["ranking_sucursales"]
        margenes = [result["sucursales"][g]["margen"] for g in ranking]
        assert margenes == sorted(margenes, reverse=True)

    def test_ranking_fixture_order(self, result):
        assert result["ranking_sucursales"] == ["D", "E", "C", "B", "A"]

    # --- Alerts: healthy fixture → no alerts ---

    def test_no_global_alerts_with_healthy_data(self, result):
        r = result["rentabilidad"]
        assert not r["alerta_margen_bruto"]
        assert not r["alerta_ebitda"]
        assert not r["alerta_neto"]

    def test_no_sucursal_alerts_with_healthy_data(self, result):
        for grp in "ABCDE":
            assert not result["sucursales"][grp]["alerta_margen"]

    def test_zero_alertas_with_healthy_data(self, result):
        assert result["alertas"] == []

    # --- Alerts: low-margin month → alerts fire ---

    def test_global_alerts_fire_below_threshold(self):
        result = calcular_indicadores_mes(_low_margin_mes(), "TEST 2026")
        r = result["rentabilidad"]
        assert r["alerta_margen_bruto"]
        assert r["alerta_ebitda"]
        assert r["alerta_neto"]

    def test_sucursal_alert_fires_below_threshold(self):
        result = calcular_indicadores_mes(_low_margin_mes(), "TEST 2026")
        assert result["sucursales"]["A"]["alerta_margen"]

    def test_alert_tipos_present(self):
        result = calcular_indicadores_mes(_low_margin_mes(), "TEST 2026")
        tipos = {a["tipo"] for a in result["alertas"]}
        assert "margen_bruto" in tipos
        assert "ebitda" in tipos
        assert "margen_neto" in tipos
        assert "margen_sucursal" in tipos

    def test_alert_structure(self):
        result = calcular_indicadores_mes(_low_margin_mes(), "TEST 2026")
        for alert in result["alertas"]:
            assert "tipo" in alert
            assert "severidad" in alert
            assert "descripcion" in alert
            assert "valor" in alert
            assert "umbral" in alert
            assert alert["severidad"] in ("alta", "media", "baja")
            assert isinstance(alert["descripcion"], str)
            assert len(alert["descripcion"]) > 0

    def test_alert_severidad_alta_for_zero_margin(self):
        mes = empty_month()
        mes["kpis"]["total_ventas"] = 1_000_000.0
        mes["kpis"]["margen_bruto"] = 0.0     # 0/0.40 < 0.5 → alta
        mes["kpis"]["margen_ebitda"] = 0.0
        mes["kpis"]["margen_neto"] = 0.0
        result = calcular_indicadores_mes(mes, "TEST 2026")
        mb_alert = next(a for a in result["alertas"] if a["tipo"] == "margen_bruto")
        assert mb_alert["severidad"] == "alta"

    def test_alert_severidad_baja_for_near_threshold(self):
        mes = empty_month()
        mes["kpis"]["total_ventas"] = 1_000_000.0
        mes["kpis"]["margen_bruto"] = 0.38    # 0.38/0.40 = 0.95 ≥ 0.75 → baja
        mes["kpis"]["margen_ebitda"] = 0.50
        mes["kpis"]["margen_neto"] = 0.50
        result = calcular_indicadores_mes(mes, "TEST 2026")
        mb_alert = next((a for a in result["alertas"] if a["tipo"] == "margen_bruto"), None)
        assert mb_alert is not None
        assert mb_alert["severidad"] == "baja"

    # --- Zero total_ventas ---

    def test_zero_ventas_no_exception(self):
        result = calcular_indicadores_mes(empty_month(), "ENERO 2026")
        assert result is not None

    def test_zero_ventas_ratios_are_zero(self):
        result = calcular_indicadores_mes(empty_month(), "ENERO 2026")
        assert result["estructura_costos"]["costo_sobre_ventas"] == 0.0
        assert result["estructura_costos"]["nomina_sobre_ventas"] == 0.0
        for grp in "ABCDE":
            assert result["sucursales"][grp]["margen"] == 0.0
            assert result["sucursales"][grp]["participacion_ventas"] == 0.0


# ── calcular_tendencias ───────────────────────────────────────────────────────

class TestCalcularTendencias:

    def test_one_month_insuficiente_datos(self):
        result = calcular_tendencias(build_normalized_doc()["meses"])
        assert result["ventas"]["tendencia"] == "insuficiente_datos"
        assert result["ebitda"]["tendencia"] == "insuficiente_datos"
        assert result["margen_neto"]["tendencia"] == "insuficiente_datos"

    def test_one_month_variacion_is_none(self):
        result = calcular_tendencias(build_normalized_doc()["meses"])
        assert result["ventas"]["variacion_pct_ultimo_mes"] is None

    def test_one_month_meses_con_datos(self):
        result = calcular_tendencias(build_normalized_doc()["meses"])
        assert result["meses_con_datos"] == ["ENERO 2026"]

    def test_one_month_valores_list(self):
        from financial_normalizer.tests.fixtures import TOTAL_VENTAS
        result = calcular_tendencias(build_normalized_doc()["meses"])
        assert result["ventas"]["valores"] == [TOTAL_VENTAS]

    def test_two_months_growing(self):
        base = build_normalized_month()
        meses = {
            "ENERO 2026": base,
            "FEBRERO 2026": _scaled_month(base, 1.15),
        }
        result = calcular_tendencias(meses)
        assert result["ventas"]["tendencia"] == "creciente"

    def test_two_months_declining(self):
        base = build_normalized_month()
        meses = {
            "ENERO 2026": base,
            "FEBRERO 2026": _scaled_month(base, 0.80),
        }
        result = calcular_tendencias(meses)
        assert result["ventas"]["tendencia"] == "decreciente"

    def test_two_months_estable(self):
        base = build_normalized_month()
        meses = {
            "ENERO 2026": base,
            "FEBRERO 2026": _scaled_month(base, 1.02),  # 2% change → estable
        }
        result = calcular_tendencias(meses)
        assert result["ventas"]["tendencia"] == "estable"

    def test_variacion_pct_correct(self):
        base = build_normalized_month()
        meses = {
            "ENERO 2026": base,
            "FEBRERO 2026": _scaled_month(base, 1.10),
        }
        result = calcular_tendencias(meses)
        assert result["ventas"]["variacion_pct_ultimo_mes"] == pytest.approx(0.10, rel=1e-2)

    def test_months_sorted_chronologically(self):
        base = build_normalized_month()
        # Insert in reverse order to verify sorting
        meses = {
            "MARZO 2026": _scaled_month(base, 1.20),
            "ENERO 2026": base,
            "FEBRERO 2026": _scaled_month(base, 1.10),
        }
        result = calcular_tendencias(meses)
        assert result["meses_con_datos"] == ["ENERO 2026", "FEBRERO 2026", "MARZO 2026"]

    def test_empty_months_excluded(self):
        meses = {
            "ENERO 2026": build_normalized_month(),
            "FEBRERO 2026": empty_month(),  # total_ventas = 0 → excluded
        }
        result = calcular_tendencias(meses)
        assert result["meses_con_datos"] == ["ENERO 2026"]
        assert result["ventas"]["tendencia"] == "insuficiente_datos"

    def test_sucursales_all_groups_present(self):
        result = calcular_tendencias(build_normalized_doc()["meses"])
        assert set(result["sucursales"].keys()) == {"A", "B", "C", "D", "E"}

    def test_sucursal_tendencia_key_present(self):
        result = calcular_tendencias(build_normalized_doc()["meses"])
        for grp in "ABCDE":
            assert "tendencia_margen" in result["sucursales"][grp]
            assert "ventas" in result["sucursales"][grp]
            assert "margen" in result["sucursales"][grp]


# ── analizar ──────────────────────────────────────────────────────────────────

class TestAnalizar:

    @pytest.fixture
    def result(self):
        return analizar(build_normalized_doc())

    def test_top_level_keys(self, result):
        for key in ("cliente_id", "periodo", "por_mes", "tendencias", "resumen_ejecutivo"):
            assert key in result

    def test_cliente_id_propagated(self, result):
        assert result["cliente_id"] == "test_client"

    def test_periodo_propagated(self, result):
        assert result["periodo"] == "2026"

    def test_por_mes_contains_month(self, result):
        assert "ENERO 2026" in result["por_mes"]

    def test_resumen_ejecutivo_keys(self, result):
        re = result["resumen_ejecutivo"]
        for key in ("meses_analizados", "mejor_mes_ebitda", "peor_mes_ebitda",
                    "mejor_sucursal_promedio", "peor_sucursal_promedio",
                    "total_alertas_activas"):
            assert key in re

    def test_meses_analizados(self, result):
        assert result["resumen_ejecutivo"]["meses_analizados"] == 1

    def test_zero_alertas_healthy_data(self, result):
        assert result["resumen_ejecutivo"]["total_alertas_activas"] == 0

    def test_mejor_sucursal_is_d(self, result):
        assert result["resumen_ejecutivo"]["mejor_sucursal_promedio"] == "D"

    def test_peor_sucursal_is_a(self, result):
        assert result["resumen_ejecutivo"]["peor_sucursal_promedio"] == "A"

    def test_mejor_y_peor_mes_ebitda_same_when_one_month(self, result):
        re = result["resumen_ejecutivo"]
        assert re["mejor_mes_ebitda"] == "ENERO 2026"
        assert re["peor_mes_ebitda"] == "ENERO 2026"

    def test_zero_ventas_month_excluded_from_por_mes(self):
        doc = build_normalized_doc()
        doc["meses"]["FEBRERO 2026"] = empty_month()
        result = analizar(doc)
        assert "ENERO 2026" in result["por_mes"]
        assert "FEBRERO 2026" not in result["por_mes"]
        assert result["resumen_ejecutivo"]["meses_analizados"] == 1

    def test_alertas_counted_correctly(self):
        doc = build_normalized_doc()
        doc["meses"]["ENERO 2026"] = _low_margin_mes()
        result = analizar(doc)
        assert result["resumen_ejecutivo"]["total_alertas_activas"] > 0
