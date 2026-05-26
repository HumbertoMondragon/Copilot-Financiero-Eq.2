import pickle
from dataclasses import dataclass
from typing import Any, Dict, List

import numpy as np

from ..pipeline.parsers.parser_bd import BDData
from .features import extract_features
from .trainer import TrainedModel


@dataclass
class PredictionReport:
    por_sku: List[Dict]
    por_sucursal_mes: Dict[str, Dict]
    global_: Dict
    train_metrics: Dict


def predict_and_explain(trained_model: TrainedModel, bd_data: BDData) -> PredictionReport:
    registros = bd_data.registros
    if not registros:
        return PredictionReport(por_sku=[], por_sucursal_mes={}, global_={}, train_metrics={})

    X = extract_features(registros, trained_model.label_encoders, trained_model.category_stats)
    predictions = trained_model.model.predict(X).astype(float)

    import shap
    explainer = shap.TreeExplainer(trained_model.model)
    shap_arr = np.array(explainer.shap_values(X))   # (n_samples, n_features)
    base_value = float(explainer.expected_value)

    feature_names = trained_model.feature_names

    # per-SKU records
    por_sku: List[Dict] = []
    for i, r in enumerate(registros):
        shap_dict = {feat: float(shap_arr[i, j]) for j, feat in enumerate(feature_names)}
        por_sku.append({
            "sku": r["sku"],
            "sucursal": r["sucursal"],
            "categoria": r["categoria"],
            "mes": r["mes"],
            "multiplicador_real": float(r["multiplicador_eficiencia"]),
            "multiplicador_predicho": float(predictions[i]),
            "shap_values": shap_dict,
            "shap_top_positivo": max(shap_dict, key=shap_dict.get),
            "shap_top_negativo": min(shap_dict, key=shap_dict.get),
        })

    # aggregate by sucursal+mes
    suc_mes_rows: Dict[str, List[int]] = {}
    for i, r in enumerate(registros):
        key = f"{r['sucursal']}_{r['mes']}"
        suc_mes_rows.setdefault(key, []).append(i)

    por_sucursal_mes: Dict[str, Dict] = {}
    for key, idxs in suc_mes_rows.items():
        avg = np.mean(shap_arr[idxs], axis=0)
        shap_promedio = {feat: float(avg[j]) for j, feat in enumerate(feature_names)}
        por_sucursal_mes[key] = {
            "shap_promedio": shap_promedio,
            "factor_mas_positivo": max(shap_promedio, key=shap_promedio.get),
            "factor_mas_negativo": min(shap_promedio, key=shap_promedio.get),
        }

    # global importance
    mean_abs = np.mean(np.abs(shap_arr), axis=0)
    shap_importancia = {feat: float(mean_abs[j]) for j, feat in enumerate(feature_names)}
    top_3 = sorted(shap_importancia, key=shap_importancia.get, reverse=True)[:3]

    return PredictionReport(
        por_sku=por_sku,
        por_sucursal_mes=por_sucursal_mes,
        global_={
            "shap_importancia": shap_importancia,
            "top_3_factores": top_3,
            "shap_base_value": base_value,
        },
        train_metrics=trained_model.train_metrics,
    )


def load_model(path: str) -> TrainedModel:
    with open(path, "rb") as fh:
        return pickle.load(fh)
