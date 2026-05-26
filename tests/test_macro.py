import pytest
from unittest.mock import patch, MagicMock

from src.pipeline.macro import MacroFetcher, MacroData, MacroIndices

# ── mock helpers ──────────────────────────────────────────────────────────────

_BANXICO_TC = {
    "bmx": {"series": [{"datos": [{"dato": "17.23", "fecha": "09/05/2026"}]}]}
}
_BANXICO_TASA = {
    "bmx": {"series": [{"datos": [{"dato": "9.00", "fecha": "09/05/2026"}]}]}
}
# SP1 date-range response: 2 entries so prev=datos[0], last=datos[-1] → 3.8% variation
_BANXICO_INPC_RANGE = {
    "bmx": {"series": [{"datos": [
        {"dato": "100.00", "fecha": "01/04/2025"},
        {"dato": "103.80", "fecha": "01/04/2026"},
    ]}]}
}
_INEGI_IGAE = {
    "Series": [{"OBSERVATIONS": [{"OBS_VALUE": "1.2", "TIME_PERIOD": "2026/03"}]}]
}

_ALL_RESPONSES = [_BANXICO_TC, _BANXICO_TASA, _BANXICO_INPC_RANGE, _INEGI_IGAE]

_CONFIG = {
    "macro_sensibilidad": {
        "energia": 0.15,
        "servicios": 0.40,
        "mercancias": 0.30,
        "alimentos": 0.15,
    }
}


def _make_response(json_data):
    m = MagicMock()
    m.raise_for_status.return_value = None
    m.json.return_value = json_data
    return m


def _all_fail_macro() -> MacroData:
    return MacroData(
        fetched_at="2026-05-24T00:00:00+00:00",
        raw={
            "tipo_cambio_usd": None,
            "tasa_interes": None,
            "inpc_variacion_anual": None,
            "igae_variacion_anual": None,
            "inpc_por_componente": None,
            "expectativa_inflacion_12m": None,
        },
        errores=["Banxico SF43718: timeout", "Banxico SF61745: timeout",
                 "Banxico SP1: timeout", "INEGI IGAE: timeout"],
    )


# ── fetch_all tests ───────────────────────────────────────────────────────────

def test_fetch_all_returns_macro_data_even_on_all_failures():
    fetcher = MacroFetcher()
    with patch("src.pipeline.macro.requests.get", side_effect=Exception("timeout")):
        result = fetcher.fetch_all()
    assert isinstance(result, MacroData)
    assert result.fetched_at
    assert isinstance(result.raw, dict)


def test_fetch_all_populates_errores_on_all_failures():
    fetcher = MacroFetcher()
    with patch("src.pipeline.macro.requests.get", side_effect=Exception("timeout")):
        result = fetcher.fetch_all()
    assert len(result.errores) == 4  # two Banxico + two INEGI
    assert all(isinstance(e, str) for e in result.errores)


def test_fetch_all_errores_empty_on_full_success():
    fetcher = MacroFetcher()
    responses = [_make_response(d) for d in _ALL_RESPONSES]
    with patch("src.pipeline.macro.requests.get", side_effect=responses):
        result = fetcher.fetch_all()
    assert result.errores == []


def test_fetch_all_successful_values_populated():
    fetcher = MacroFetcher()
    responses = [_make_response(d) for d in _ALL_RESPONSES]
    with patch("src.pipeline.macro.requests.get", side_effect=responses):
        result = fetcher.fetch_all()
    assert result.raw["tipo_cambio_usd"]["valor"] == pytest.approx(17.23)
    assert result.raw["tasa_interes"]["valor"] == pytest.approx(9.0)
    assert result.raw["inpc_variacion_anual"]["valor"] == pytest.approx(3.8)
    assert result.raw["igae_variacion_anual"]["valor"] == pytest.approx(1.2)


def test_fetch_all_failed_source_is_none_in_raw():
    fetcher = MacroFetcher()
    # First call fails (tipo_cambio), rest succeed
    responses = [Exception("timeout")] + [_make_response(d) for d in _ALL_RESPONSES[1:]]
    with patch("src.pipeline.macro.requests.get", side_effect=responses):
        result = fetcher.fetch_all()
    assert result.raw["tipo_cambio_usd"] is None
    assert len(result.errores) == 1


def test_fetch_all_inpc_por_componente_always_present():
    fetcher = MacroFetcher()
    with patch("src.pipeline.macro.requests.get", side_effect=Exception("timeout")):
        result = fetcher.fetch_all()
    # Even on total failure, component estimates are derived from fallback 3.8%
    comps = result.raw["inpc_por_componente"]
    assert set(comps.keys()) == {"energia", "servicios", "mercancias", "alimentos"}
    assert all(v > 0 for v in comps.values())


# ── calcular_indices tests ────────────────────────────────────────────────────

def test_calcular_indices_uses_config_sensibilidad():
    """Higher weight on the high-variation component → higher pressure index."""
    macro = MacroData(
        fetched_at="2026-05-24T00:00:00+00:00",
        raw={
            "inpc_por_componente": {
                "energia": 10.0, "servicios": 1.0, "mercancias": 1.0, "alimentos": 1.0
            },
            "tipo_cambio_usd": None, "tasa_interes": None,
            "inpc_variacion_anual": None, "igae_variacion_anual": None,
            "expectativa_inflacion_12m": None,
        },
        errores=[],
    )
    config_energia_heavy = {"macro_sensibilidad": {
        "energia": 0.70, "servicios": 0.10, "mercancias": 0.10, "alimentos": 0.10,
    }}
    config_servicios_heavy = {"macro_sensibilidad": {
        "energia": 0.10, "servicios": 0.70, "mercancias": 0.10, "alimentos": 0.10,
    }}
    fetcher = MacroFetcher()
    r1 = fetcher.calcular_indices(macro, config_energia_heavy)
    r2 = fetcher.calcular_indices(macro, config_servicios_heavy)
    assert (
        r1.indice_presion_inflacionaria["valor"]
        > r2.indice_presion_inflacionaria["valor"]
    )


def test_presion_inflacionaria_components_sum_correctly():
    macro = MacroData(
        fetched_at="2026-05-24T00:00:00+00:00",
        raw={
            "inpc_por_componente": {
                "energia": 2.1, "servicios": 4.2, "mercancias": 3.1, "alimentos": 5.3
            },
            "tipo_cambio_usd": None, "tasa_interes": None,
            "inpc_variacion_anual": None, "igae_variacion_anual": None,
            "expectativa_inflacion_12m": None,
        },
        errores=[],
    )
    fetcher = MacroFetcher()
    result = fetcher.calcular_indices(macro, _CONFIG)
    comps = result.indice_presion_inflacionaria["componentes"]
    total_contrib = sum(c["contribucion"] for c in comps.values())
    valor = result.indice_presion_inflacionaria["valor"]
    assert abs(total_contrib - valor * 3.0) < 0.01


def test_indice_entorno_economico_between_0_and_1():
    for igae in [-5.0, -1.0, 0.0, 2.0, 5.0, 10.0]:
        macro = MacroData(
            fetched_at="2026-05-24T00:00:00+00:00",
            raw={
                "igae_variacion_anual": {"valor": igae, "fecha": "2026/03"},
                "inpc_por_componente": None, "tipo_cambio_usd": None,
                "tasa_interes": None, "inpc_variacion_anual": None,
                "expectativa_inflacion_12m": None,
            },
            errores=[],
        )
        fetcher = MacroFetcher()
        result = fetcher.calcular_indices(macro, _CONFIG)
        v = result.indice_entorno_economico["valor"]
        assert 0.0 <= v <= 1.0, f"valor={v} out of [0,1] for igae={igae}"


def test_indice_presion_financiera_between_0_and_1():
    for tasa in [0.0, 5.0, 7.0, 9.0, 10.0, 15.0, 20.0]:
        macro = MacroData(
            fetched_at="2026-05-24T00:00:00+00:00",
            raw={
                "tasa_interes": {"valor": tasa, "fecha": "2026/05"},
                "inpc_por_componente": None, "tipo_cambio_usd": None,
                "inpc_variacion_anual": None, "igae_variacion_anual": None,
                "expectativa_inflacion_12m": None,
            },
            errores=[],
        )
        fetcher = MacroFetcher()
        result = fetcher.calcular_indices(macro, _CONFIG)
        v = result.indice_presion_financiera["valor"]
        assert 0.0 <= v <= 1.0, f"valor={v} out of [0,1] for tasa={tasa}"


def test_narrativa_consolidada_nonempty_spanish():
    fetcher = MacroFetcher()
    result = fetcher.calcular_indices(_all_fail_macro(), _CONFIG)
    n = result.narrativa_consolidada
    assert isinstance(n, str) and len(n) > 20
    spanish_markers = ["El", "el", "la", "de", "con", "una", "presión", "entorno"]
    assert any(m in n for m in spanish_markers)


def test_all_interpretacion_values_are_valid():
    fetcher = MacroFetcher()
    result = fetcher.calcular_indices(_all_fail_macro(), _CONFIG)
    assert result.indice_presion_inflacionaria["interpretacion"] in ("alta", "moderada", "baja")
    assert result.indice_entorno_economico["interpretacion"] in ("favorable", "neutral", "adverso")
    assert result.indice_presion_financiera["interpretacion"] in ("alta", "moderada", "baja")


def test_calcular_indices_handles_all_none_values_gracefully():
    fetcher = MacroFetcher()
    result = fetcher.calcular_indices(_all_fail_macro(), _CONFIG)
    assert isinstance(result, MacroIndices)
    assert result.indice_presion_inflacionaria["valor"] >= 0
    assert 0.0 <= result.indice_entorno_economico["valor"] <= 1.0
    assert 0.0 <= result.indice_presion_financiera["valor"] <= 1.0


def test_presion_inflacionaria_alta_when_high_variations():
    macro = MacroData(
        fetched_at="2026-05-24T00:00:00+00:00",
        raw={
            "inpc_por_componente": {
                "energia": 12.0, "servicios": 10.0, "mercancias": 9.0, "alimentos": 11.0
            },
            "tipo_cambio_usd": None, "tasa_interes": None,
            "inpc_variacion_anual": None, "igae_variacion_anual": None,
            "expectativa_inflacion_12m": None,
        },
        errores=[],
    )
    fetcher = MacroFetcher()
    result = fetcher.calcular_indices(macro, _CONFIG)
    assert result.indice_presion_inflacionaria["interpretacion"] == "alta"
    assert result.indice_presion_inflacionaria["valor"] > 1.0


def test_presion_inflacionaria_baja_when_low_variations():
    macro = MacroData(
        fetched_at="2026-05-24T00:00:00+00:00",
        raw={
            "inpc_por_componente": {
                "energia": 0.5, "servicios": 0.3, "mercancias": 0.4, "alimentos": 0.6
            },
            "tipo_cambio_usd": None, "tasa_interes": None,
            "inpc_variacion_anual": None, "igae_variacion_anual": None,
            "expectativa_inflacion_12m": None,
        },
        errores=[],
    )
    fetcher = MacroFetcher()
    result = fetcher.calcular_indices(macro, _CONFIG)
    assert result.indice_presion_inflacionaria["interpretacion"] == "baja"
    assert result.indice_presion_inflacionaria["valor"] < 0.3


def test_entorno_economico_favorable_when_igae_high():
    macro = MacroData(
        fetched_at="2026-05-24T00:00:00+00:00",
        raw={
            "igae_variacion_anual": {"valor": 3.5, "fecha": "2026/03"},
            "inpc_por_componente": None, "tipo_cambio_usd": None,
            "tasa_interes": None, "inpc_variacion_anual": None,
            "expectativa_inflacion_12m": None,
        },
        errores=[],
    )
    fetcher = MacroFetcher()
    result = fetcher.calcular_indices(macro, _CONFIG)
    assert result.indice_entorno_economico["interpretacion"] == "favorable"


def test_entorno_economico_adverso_when_igae_negative():
    macro = MacroData(
        fetched_at="2026-05-24T00:00:00+00:00",
        raw={
            "igae_variacion_anual": {"valor": -2.0, "fecha": "2026/03"},
            "inpc_por_componente": None, "tipo_cambio_usd": None,
            "tasa_interes": None, "inpc_variacion_anual": None,
            "expectativa_inflacion_12m": None,
        },
        errores=[],
    )
    fetcher = MacroFetcher()
    result = fetcher.calcular_indices(macro, _CONFIG)
    assert result.indice_entorno_economico["interpretacion"] == "adverso"


def test_presion_financiera_alta_when_high_rate():
    macro = MacroData(
        fetched_at="2026-05-24T00:00:00+00:00",
        raw={
            "tasa_interes": {"valor": 11.5, "fecha": "2026/05"},
            "inpc_por_componente": None, "tipo_cambio_usd": None,
            "inpc_variacion_anual": None, "igae_variacion_anual": None,
            "expectativa_inflacion_12m": None,
        },
        errores=[],
    )
    fetcher = MacroFetcher()
    result = fetcher.calcular_indices(macro, _CONFIG)
    assert result.indice_presion_financiera["interpretacion"] == "alta"


def test_presion_financiera_baja_when_low_rate():
    macro = MacroData(
        fetched_at="2026-05-24T00:00:00+00:00",
        raw={
            "tasa_interes": {"valor": 4.0, "fecha": "2026/05"},
            "inpc_por_componente": None, "tipo_cambio_usd": None,
            "inpc_variacion_anual": None, "igae_variacion_anual": None,
            "expectativa_inflacion_12m": None,
        },
        errores=[],
    )
    fetcher = MacroFetcher()
    result = fetcher.calcular_indices(macro, _CONFIG)
    assert result.indice_presion_financiera["interpretacion"] == "baja"


def test_calcular_indices_returns_macro_indices_instance():
    fetcher = MacroFetcher()
    result = fetcher.calcular_indices(_all_fail_macro(), _CONFIG)
    assert isinstance(result, MacroIndices)
    assert "valor" in result.indice_presion_inflacionaria
    assert "valor" in result.indice_entorno_economico
    assert "valor" in result.indice_presion_financiera
