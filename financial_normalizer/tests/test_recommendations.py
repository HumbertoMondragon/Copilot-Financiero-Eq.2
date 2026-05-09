"""
Tests for financial_normalizer/recommendations.py.
All Anthropic API calls are fully mocked — no real network calls.
"""
import json
import pytest
from dataclasses import fields
from unittest.mock import MagicMock, patch

from financial_normalizer.recommendations import (
    RecommendationEngine,
    RecommendationReport,
    RecommendationError,
    _try_parse_json,
    _build_limitaciones,
)
from financial_normalizer.orchestrator import AnalysisOrchestrator, AnalysisPackage
from financial_normalizer.tests.fixtures import build_normalized_doc
from financial_normalizer.profiles import empty_month


# ── Shared test data ──────────────────────────────────────────────────────────

VALID_RECS = [
    {
        "id": "REC-001",
        "area": "sucursales",
        "prioridad": "alta",
        "titulo": "Mejorar rentabilidad de sucursal A",
        "descripcion": "Sucursal A presenta el margen más bajo del grupo.",
        "evidencia": [
            {
                "tipo": "indicador",
                "fuente": "ENERO 2026 / sucursal A margen",
                "valor": "38.0%",
            }
        ],
        "accion_sugerida": "Revisar estructura de costos en sucursal A.",
    }
]
VALID_RECS_JSON = json.dumps(VALID_RECS)


def _make_mock_response(json_text: str, input_tokens: int = 500, output_tokens: int = 300):
    resp = MagicMock()
    resp.content = [MagicMock(text=json_text)]
    resp.usage.input_tokens = input_tokens
    resp.usage.output_tokens = output_tokens
    return resp


def _make_pkg(with_chunks: bool = False, listo: bool = True) -> AnalysisPackage:
    base = AnalysisOrchestrator().analyze(build_normalized_doc(), "test_client")
    if not with_chunks and listo:
        return base
    ctx = {}
    if with_chunks:
        ctx["ENERO 2026"] = {
            "queries_usadas": base.contexto_cualitativo.get("ENERO 2026", {}).get("queries_usadas", []),
            "chunks_relevantes": [
                {"texto": "El margen EBITDA superó el umbral mínimo del período.", "score": 0.92, "filename": "informe.pdf", "chunk_index": 0},
                {"texto": "Los costos operativos se mantuvieron dentro del presupuesto.", "score": 0.85, "filename": "informe.pdf", "chunk_index": 1},
                {"texto": "La sucursal A registró el mayor volumen de ventas.", "score": 0.78, "filename": "informe.pdf", "chunk_index": 2},
            ],
        }
    else:
        ctx = base.contexto_cualitativo

    return AnalysisPackage(
        cliente_id=base.cliente_id,
        periodo=base.periodo,
        generated_at=base.generated_at,
        indicadores=base.indicadores,
        contexto_cualitativo=ctx,
        resumen_alertas=base.resumen_alertas,
        listo_para_recomendaciones=listo,
    )


def _make_low_margin_pkg() -> AnalysisPackage:
    mes = empty_month()
    mes["kpis"]["total_ventas"] = 1_000_000.0
    mes["kpis"]["margen_bruto"] = 0.30
    mes["kpis"]["margen_ebitda"] = 0.04
    mes["kpis"]["margen_neto"] = 0.02
    mes["ventas"]["A"]["total"] = 500_000.0
    mes["egresos"]["A"]["total"] = 400_000.0
    doc = {"cliente_id": "c1", "periodo": "2026", "meses": {"ENERO 2026": mes}}
    return AnalysisOrchestrator().analyze(doc, "c1")


# ── Engine fixture ────────────────────────────────────────────────────────────

@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("anthropic.Anthropic"):
        yield RecommendationEngine()


@pytest.fixture
def engine_with_mock(monkeypatch):
    """Returns (engine, mock_client) where mock_client.messages.create can be configured."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("anthropic.Anthropic") as MockCls:
        mock_client = MagicMock()
        MockCls.return_value = mock_client
        eng = RecommendationEngine()
        yield eng, mock_client


# ── RecommendationEngine init ─────────────────────────────────────────────────

class TestEngineInit:

    def test_raises_without_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
            RecommendationEngine()

    def test_creates_successfully_with_api_key(self, engine):
        assert engine is not None

    def test_default_model(self, engine):
        assert engine._model == "claude-sonnet-4-20250514"

    def test_custom_model(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        with patch("anthropic.Anthropic"):
            eng = RecommendationEngine(model="claude-haiku-4-5-20251001")
            assert eng._model == "claude-haiku-4-5-20251001"


# ── build_prompt ──────────────────────────────────────────────────────────────

class TestBuildPrompt:

    def test_returns_string(self, engine):
        pkg = _make_pkg()
        assert isinstance(engine.build_prompt(pkg), str)

    def test_under_4000_chars_for_single_month(self, engine):
        pkg = _make_pkg()
        prompt = engine.build_prompt(pkg)
        assert len(prompt) < 4000

    def test_includes_period(self, engine):
        pkg = _make_pkg()
        assert "2026" in engine.build_prompt(pkg)

    def test_includes_month_name(self, engine):
        pkg = _make_pkg()
        assert "ENERO 2026" in engine.build_prompt(pkg)

    def test_includes_margin_values(self, engine):
        pkg = _make_pkg()
        prompt = engine.build_prompt(pkg)
        assert "%" in prompt
        assert "Margen bruto" in prompt or "margen bruto" in prompt.lower()

    def test_includes_sucursal_data(self, engine):
        pkg = _make_pkg()
        prompt = engine.build_prompt(pkg)
        for grp in "ABCDE":
            assert grp in prompt

    def test_includes_alert_values_when_active(self, engine):
        pkg = _make_low_margin_pkg()
        prompt = engine.build_prompt(pkg)
        assert "ALERTA" in prompt.upper() or "alerta" in prompt.lower()
        assert "30.0%" in prompt or "0.30" in prompt or "30%" in prompt

    def test_alert_type_mentioned_when_active(self, engine):
        pkg = _make_low_margin_pkg()
        prompt = engine.build_prompt(pkg)
        assert "margen_bruto" in prompt or "margen bruto" in prompt.lower()

    def test_no_alerts_message_when_healthy(self, engine):
        pkg = _make_pkg()
        prompt = engine.build_prompt(pkg)
        assert "ninguna" in prompt.lower() or "sin alertas" in prompt.lower() or "Alertas: ninguna" in prompt

    def test_includes_chunks_when_present(self, engine):
        pkg = _make_pkg(with_chunks=True)
        prompt = engine.build_prompt(pkg)
        assert "informe.pdf" in prompt
        assert "EBITDA superó" in prompt or "margen" in prompt.lower()

    def test_no_chunks_message_when_absent(self, engine):
        pkg = _make_pkg(with_chunks=False)
        prompt = engine.build_prompt(pkg)
        assert "ninguno" in prompt.lower()

    def test_does_not_include_raw_json_dict_keys(self, engine):
        pkg = _make_pkg()
        prompt = engine.build_prompt(pkg)
        # Prompt must not contain raw JSON field names used in the normalized schema
        assert '"total_costo"' not in prompt
        assert '"gastos_administrativos"' not in prompt
        assert '"utilidad_bruta"' not in prompt
        assert '"margen_costo"' not in prompt

    def test_includes_output_instructions(self, engine):
        pkg = _make_pkg()
        prompt = engine.build_prompt(pkg)
        assert "JSON" in prompt
        assert "REC-001" in prompt

    def test_chunks_capped_at_8_in_prompt(self, engine):
        pkg = _make_pkg()
        # Inject 12 chunks across two months
        ctx = {}
        for mes in ["ENERO 2026", "FEBRERO 2026"]:
            ctx[mes] = {
                "queries_usadas": [],
                "chunks_relevantes": [
                    {"texto": f"chunk {mes} {i}", "score": 0.9 - i * 0.01, "filename": "f.txt", "chunk_index": i}
                    for i in range(6)
                ],
            }
        pkg2 = AnalysisPackage(
            cliente_id=pkg.cliente_id,
            periodo=pkg.periodo,
            generated_at=pkg.generated_at,
            indicadores=pkg.indicadores,
            contexto_cualitativo=ctx,
            resumen_alertas=pkg.resumen_alertas,
            listo_para_recomendaciones=pkg.listo_para_recomendaciones,
        )
        prompt = engine.build_prompt(pkg2)
        # Count how many "chunk_index" markers appear — each chunk adds one [filename, chunk N] line
        chunk_lines = [line for line in prompt.splitlines() if line.strip().startswith("[") and "chunk" in line.lower()]
        assert len(chunk_lines) <= 8


# ── generate() ────────────────────────────────────────────────────────────────

class TestGenerate:

    def test_raises_when_not_listo(self, engine):
        pkg = _make_pkg(listo=False)
        with pytest.raises(RecommendationError, match="not ready"):
            engine.generate(pkg)

    def test_returns_recommendation_report(self, engine_with_mock):
        eng, mock_client = engine_with_mock
        mock_client.messages.create.return_value = _make_mock_response(VALID_RECS_JSON)
        pkg = _make_pkg()
        report = eng.generate(pkg)
        assert isinstance(report, RecommendationReport)

    def test_parses_valid_json_response(self, engine_with_mock):
        eng, mock_client = engine_with_mock
        mock_client.messages.create.return_value = _make_mock_response(VALID_RECS_JSON)
        report = eng.generate(_make_pkg())
        assert len(report.recomendaciones) == 1
        assert report.recomendaciones[0]["id"] == "REC-001"

    def test_retries_once_on_invalid_json(self, engine_with_mock):
        eng, mock_client = engine_with_mock
        mock_client.messages.create.side_effect = [
            _make_mock_response("esto no es json válido {{{"),
            _make_mock_response(VALID_RECS_JSON),
        ]
        report = eng.generate(_make_pkg())
        assert mock_client.messages.create.call_count == 2
        assert isinstance(report, RecommendationReport)

    def test_raises_after_two_invalid_json_responses(self, engine_with_mock):
        eng, mock_client = engine_with_mock
        mock_client.messages.create.side_effect = [
            _make_mock_response("invalid json one {"),
            _make_mock_response("invalid json two {"),
        ]
        with pytest.raises(RecommendationError):
            eng.generate(_make_pkg())
        assert mock_client.messages.create.call_count == 2

    def test_raw_response_attached_on_double_failure(self, engine_with_mock):
        eng, mock_client = engine_with_mock
        mock_client.messages.create.side_effect = [
            _make_mock_response("bad 1"),
            _make_mock_response("bad 2"),
        ]
        with pytest.raises(RecommendationError) as exc_info:
            eng.generate(_make_pkg())
        assert exc_info.value.raw_response == "bad 2"

    def test_api_called_once_on_success(self, engine_with_mock):
        eng, mock_client = engine_with_mock
        mock_client.messages.create.return_value = _make_mock_response(VALID_RECS_JSON)
        eng.generate(_make_pkg())
        assert mock_client.messages.create.call_count == 1

    def test_accepts_json_wrapped_in_markdown_fence(self, engine_with_mock):
        eng, mock_client = engine_with_mock
        fenced = f"```json\n{VALID_RECS_JSON}\n```"
        mock_client.messages.create.return_value = _make_mock_response(fenced)
        report = eng.generate(_make_pkg())
        assert len(report.recomendaciones) == 1


# ── RecommendationReport fields ───────────────────────────────────────────────

class TestRecommendationReportFields:

    @pytest.fixture
    def report(self, engine_with_mock):
        eng, mock_client = engine_with_mock
        mock_client.messages.create.return_value = _make_mock_response(VALID_RECS_JSON)
        return eng.generate(_make_pkg())

    def test_all_required_fields_present(self, report):
        field_names = {f.name for f in fields(report)}
        for required in (
            "cliente_id", "periodo", "generated_at", "model_used",
            "recomendaciones", "limitaciones", "resumen_ejecutivo", "metadata",
        ):
            assert required in field_names

    def test_cliente_id_correct(self, report):
        assert report.cliente_id == "test_client"

    def test_periodo_correct(self, report):
        assert report.periodo == "2026"

    def test_model_used_set(self, report):
        assert report.model_used == "claude-sonnet-4-20250514"

    def test_generated_at_is_iso_string(self, report):
        assert isinstance(report.generated_at, str)
        assert "T" in report.generated_at

    def test_metadata_has_required_keys(self, report):
        for key in ("meses_analizados", "alertas_activas", "chunks_cualitativos_usados",
                    "prompt_tokens", "completion_tokens"):
            assert key in report.metadata

    def test_metadata_token_counts_from_response(self, report):
        assert report.metadata["prompt_tokens"] == 500
        assert report.metadata["completion_tokens"] == 300

    def test_resumen_ejecutivo_is_string(self, report):
        assert isinstance(report.resumen_ejecutivo, str)
        assert len(report.resumen_ejecutivo) > 0

    def test_limitaciones_is_list(self, report):
        assert isinstance(report.limitaciones, list)


# ── metadata.chunks_cualitativos_usados ───────────────────────────────────────

class TestChunkCount:

    def test_chunks_counted_correctly_with_three_chunks(self, engine_with_mock):
        eng, mock_client = engine_with_mock
        mock_client.messages.create.return_value = _make_mock_response(VALID_RECS_JSON)
        pkg = _make_pkg(with_chunks=True)  # 3 chunks in ENERO 2026
        report = eng.generate(pkg)
        assert report.metadata["chunks_cualitativos_usados"] == 3

    def test_chunks_zero_when_no_context(self, engine_with_mock):
        eng, mock_client = engine_with_mock
        mock_client.messages.create.return_value = _make_mock_response(VALID_RECS_JSON)
        pkg = _make_pkg(with_chunks=False)
        report = eng.generate(pkg)
        assert report.metadata["chunks_cualitativos_usados"] == 0


# ── limitaciones ──────────────────────────────────────────────────────────────

class TestLimitaciones:

    def test_data_gap_message_for_one_month(self, engine_with_mock):
        eng, mock_client = engine_with_mock
        mock_client.messages.create.return_value = _make_mock_response(VALID_RECS_JSON)
        pkg = _make_pkg()  # single month → tendencias insuficiente_datos
        report = eng.generate(pkg)
        assert any("1 mes" in lim for lim in report.limitaciones)

    def test_qualitative_gap_message_when_no_chunks(self, engine_with_mock):
        eng, mock_client = engine_with_mock
        mock_client.messages.create.return_value = _make_mock_response(VALID_RECS_JSON)
        pkg = _make_pkg(with_chunks=False)
        report = eng.generate(pkg)
        assert any("cualitativ" in lim.lower() for lim in report.limitaciones)

    def test_no_qualitative_gap_when_chunks_present(self, engine_with_mock):
        eng, mock_client = engine_with_mock
        mock_client.messages.create.return_value = _make_mock_response(VALID_RECS_JSON)
        pkg = _make_pkg(with_chunks=True)
        report = eng.generate(pkg)
        assert not any("cualitativ" in lim.lower() for lim in report.limitaciones)

    def test_both_gaps_present_for_single_month_no_chunks(self, engine_with_mock):
        eng, mock_client = engine_with_mock
        mock_client.messages.create.return_value = _make_mock_response(VALID_RECS_JSON)
        pkg = _make_pkg(with_chunks=False)
        report = eng.generate(pkg)
        assert len(report.limitaciones) >= 2


# ── _try_parse_json unit tests ────────────────────────────────────────────────

class TestTryParseJson:

    def test_valid_list(self):
        assert _try_parse_json('[{"a": 1}]') == [{"a": 1}]

    def test_invalid_returns_none(self):
        assert _try_parse_json("not json {{{") is None

    def test_strips_markdown_fence(self):
        text = '```json\n[{"a": 1}]\n```'
        assert _try_parse_json(text) == [{"a": 1}]

    def test_strips_plain_fence(self):
        text = '```\n[{"a": 1}]\n```'
        assert _try_parse_json(text) == [{"a": 1}]

    def test_handles_wrapper_key(self):
        text = '{"recomendaciones": [{"id": "REC-001"}]}'
        result = _try_parse_json(text)
        assert result == [{"id": "REC-001"}]

    def test_returns_none_for_plain_dict(self):
        assert _try_parse_json('{"id": "REC-001"}') is None

    def test_empty_list(self):
        assert _try_parse_json("[]") == []
