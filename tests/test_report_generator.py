import pytest
from src.pipeline.kpis import KPIReport
from src.pipeline.health_score import HealthScoreReport
from src.pipeline.report_generator import generar_reporte


def _make_kpi() -> KPIReport:
    return KPIReport(
        meses_analizados=["ENERO 2026"],
        por_mes={
            "ENERO 2026": {
                "consolidado": {
                    "total_revenue": 8_790_000.0,
                    "total_costo_directo": 2_637_000.0,
                    "utilidad_bruta": 6_153_000.0,
                    "margen_bruto": 0.70,
                    "nomina": 2_373_300.0,
                    "gastos_financieros": 703_200.0,
                    "total_gastos_operacion": 3_781_700.0,
                    "ebitda": 2_371_300.0,
                    "margen_ebitda": 0.27,
                    "utilidad_neta": 1_668_100.0,
                    "margen_neto": 0.19,
                    "costo_directo_pct": 0.30,
                    "nomina_pct": 0.27,
                    "gastos_op_pct": 0.43,
                    "gastos_financieros_pct": 0.08,
                },
                "vs_benchmark": {
                    "margen_bruto": {"valor": 0.70, "benchmark": 0.68, "diferencia": 0.02, "estado": "en_rango"},
                    "nomina_pct": {"valor": 0.27, "benchmark": 0.28, "diferencia": -0.01, "estado": "en_rango"},
                    "gastos_financieros_pct": {"valor": 0.08, "benchmark": 0.05, "diferencia": 0.03, "estado": "alerta"},
                },
                "efficiency_ranking": [],
                "skus_bajo_rendimiento": [],
            }
        },
        tendencias={},
        resumen_ejecutivo={},
    )


def _make_hs() -> HealthScoreReport:
    return HealthScoreReport(
        por_mes={
            "ENERO 2026": {
                "score_total": 62.0,
                "categoria": "en_observacion",
                "dimensiones": {
                    "margen_bruto_vs_benchmark": {"score": 80, "peso": 0.30, "valor_base": 0.70, "benchmark": 0.68, "contribucion": 24.0},
                    "nomina_vs_benchmark": {"score": 80, "peso": 0.25, "valor_base": 0.27, "benchmark": 0.28, "contribucion": 20.0},
                    "gastos_financieros_vs_benchmark": {"score": 20, "peso": 0.20, "valor_base": 0.08, "benchmark": 0.05, "contribucion": 4.0},
                    "presion_inflacionaria": {"score": 70, "peso": 0.15, "valor_base": 0.4, "benchmark": None, "contribucion": 10.5},
                    "tendencia_ingresos": {"score": 50, "peso": 0.10, "valor_base": "estable", "benchmark": None, "contribucion": 5.0},
                },
                "score_total_verificacion": 63.5,
                "dimension_mas_debil": "gastos_financieros_vs_benchmark",
                "dimension_mas_fuerte": "margen_bruto_vs_benchmark",
            }
        },
        tendencia_score={"valores": [62.0], "meses": ["ENERO 2026"], "tendencia": "insuficiente_datos"},
    )


# ── basic output ──────────────────────────────────────────────────────────────

def test_generar_reporte_returns_bytes():
    result = generar_reporte(_make_kpi(), _make_hs())
    assert isinstance(result, bytes)


def test_generar_reporte_nonempty():
    result = generar_reporte(_make_kpi(), _make_hs())
    assert len(result) > 1000


def test_pdf_starts_with_pdf_magic_bytes():
    result = generar_reporte(_make_kpi(), _make_hs())
    assert result[:4] == b"%PDF"


# ── optional sections ─────────────────────────────────────────────────────────

def test_generar_sin_opcionales_no_raises():
    result = generar_reporte(
        _make_kpi(), _make_hs(),
        macro_indices=None,
        shap_narrative=None,
        forecast_result=None,
        scenario_result=None,
        copilot_report=None,
    )
    assert len(result) > 500


def test_generar_con_scenario_result_larger():
    from src.pipeline.scenario import ScenarioConfig, simular_escenario
    kpi = _make_kpi()
    config = ScenarioConfig(variaciones={"revenue": 0.05}, n_simulaciones=500, semilla=42)
    sr = simular_escenario(kpi, config, {"margen_bruto": 0.68, "nomina_pct": 0.28,
                                          "gastos_financieros_pct": 0.05, "margen_neto": 0.10})
    sin_sc = generar_reporte(_make_kpi(), _make_hs())
    con_sc = generar_reporte(_make_kpi(), _make_hs(), scenario_result=sr)
    assert len(con_sc) > len(sin_sc)


def test_generar_con_cliente_id():
    result = generar_reporte(_make_kpi(), _make_hs(), cliente_id="nama")
    assert isinstance(result, bytes) and len(result) > 500
