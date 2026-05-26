import dataclasses
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.pipeline.engine import CopilotReport
from src.pipeline.kpis import KPIReport
from src.pipeline.forecast import ForecastResult
from src.pipeline.parsers import ParseError

FIXTURES = Path(__file__).parent / "fixtures"


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_copilot_report() -> "CopilotReport":
    return CopilotReport(
        cliente_id="default",
        periodo="ENERO 2026",
        generated_at="2026-05-24T00:00:00+00:00",
        model_used="claude-sonnet-4-20250514",
        health_score=65.0,
        health_categoria="en_observacion",
        recomendaciones=[],
        narrativa_ejecutiva="El negocio muestra tendencia estable.",
        shap_top_factores=[],
        forecast=None,
        limitaciones=[],
        metadata={
            "meses_analizados": 1,
            "total_skus": 0,
            "skus_bajo_rendimiento": 0,
            "chunks_cualitativos_usados": 0,
            "prompt_tokens": 100,
            "completion_tokens": 200,
        },
    )


def _make_kpi_dict() -> dict:
    return {
        "meses_analizados": ["ENERO 2026"],
        "por_mes": {
            "ENERO 2026": {
                "consolidado": {"total_revenue": 1_000_000.0},
                "vs_benchmark": {},
                "efficiency_ranking": [],
                "skus_bajo_rendimiento": [],
            }
        },
        "tendencias": {"revenue": {"tendencia": "estable"}},
        "resumen_ejecutivo": {},
    }


def _make_forecast_dict() -> dict:
    return {
        "mes_proyectado": "FEBRERO 2026",
        "revenue_proyectado": 1_050_000.0,
        "tendencia": "creciente",
        "variacion_pct_esperada": 0.05,
        "confianza": "baja",
        "advertencia": "Solo 1 mes de datos.",
        "metodo": "regresion_lineal",
        "puntos_usados": 1,
        "por_sucursal": {},
    }


def _files():
    return {
        "bd_file": ("bd.csv", open(FIXTURES / "sample_bd.csv", "rb"), "text/csv"),
        "er_file": ("er.csv", open(FIXTURES / "sample_er.csv", "rb"), "text/csv"),
    }


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ── health tests ──────────────────────────────────────────────────────────────

def test_health_returns_200(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "2.0.0"


def test_health_detailed_returns_200(client):
    response = client.get("/api/v1/health/detailed")
    assert response.status_code == 200
    body = response.json()
    assert "status" in body
    assert "api_key_configured" in body


# ── /analyze tests ────────────────────────────────────────────────────────────

def test_analyze_with_valid_files_returns_200(client):
    with patch("src.api.routes.analysis.CopilotEngine") as MockEngine:
        MockEngine.return_value.run_full_pipeline.return_value = _make_copilot_report()

        with open(FIXTURES / "sample_bd.csv", "rb") as bd, \
             open(FIXTURES / "sample_er.csv", "rb") as er:
            response = client.post(
                "/api/v1/analyze",
                files={
                    "bd_file": ("bd.csv", bd, "text/csv"),
                    "er_file": ("er.csv", er, "text/csv"),
                },
            )

    assert response.status_code == 200
    body = response.json()
    assert "health_score" in body
    assert "recomendaciones" in body
    assert "narrativa_ejecutiva" in body


def test_analyze_missing_bd_file_returns_422(client):
    with open(FIXTURES / "sample_er.csv", "rb") as er:
        response = client.post(
            "/api/v1/analyze",
            files={"er_file": ("er.csv", er, "text/csv")},
        )
    assert response.status_code == 422


def test_analyze_missing_er_file_returns_422(client):
    with open(FIXTURES / "sample_bd.csv", "rb") as bd:
        response = client.post(
            "/api/v1/analyze",
            files={"bd_file": ("bd.csv", bd, "text/csv")},
        )
    assert response.status_code == 422


def test_analyze_parse_error_returns_422_with_message(client):
    with patch("src.api.routes.analysis.CopilotEngine") as MockEngine:
        MockEngine.return_value.run_full_pipeline.side_effect = ParseError("Columna faltante")

        with open(FIXTURES / "sample_bd.csv", "rb") as bd, \
             open(FIXTURES / "sample_er.csv", "rb") as er:
            response = client.post(
                "/api/v1/analyze",
                files={
                    "bd_file": ("bd.csv", bd, "text/csv"),
                    "er_file": ("er.csv", er, "text/csv"),
                },
            )

    assert response.status_code == 422
    assert "Columna faltante" in response.json()["detail"]


def test_global_error_handler_returns_500(client):
    with patch("src.api.routes.analysis.CopilotEngine") as MockEngine:
        MockEngine.return_value.run_full_pipeline.side_effect = RuntimeError("unexpected boom")

        with open(FIXTURES / "sample_bd.csv", "rb") as bd, \
             open(FIXTURES / "sample_er.csv", "rb") as er:
            response = client.post(
                "/api/v1/analyze",
                files={
                    "bd_file": ("bd.csv", bd, "text/csv"),
                    "er_file": ("er.csv", er, "text/csv"),
                },
            )

    assert response.status_code == 500
    body = response.json()
    assert "error" in body
    assert body["error"] == "Error interno"


def test_temp_files_cleaned_after_analyze(client):
    unlinked: list = []

    with patch("src.api.routes.analysis.CopilotEngine") as MockEngine, \
         patch("src.api.routes.analysis.os.unlink", side_effect=unlinked.append):
        MockEngine.return_value.run_full_pipeline.return_value = _make_copilot_report()

        with open(FIXTURES / "sample_bd.csv", "rb") as bd, \
             open(FIXTURES / "sample_er.csv", "rb") as er:
            client.post(
                "/api/v1/analyze",
                files={
                    "bd_file": ("bd.csv", bd, "text/csv"),
                    "er_file": ("er.csv", er, "text/csv"),
                },
            )

    assert len(unlinked) >= 2  # at least bd_tmp and er_tmp


# ── /kpis tests ───────────────────────────────────────────────────────────────

def test_kpis_does_not_call_llm(client):
    with patch("src.api.routes.analysis.CopilotEngine") as MockEngine, \
         patch("src.api.routes.analysis.parse_bd") as mock_bd, \
         patch("src.api.routes.analysis.parse_er") as mock_er, \
         patch("src.api.routes.analysis.integrate") as mock_integrate, \
         patch("src.api.routes.analysis.calcular_kpis", return_value=MagicMock()) as mock_kpis:

        mock_bd.return_value = MagicMock()
        mock_er.return_value = MagicMock()
        mock_integrate.return_value = MagicMock()
        mock_kpis.return_value.__class__ = KPIReport
        # Return a serializable dict instead of dataclass
        with patch("src.api.routes.analysis.dataclasses") as mock_dc:
            mock_dc.asdict.return_value = _make_kpi_dict()

            with open(FIXTURES / "sample_bd.csv", "rb") as bd, \
                 open(FIXTURES / "sample_er.csv", "rb") as er:
                response = client.post(
                    "/api/v1/kpis",
                    files={
                        "bd_file": ("bd.csv", bd, "text/csv"),
                        "er_file": ("er.csv", er, "text/csv"),
                    },
                )

    MockEngine.assert_not_called()
    assert response.status_code == 200


def test_kpis_returns_kpi_fields(client):
    with patch("src.api.routes.analysis.parse_bd") as mock_bd, \
         patch("src.api.routes.analysis.parse_er") as mock_er, \
         patch("src.api.routes.analysis.integrate") as mock_int, \
         patch("src.api.routes.analysis.calcular_kpis") as mock_kpis, \
         patch("src.api.routes.analysis.dataclasses") as mock_dc:

        mock_bd.return_value = MagicMock()
        mock_er.return_value = MagicMock()
        mock_int.return_value = MagicMock()
        mock_kpis.return_value = MagicMock()
        mock_dc.asdict.return_value = _make_kpi_dict()

        with open(FIXTURES / "sample_bd.csv", "rb") as bd, \
             open(FIXTURES / "sample_er.csv", "rb") as er:
            response = client.post(
                "/api/v1/kpis",
                files={
                    "bd_file": ("bd.csv", bd, "text/csv"),
                    "er_file": ("er.csv", er, "text/csv"),
                },
            )

    assert response.status_code == 200
    body = response.json()
    assert "meses_analizados" in body


# ── /macro tests ──────────────────────────────────────────────────────────────

def test_macro_returns_macro_data(client):
    import src.api.routes.analysis as analysis_module
    analysis_module._macro_cache = None
    analysis_module._macro_cache_ts = 0.0

    with patch("src.api.routes.analysis.MacroFetcher") as MockFetcher, \
         patch("src.api.routes.analysis.dataclasses") as mock_dc:

        mock_dc.asdict.side_effect = lambda x: {"mocked": True}
        MockFetcher.return_value.fetch_all.return_value = MagicMock()
        MockFetcher.return_value.calcular_indices.return_value = MagicMock()

        response = client.get("/api/v1/macro")

    assert response.status_code == 200
    body = response.json()
    assert "macro_data" in body
    assert "macro_indices" in body


def test_macro_uses_cache_on_second_call(client):
    import src.api.routes.analysis as analysis_module
    import time
    analysis_module._macro_cache = {"macro_data": {"cached": True}, "macro_indices": {}}
    analysis_module._macro_cache_ts = time.time()  # fresh cache

    with patch("src.api.routes.analysis.MacroFetcher") as MockFetcher:
        response = client.get("/api/v1/macro")

    MockFetcher.assert_not_called()  # should use cache
    assert response.status_code == 200
    assert response.json()["macro_data"]["cached"] is True


# ── /train tests ──────────────────────────────────────────────────────────────

def test_train_returns_train_metrics(client):
    with patch("src.api.routes.analysis.parse_bd") as mock_bd, \
         patch("src.api.routes.analysis.train") as mock_train:

        mock_bd.return_value = MagicMock()
        mock_train.return_value = MagicMock(
            train_metrics={"rmse": 1.2, "mae": 0.8, "r2": 0.85, "n_samples": 81},
            trained_at="2026-05-24T00:00:00+00:00",
        )

        with open(FIXTURES / "sample_bd.csv", "rb") as bd:
            response = client.post(
                "/api/v1/train",
                files={"bd_file": ("bd.csv", bd, "text/csv")},
                data={"cliente_id": "nama"},
            )

    assert response.status_code == 200
    body = response.json()
    assert "train_metrics" in body
    assert "rmse" in body["train_metrics"]


# ── /forecast tests ───────────────────────────────────────────────────────────

def test_forecast_endpoint_returns_forecast_fields(client):
    with patch("src.api.routes.analysis.parse_bd") as mock_bd, \
         patch("src.api.routes.analysis.parse_er") as mock_er, \
         patch("src.api.routes.analysis.integrate") as mock_int, \
         patch("src.api.routes.analysis.calcular_kpis") as mock_kpis, \
         patch("src.api.routes.analysis.forecast_revenue") as mock_forecast, \
         patch("src.api.routes.analysis.dataclasses") as mock_dc:

        mock_bd.return_value = MagicMock()
        mock_er.return_value = MagicMock()
        mock_int.return_value = MagicMock()
        mock_kpis.return_value = MagicMock()
        mock_forecast.return_value = MagicMock()
        mock_dc.asdict.return_value = _make_forecast_dict()

        with open(FIXTURES / "sample_bd.csv", "rb") as bd, \
             open(FIXTURES / "sample_er.csv", "rb") as er:
            response = client.post(
                "/api/v1/forecast",
                files={
                    "bd_file": ("bd.csv", bd, "text/csv"),
                    "er_file": ("er.csv", er, "text/csv"),
                },
            )

    assert response.status_code == 200
    body = response.json()
    assert "mes_proyectado" in body
    assert "tendencia" in body
    assert "confianza" in body
