import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.pipeline.kpis import KPIReport
from src.pipeline.health_score import HealthScoreReport
from src.pipeline.shap_translator import SHAPNarrative
from src.pipeline.forecast import ForecastResult
from src.pipeline.engine import CopilotEngine, CopilotReport

# ── constants ─────────────────────────────────────────────────────────────────

_DEFAULT_LLM_JSON = {
    "recomendaciones": [
        {
            "id": "REC-001",
            "area": "costos",
            "prioridad": "alta",
            "titulo": "Reducir costo unitario en ANT",
            "descripcion": "El costo unitario está por encima del promedio de categoría.",
            "evidencia": [{"tipo": "shap", "fuente": "costo_unitario", "valor": "-0.89"}],
            "accion_sugerida": "Renegociar proveedores en sucursal ANT.",
            "impacto_estimado": "~5% mejora en multiplicador de eficiencia",
        }
    ],
    "narrativa_ejecutiva": "El negocio muestra presión en costos con oportunidades en mix.",
    "limitaciones": [],
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_llm_response(data: dict = None, text: str = None) -> MagicMock:
    if text is None:
        text = json.dumps(data or _DEFAULT_LLM_JSON)
    m = MagicMock()
    m.content = [MagicMock(text=text)]
    m.usage = MagicMock(input_tokens=100, output_tokens=200)
    return m


def _make_kpi_report(meses=None) -> KPIReport:
    meses = meses or ["ENERO 2026"]
    por_mes = {
        mes: {
            "consolidado": {
                "margen_bruto": 0.68,
                "nomina_pct": 0.28,
                "gastos_financieros_pct": 0.05,
                "total_revenue": 1_000_000.0,
                "ebitda": 100_000.0,
                "margen_neto": 0.10,
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
        tendencias={
            "revenue": {
                "tendencia": "estable",
                "variacion_pct": 0.0,
                "valores": [1_000_000.0] * len(meses),
                "meses": meses,
            }
        },
        resumen_ejecutivo={},
    )


def _make_health_report(mes: str = "ENERO 2026", score: float = 65.0) -> HealthScoreReport:
    return HealthScoreReport(
        por_mes={
            mes: {
                "score_total": score,
                "categoria": "en_observacion",
                "dimensiones": {
                    "margen_bruto_vs_benchmark": {
                        "score": 80, "peso": 0.30, "valor_base": 0.68,
                        "benchmark": 0.68, "contribucion": 24.0,
                    },
                    "nomina_vs_benchmark": {
                        "score": 80, "peso": 0.25, "valor_base": 0.28,
                        "benchmark": 0.28, "contribucion": 20.0,
                    },
                    "gastos_financieros_vs_benchmark": {
                        "score": 20, "peso": 0.20, "valor_base": 0.08,
                        "benchmark": 0.05, "contribucion": 4.0,
                    },
                    "presion_inflacionaria": {
                        "score": 80, "peso": 0.15, "valor_base": 0.4,
                        "benchmark": None, "contribucion": 12.0,
                    },
                    "tendencia_ingresos": {
                        "score": 50, "peso": 0.10, "valor_base": "estable",
                        "benchmark": None, "contribucion": 5.0,
                    },
                },
                "score_total_verificacion": score,
                "dimension_mas_debil": "gastos_financieros_vs_benchmark",
                "dimension_mas_fuerte": "margen_bruto_vs_benchmark",
            }
        },
        tendencia_score={"valores": [score], "meses": [mes], "tendencia": "insuficiente_datos"},
    )


def _make_shap_narrative() -> SHAPNarrative:
    return SHAPNarrative(
        por_sucursal_mes={
            "ANT_ENERO 2026": {
                "narrativa": "El costo unitario arrastra el multiplicador.",
                "factores": [
                    {"feature": "costo_unitario", "shap": -0.89,
                     "direccion": "negativo", "magnitud": "alta",
                     "descripcion": "Costo alto."},
                ],
            }
        },
        global_={
            "narrativa": "El factor más influyente es costo_unitario con importancia 0.89.",
            "top_3_factores_descripcion": [
                {"feature": "costo_unitario", "importancia": 0.89, "descripcion": "Alto impacto."},
                {"feature": "precio_unitario", "importancia": 0.41, "descripcion": "Positivo."},
                {"feature": "costo_vs_categoria_avg", "importancia": 0.32, "descripcion": "Relativo."},
            ],
        },
    )


def _make_forecast() -> ForecastResult:
    return ForecastResult(
        mes_proyectado="FEBRERO 2026",
        revenue_proyectado=1_050_000.0,
        tendencia="creciente",
        variacion_pct_esperada=0.05,
        confianza="baja",
        advertencia="Proyección basada en 1 mes de datos.",
        metodo="regresion_lineal",
        puntos_usados=1,
        por_sucursal={},
    )


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def engine():
    with patch("src.pipeline.engine.anthropic.Anthropic") as MockAnthropic:
        mock_client = MockAnthropic.return_value
        mock_client.messages.create.return_value = _make_llm_response()
        e = CopilotEngine()
        yield e


# ── build_prompt tests ────────────────────────────────────────────────────────

def test_build_prompt_includes_health_score_section(engine):
    kpi = _make_kpi_report()
    hs = _make_health_report()
    prompt = engine.build_prompt(kpi, hs, None, None, None, [])
    assert "Health Score" in prompt
    assert "65.0" in prompt
    assert "en_observacion" in prompt


def test_build_prompt_includes_shap_narrative_when_provided(engine):
    kpi = _make_kpi_report()
    hs = _make_health_report()
    shap = _make_shap_narrative()
    prompt = engine.build_prompt(kpi, hs, None, shap, None, [])
    assert "Análisis ML" in prompt
    assert "costo_unitario" in prompt


def test_build_prompt_excludes_shap_section_when_none(engine):
    kpi = _make_kpi_report()
    hs = _make_health_report()
    prompt = engine.build_prompt(kpi, hs, None, None, None, [])
    assert "Análisis ML" not in prompt


def test_build_prompt_includes_forecast_when_provided(engine):
    kpi = _make_kpi_report()
    hs = _make_health_report()
    forecast = _make_forecast()
    prompt = engine.build_prompt(kpi, hs, None, None, forecast, [])
    assert "Forecast" in prompt
    assert "FEBRERO 2026" in prompt
    assert "creciente" in prompt


def test_build_prompt_handles_none_macro_gracefully(engine):
    kpi = _make_kpi_report()
    hs = _make_health_report()
    # Should not raise and should not include macro section
    prompt = engine.build_prompt(kpi, hs, None, None, None, [])
    assert "macroeconómico" not in prompt


def test_build_prompt_includes_macro_when_provided(engine):
    kpi = _make_kpi_report()
    hs = _make_health_report()
    macro = MagicMock()
    macro.narrativa_consolidada = "Inflación moderada en México."
    prompt = engine.build_prompt(kpi, hs, macro, None, None, [])
    assert "macroeconómico" in prompt
    assert "Inflación moderada" in prompt


def test_build_prompt_under_5000_chars_for_single_month(engine):
    kpi = _make_kpi_report()
    hs = _make_health_report()
    prompt = engine.build_prompt(kpi, hs, None, None, None, [])
    assert len(prompt) < 5000


def test_build_prompt_includes_qualitative_chunks(engine):
    kpi = _make_kpi_report()
    hs = _make_health_report()
    chunks = [{"source": "doc1.pdf", "fecha": "2026-01", "text": "Texto de prueba."}]
    prompt = engine.build_prompt(kpi, hs, None, None, None, chunks)
    assert "cualitativo" in prompt
    assert "doc1.pdf" in prompt


# ── generate tests ────────────────────────────────────────────────────────────

def test_generate_raises_error_if_no_months(engine):
    kpi_empty = KPIReport(
        meses_analizados=[],
        por_mes={},
        tendencias={},
        resumen_ejecutivo={},
    )
    hs = _make_health_report()
    with pytest.raises(ValueError, match="no months"):
        engine.generate(kpi_empty, hs)


def test_generate_retries_once_on_invalid_json(engine):
    kpi = _make_kpi_report()
    hs = _make_health_report()
    invalid = _make_llm_response(text="not valid json {{}")
    valid = _make_llm_response()
    engine._client.messages.create.side_effect = [invalid, valid]
    result = engine.generate(kpi, hs)
    assert engine._client.messages.create.call_count == 2
    assert isinstance(result, CopilotReport)


def test_copilot_report_has_all_required_fields(engine):
    kpi = _make_kpi_report()
    hs = _make_health_report()
    result = engine.generate(kpi, hs, cliente_id="nama")
    assert result.cliente_id == "nama"
    assert result.periodo == "ENERO 2026"
    assert result.generated_at
    assert result.model_used
    assert isinstance(result.health_score, float)
    assert result.health_categoria
    assert isinstance(result.recomendaciones, list)
    assert isinstance(result.narrativa_ejecutiva, str)
    assert isinstance(result.shap_top_factores, list)
    assert isinstance(result.limitaciones, list)
    assert isinstance(result.metadata, dict)


def test_shap_top_factores_populated_from_shap_narrative(engine):
    kpi = _make_kpi_report()
    hs = _make_health_report()
    shap = _make_shap_narrative()
    result = engine.generate(kpi, hs, shap_narrative=shap)
    assert len(result.shap_top_factores) == 3
    assert result.shap_top_factores[0]["feature"] == "costo_unitario"


def test_shap_top_factores_empty_when_no_shap_narrative(engine):
    kpi = _make_kpi_report()
    hs = _make_health_report()
    result = engine.generate(kpi, hs, shap_narrative=None)
    assert result.shap_top_factores == []


def test_generate_forecast_included_in_report(engine):
    kpi = _make_kpi_report()
    hs = _make_health_report()
    forecast = _make_forecast()
    result = engine.generate(kpi, hs, forecast_result=forecast)
    assert result.forecast is not None
    assert result.forecast["mes_proyectado"] == "FEBRERO 2026"
    assert result.forecast["tendencia"] == "creciente"


def test_generate_forecast_none_when_not_provided(engine):
    kpi = _make_kpi_report()
    hs = _make_health_report()
    result = engine.generate(kpi, hs)
    assert result.forecast is None


def test_limitaciones_includes_data_gap_when_1_month(engine):
    kpi = _make_kpi_report(meses=["ENERO 2026"])
    hs = _make_health_report()
    result = engine.generate(kpi, hs)
    gap_msgs = [l for l in result.limitaciones if "mes" in l.lower()]
    assert len(gap_msgs) >= 1


def test_limitaciones_no_gap_when_3_months(engine):
    meses = ["ENERO 2026", "FEBRERO 2026", "MARZO 2026"]
    kpi = _make_kpi_report(meses=meses)
    hs_multi = HealthScoreReport(
        por_mes={mes: _make_health_report(mes=mes).por_mes[mes] for mes in meses},
        tendencia_score={"valores": [65.0] * 3, "meses": meses, "tendencia": "estable"},
    )
    result = engine.generate(kpi, hs_multi)
    gap_msgs = [l for l in result.limitaciones if "mes(es)" in l]
    assert len(gap_msgs) == 0


def test_generate_metadata_fields_present(engine):
    kpi = _make_kpi_report()
    hs = _make_health_report()
    result = engine.generate(kpi, hs)
    for key in ("meses_analizados", "total_skus", "skus_bajo_rendimiento",
                "chunks_cualitativos_usados", "prompt_tokens", "completion_tokens"):
        assert key in result.metadata


# ── run_full_pipeline tests ───────────────────────────────────────────────────

def test_run_full_pipeline_calls_all_steps(engine, tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text('{"benchmarks": {}, "health_score_weights": {}}')

    kpi_mock = _make_kpi_report()
    hs_mock = _make_health_report()

    with patch("src.pipeline.engine.parse_bd", return_value=MagicMock()) as m_bd, \
         patch("src.pipeline.engine.parse_er", return_value=MagicMock()) as m_er, \
         patch("src.pipeline.engine.integrate", return_value=MagicMock()) as m_integrate, \
         patch("src.pipeline.engine.calcular_kpis", return_value=kpi_mock) as m_kpis, \
         patch("src.pipeline.engine.train", return_value=MagicMock()) as m_train, \
         patch("src.pipeline.engine.predict_and_explain", return_value=MagicMock()) as m_pred, \
         patch("src.pipeline.engine.translate_shap", return_value=MagicMock()) as m_shap, \
         patch("src.pipeline.engine.forecast_revenue", return_value=MagicMock()) as m_forecast, \
         patch("src.pipeline.engine.MacroFetcher") as MockFetcher, \
         patch("src.pipeline.engine.calcular_health_score", return_value=hs_mock) as m_hs, \
         patch.object(engine, "generate", return_value=MagicMock()) as m_gen:

        MockFetcher.return_value.fetch_all.return_value = MagicMock()
        MockFetcher.return_value.calcular_indices.return_value = MagicMock()

        engine.run_full_pipeline("bd.csv", "er.csv", config_path=str(config_file))

    m_bd.assert_called_once_with("bd.csv")
    m_er.assert_called_once_with("er.csv")
    m_integrate.assert_called_once()
    m_kpis.assert_called_once()
    m_forecast.assert_called_once()
    m_hs.assert_called_once()
    m_gen.assert_called_once()


def test_run_full_pipeline_skips_ml_when_train_false(engine, tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text("{}")

    kpi_mock = _make_kpi_report()
    hs_mock = _make_health_report()

    with patch("src.pipeline.engine.parse_bd", return_value=MagicMock()), \
         patch("src.pipeline.engine.parse_er", return_value=MagicMock()), \
         patch("src.pipeline.engine.integrate", return_value=MagicMock()), \
         patch("src.pipeline.engine.calcular_kpis", return_value=kpi_mock), \
         patch("src.pipeline.engine.train") as m_train, \
         patch("src.pipeline.engine.forecast_revenue", return_value=MagicMock()), \
         patch("src.pipeline.engine.MacroFetcher"), \
         patch("src.pipeline.engine.calcular_health_score", return_value=hs_mock), \
         patch.object(engine, "generate", return_value=MagicMock()):

        engine.run_full_pipeline(
            "bd.csv", "er.csv",
            config_path=str(config_file),
            train_model=False,
        )

    m_train.assert_not_called()
