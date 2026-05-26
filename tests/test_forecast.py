import pytest
from pathlib import Path

from src.pipeline.kpis import KPIReport
from src.pipeline.forecast import forecast_revenue, ForecastResult
from src.ml.predictor import PredictionReport
from src.pipeline.shap_translator import (
    translate_shap,
    get_magnitud,
    get_direccion,
    SHAPNarrative,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_kpi_report(revenue_values, meses=None, sucursales=None):
    """Build a minimal KPIReport with the given revenue series."""
    if meses is None:
        base = ["ENERO 2026", "FEBRERO 2026", "MARZO 2026", "ABRIL 2026",
                "MAYO 2026", "JUNIO 2026", "JULIO 2026", "AGOSTO 2026",
                "SEPTIEMBRE 2026", "OCTUBRE 2026", "NOVIEMBRE 2026", "DICIEMBRE 2026"]
        meses = base[: len(revenue_values)]

    tendencias: dict = {
        "revenue": {"valores": list(revenue_values), "meses": meses},
    }

    if sucursales:
        por_suc = {}
        for suc, vals in sucursales.items():
            por_suc[suc] = {"revenue": {"valores": vals, "meses": meses[: len(vals)]}}
        tendencias["por_sucursal"] = por_suc

    return KPIReport(
        meses_analizados=meses,
        por_mes={},
        tendencias=tendencias,
        resumen_ejecutivo={},
    )


def _make_prediction_report(shap_values_per_row=None):
    """Build a minimal PredictionReport with known SHAP values."""
    if shap_values_per_row is None:
        shap_values_per_row = [
            {
                "costo_unitario": -0.89,
                "costo_vs_categoria_avg": -0.72,
                "precio_unitario": 0.41,
                "precio_vs_categoria_avg": 0.15,
                "sucursal": 0.10,
                "categoria": -0.08,
                "tag_menu_1": 0.02,
                "mes_num": 0.01,
                "log_cantidad": -0.03,
            }
        ]

    registros = [
        {"sucursal": "ANT", "mes": "ENERO 2026", "sku": "SKU1",
         "categoria": "Alimentos", "multiplicador_eficiencia": 9.0}
        for _ in shap_values_per_row
    ]

    feature_names = list(shap_values_per_row[0].keys())

    por_sku = []
    for i, sv in enumerate(shap_values_per_row):
        por_sku.append({
            "sku": registros[i]["sku"],
            "sucursal": registros[i]["sucursal"],
            "categoria": registros[i]["categoria"],
            "mes": registros[i]["mes"],
            "multiplicador_real": 9.0,
            "multiplicador_predicho": 9.0,
            "shap_values": sv,
            "shap_top_positivo": max(sv, key=sv.get),
            "shap_top_negativo": min(sv, key=sv.get),
        })

    key = "ANT_ENERO 2026"
    avg = {f: sum(sv[f] for sv in shap_values_per_row) / len(shap_values_per_row)
           for f in feature_names}
    importancia = {f: abs(v) for f, v in avg.items()}
    top_3 = sorted(importancia, key=importancia.get, reverse=True)[:3]

    return PredictionReport(
        por_sku=por_sku,
        por_sucursal_mes={
            key: {
                "shap_promedio": avg,
                "factor_mas_positivo": max(avg, key=avg.get),
                "factor_mas_negativo": min(avg, key=avg.get),
            }
        },
        global_={
            "shap_importancia": importancia,
            "top_3_factores": top_3,
            "shap_base_value": 5.0,
        },
        train_metrics={},
    )


# ── forecast_revenue ──────────────────────────────────────────────────────────

def test_forecast_one_month_returns_insuficiente_datos():
    report = _make_kpi_report([100_000])
    result = forecast_revenue(report)
    assert result.tendencia == "insuficiente_datos"
    assert result.variacion_pct_esperada is None


def test_forecast_three_months_baja_confianza():
    report = _make_kpi_report([100_000, 110_000, 120_000])
    result = forecast_revenue(report)
    assert result.confianza == "baja"


def test_forecast_growing_revenue_tendencia_creciente():
    report = _make_kpi_report([100_000, 110_000, 120_000, 130_000, 140_000])
    result = forecast_revenue(report)
    assert result.tendencia == "creciente"
    assert result.variacion_pct_esperada > 0.05


def test_forecast_declining_revenue_tendencia_decreciente():
    report = _make_kpi_report([140_000, 130_000, 120_000, 110_000, 100_000])
    result = forecast_revenue(report)
    assert result.tendencia == "decreciente"
    assert result.variacion_pct_esperada < -0.05


def test_forecast_flat_revenue_tendencia_estable():
    report = _make_kpi_report([100_000, 100_050, 99_980, 100_010, 100_030])
    result = forecast_revenue(report)
    assert result.tendencia == "estable"


def test_forecast_mes_proyectado_correct_next_month():
    meses = ["ENERO 2026", "FEBRERO 2026", "MARZO 2026"]
    report = _make_kpi_report([100_000, 110_000, 120_000], meses=meses)
    result = forecast_revenue(report)
    assert result.mes_proyectado == "ABRIL 2026"


def test_forecast_mes_proyectado_december_rolls_year():
    meses = ["OCTUBRE 2026", "NOVIEMBRE 2026", "DICIEMBRE 2026"]
    report = _make_kpi_report([100_000, 110_000, 120_000], meses=meses)
    result = forecast_revenue(report)
    assert result.mes_proyectado == "ENERO 2027"


def test_forecast_por_sucursal_included_when_data_present():
    sucursales = {
        "ANT": [100_000, 110_000, 120_000],
        "SLP": [80_000, 85_000, 90_000],
    }
    report = _make_kpi_report([180_000, 195_000, 210_000], sucursales=sucursales)
    result = forecast_revenue(report)
    assert "ANT" in result.por_sucursal
    assert "SLP" in result.por_sucursal


def test_forecast_por_sucursal_omits_branch_with_one_month():
    sucursales = {
        "ANT": [100_000, 110_000],
        "SLP": [80_000],  # only 1 data point — cannot project
    }
    report = _make_kpi_report([180_000, 190_000], sucursales=sucursales)
    result = forecast_revenue(report)
    assert "ANT" in result.por_sucursal
    assert "SLP" not in result.por_sucursal


def test_forecast_advertencia_always_present():
    for n in [1, 3, 9]:
        vals = [100_000 + i * 1000 for i in range(n)]
        report = _make_kpi_report(vals)
        result = forecast_revenue(report)
        assert result.advertencia and len(result.advertencia) > 0


def test_forecast_returns_forecast_result_instance():
    report = _make_kpi_report([100_000, 110_000, 120_000])
    result = forecast_revenue(report)
    assert isinstance(result, ForecastResult)
    assert result.metodo == "regresion_lineal"
    assert result.puntos_usados == 3


def test_forecast_alta_confianza_more_than_8_months():
    vals = [100_000 + i * 2_000 for i in range(9)]
    report = _make_kpi_report(vals)
    result = forecast_revenue(report)
    assert result.confianza == "alta"


def test_forecast_media_confianza_4_to_8_months():
    vals = [100_000 + i * 2_000 for i in range(6)]
    report = _make_kpi_report(vals)
    result = forecast_revenue(report)
    assert result.confianza == "media"


# ── shap_translator ───────────────────────────────────────────────────────────

def test_translate_shap_returns_narrative_per_sucursal_mes():
    pred = _make_prediction_report()
    result = translate_shap(pred, {})
    assert "ANT_ENERO 2026" in result.por_sucursal_mes
    narrativa = result.por_sucursal_mes["ANT_ENERO 2026"]["narrativa"]
    assert isinstance(narrativa, str) and len(narrativa) > 0


def test_translate_shap_factores_sorted_by_abs_desc():
    pred = _make_prediction_report()
    factores = result = translate_shap(pred, {}).por_sucursal_mes["ANT_ENERO 2026"]["factores"]
    shap_abs = [abs(f["shap"]) for f in factores]
    assert shap_abs == sorted(shap_abs, reverse=True)


def test_translate_shap_magnitud_alta():
    assert get_magnitud(0.6) == "alta"
    assert get_magnitud(-0.9) == "alta"


def test_translate_shap_magnitud_media():
    assert get_magnitud(0.3) == "media"
    assert get_magnitud(-0.2) == "media"


def test_translate_shap_magnitud_baja():
    assert get_magnitud(0.1) == "baja"
    assert get_magnitud(-0.05) == "baja"


def test_translate_shap_direccion_positivo():
    assert get_direccion(0.5) == "positivo"
    assert get_direccion(0.0) == "positivo"


def test_translate_shap_direccion_negativo():
    assert get_direccion(-0.1) == "negativo"


def test_translate_shap_narrativa_nonempty_spanish():
    pred = _make_prediction_report()
    result = translate_shap(pred, {})
    narrativa = result.por_sucursal_mes["ANT_ENERO 2026"]["narrativa"]
    spanish_markers = ["el", "la", "de", "en", "El", "La", "factor", "multiplicador"]
    assert any(m in narrativa for m in spanish_markers)


def test_translate_shap_global_narrativa_present():
    pred = _make_prediction_report()
    result = translate_shap(pred, {})
    assert "narrativa" in result.global_
    assert len(result.global_["narrativa"]) > 0


def test_translate_shap_top3_descripcion_length():
    pred = _make_prediction_report()
    result = translate_shap(pred, {})
    assert len(result.global_["top_3_factores_descripcion"]) == 3


def test_translate_shap_returns_shap_narrative_instance():
    pred = _make_prediction_report()
    result = translate_shap(pred, {})
    assert isinstance(result, SHAPNarrative)
