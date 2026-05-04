"""Unit tests for arithmetic validation logic."""
import copy
import pytest

from ..validator import validate
from ..utils import almost_equal
from .fixtures import build_normalized_doc, TOTAL_VENTAS, UTILIDAD_BRUTA, EBITDA


class TestAlmostEqual:
    def test_exact(self):
        assert almost_equal(100.0, 100.0)

    def test_within_tolerance(self):
        assert almost_equal(100.0, 101.5)  # 1.5% diff

    def test_outside_tolerance(self):
        assert not almost_equal(100.0, 103.0)  # 3% diff

    def test_both_zero(self):
        assert almost_equal(0.0, 0.0)

    def test_one_zero(self):
        # any non-zero vs 0 fails
        assert not almost_equal(0.0, 100.0)


class TestValidateConsistentDoc:
    def test_valid_fixture_passes(self):
        doc = build_normalized_doc()
        result = validate(doc)
        assert result["valid"], f"Expected valid, got errors: {result['errors']}"
        assert result["errors"] == []

    def test_warnings_may_exist(self):
        doc = build_normalized_doc()
        result = validate(doc)
        # warnings are informational; valid should still be True
        assert result["valid"]


class TestValidateVentasSublineMismatch:
    def test_subline_mismatch_raises_error(self):
        doc = build_normalized_doc()
        # Corrupt Alimentos in group A so sublines don't sum to total
        doc["meses"]["ENERO 2026"]["ventas"]["A"]["Alimentos"] += 500_000.0
        result = validate(doc)
        assert not result["valid"]
        assert any("ventas[A]" in e for e in result["errors"])

    def test_total_ventas_mismatch_raises_error(self):
        doc = build_normalized_doc()
        doc["meses"]["ENERO 2026"]["kpis"]["total_ventas"] += 1_000_000.0
        result = validate(doc)
        assert not result["valid"]


class TestValidateKPIs:
    def test_utilidad_bruta_mismatch(self):
        doc = build_normalized_doc()
        doc["meses"]["ENERO 2026"]["kpis"]["utilidad_bruta"] += 500_000.0
        result = validate(doc)
        assert not result["valid"]
        assert any("utilidad_bruta" in e for e in result["errors"])

    def test_ebitda_mismatch(self):
        doc = build_normalized_doc()
        doc["meses"]["ENERO 2026"]["kpis"]["ebitda"] += 300_000.0
        result = validate(doc)
        assert not result["valid"]
        assert any("ebitda" in e for e in result["errors"])

    def test_zero_ventas_skips_margin_check(self):
        doc = build_normalized_doc()
        mes = doc["meses"]["ENERO 2026"]
        for grp in mes["ventas"].values():
            for k in grp:
                grp[k] = 0.0
        for k in mes["kpis"]:
            mes["kpis"][k] = 0.0
        result = validate(doc)
        assert result["valid"]


class TestEmptyDocument:
    def test_empty_meses_is_valid(self):
        doc = {
            "periodo": "2026",
            "fuente": "excel",
            "cliente_id": "test",
            "meses": {},
        }
        result = validate(doc)
        assert result["valid"]
        assert result["errors"] == []
