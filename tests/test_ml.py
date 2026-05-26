import pytest
import numpy as np
from pathlib import Path

from src.pipeline.parsers.parser_bd import BDData, parse_bd
from src.ml.features import build_features, get_feature_names, FEATURE_NAMES
from src.ml.trainer import train, TrainedModel
from src.ml.predictor import predict_and_explain, load_model, PredictionReport

FIXTURES = Path(__file__).parent / "fixtures"


# ── module-scoped fixtures (train + SHAP once per session) ────────────────────

@pytest.fixture(scope="module")
def bd():
    return parse_bd(str(FIXTURES / "sample_bd.csv"))


@pytest.fixture(scope="module")
def trained(bd):
    return train(bd)


@pytest.fixture(scope="module")
def report(trained, bd):
    return predict_and_explain(trained, bd)


# ── build_features ────────────────────────────────────────────────────────────

def test_build_features_correct_number_of_features(bd):
    X, y = build_features(bd)
    assert X.shape[1] == 9
    assert X.columns.tolist() == get_feature_names()


def test_build_features_feature_names_match_constant(bd):
    X, _ = build_features(bd)
    assert list(X.columns) == FEATURE_NAMES


def test_build_features_drops_nonpositive_multiplicador():
    bad_reg = _make_registro(mult=-0.8, utilidad=-400.0, costo=500.0)
    bd_bad = BDData(
        meses=["ENERO 2026"], sucursales=["ANT"], categorias=["Alimentos"],
        registros=[_make_registro(), bad_reg],
    )
    X, y = build_features(bd_bad)
    assert len(X) == 1  # only the valid row
    assert (y > 0).all()


def test_build_features_drops_zero_precio_unitario():
    zero_sub = _make_registro(subtotal=0.0)
    bd_bad = BDData(
        meses=["ENERO 2026"], sucursales=["ANT"], categorias=["Alimentos"],
        registros=[_make_registro(), zero_sub],
    )
    X, y = build_features(bd_bad)
    assert len(X) == 1


def test_build_features_caps_outliers_at_99th_percentile():
    extreme = _make_registro(utilidad=999900.0, costo=100.0, mult=9999.0, subtotal=1_000_000.0)
    bd_ext = BDData(
        meses=["ENERO 2026"], sucursales=["ANT"], categorias=["Alimentos"],
        registros=[_make_registro()] * 50 + [extreme],
    )
    _, y = build_features(bd_ext)
    assert y.max() < 9999.0


def test_build_features_all_rows_from_fixture(bd):
    X, y = build_features(bd)
    assert len(X) == len(bd.registros)
    assert len(y) == len(bd.registros)


# ── train ─────────────────────────────────────────────────────────────────────

def test_train_returns_trained_model(trained):
    assert isinstance(trained, TrainedModel)


def test_train_metrics_fields_present(trained):
    for key in ("rmse", "mae", "r2", "n_samples"):
        assert key in trained.train_metrics


def test_train_metrics_r2_positive(trained):
    assert trained.train_metrics["r2"] > 0


def test_train_feature_names_correct(trained):
    assert trained.feature_names == FEATURE_NAMES


def test_train_label_encoders_present(trained):
    for col in ("sucursal", "categoria", "tag_menu_1"):
        assert col in trained.label_encoders


def test_train_saves_model_to_path(bd, tmp_path):
    save_file = str(tmp_path / "model.pkl")
    tm = train(bd, save_path=save_file)
    assert Path(save_file).exists()


# ── predict_and_explain ───────────────────────────────────────────────────────

def test_predict_returns_one_entry_per_sku_row(report, bd):
    assert len(report.por_sku) == len(bd.registros)


def test_shap_values_cover_all_features(report):
    first = report.por_sku[0]
    assert set(first["shap_values"].keys()) == set(FEATURE_NAMES)


def test_shap_additivity(report):
    """SHAP guarantee: sum(shap_values) ≈ prediction − base_value."""
    base = report.global_["shap_base_value"]
    for item in report.por_sku[:10]:
        shap_sum = sum(item["shap_values"].values())
        diff = item["multiplicador_predicho"] - base
        assert abs(shap_sum - diff) < 0.05


def test_shap_top_positivo_is_max_shap(report):
    for item in report.por_sku[:10]:
        sv = item["shap_values"]
        assert sv[item["shap_top_positivo"]] == max(sv.values())


def test_shap_top_negativo_is_min_shap(report):
    for item in report.por_sku[:10]:
        sv = item["shap_values"]
        assert sv[item["shap_top_negativo"]] == min(sv.values())


def test_por_sucursal_mes_keys_match_bd(report, bd):
    expected = {f"{r['sucursal']}_{r['mes']}" for r in bd.registros}
    assert set(report.por_sucursal_mes.keys()) == expected


def test_shap_importancia_covers_all_features(report):
    assert set(report.global_["shap_importancia"].keys()) == set(FEATURE_NAMES)


def test_top_3_factores_length(report):
    assert len(report.global_["top_3_factores"]) == 3


# ── load_model ────────────────────────────────────────────────────────────────

def test_load_model_returns_trained_model(bd, tmp_path):
    save_file = str(tmp_path / "saved.pkl")
    original = train(bd, save_path=save_file)
    loaded = load_model(save_file)
    assert isinstance(loaded, TrainedModel)
    assert loaded.feature_names == original.feature_names
    assert loaded.train_metrics == original.train_metrics


def test_load_model_can_predict(bd, tmp_path):
    save_file = str(tmp_path / "saved2.pkl")
    train(bd, save_path=save_file)
    loaded = load_model(save_file)
    report = predict_and_explain(loaded, bd)
    assert len(report.por_sku) == len(bd.registros)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_registro(
    mult=9.0, utilidad=7200.0, costo=800.0, subtotal=8000.0, cantidad=50
) -> dict:
    return {
        "mes": "ENERO 2026", "sucursal": "ANT", "categoria": "Alimentos",
        "sku": "DONBURI", "cantidad": cantidad, "subtotal": subtotal,
        "total": subtotal * 1.16, "costo_sin_iva": costo,
        "costo_con_iva": costo * 1.16, "utilidad_bruta": utilidad,
        "margen_bruto": utilidad / subtotal if subtotal else 0.0,
        "multiplicador_eficiencia": mult,
        "tag_menu_1": "CALIENTE", "tag_menu_2": "CALIENTE",
    }
