import os
import pickle
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from xgboost import XGBRegressor

from ..pipeline.parsers.parser_bd import BDData
from ..pipeline.parsers.parser_utils import month_sort_key
from .features import (
    calc_category_stats,
    extract_features,
    fit_label_encoders,
    get_feature_names,
)


@dataclass
class TrainedModel:
    model: Any
    feature_names: List[str]
    label_encoders: Dict[str, Any]
    category_stats: Dict[str, Dict[str, float]]
    train_metrics: Dict[str, float]
    trained_at: str


def train(bd_data: BDData, save_path: Optional[str] = None) -> TrainedModel:
    registros = [
        r for r in bd_data.registros
        if r["multiplicador_eficiencia"] > 0
        and r["cantidad"] > 0
        and r["subtotal"] / r["cantidad"] > 0
    ]
    if not registros:
        raise ValueError("No valid training records after filtering")

    meses = sorted(set(r["mes"] for r in registros), key=month_sort_key)

    if len(meses) >= 2:
        test_mes = meses[-1]
        train_regs = [r for r in registros if r["mes"] != test_mes]
        test_regs = [r for r in registros if r["mes"] == test_mes]
    else:
        train_regs = registros
        test_regs = registros

    category_stats = calc_category_stats(train_regs)
    label_encoders = fit_label_encoders(train_regs)

    # Extend encoders with any labels seen only in test set
    for col, attr in [("sucursal", "sucursal"), ("categoria", "categoria")]:
        le = label_encoders[col]
        new = sorted({r[col] for r in test_regs} - set(le.classes_))
        if new:
            le.classes_ = np.array(sorted(list(le.classes_) + new))
    tag_le = label_encoders["tag_menu_1"]
    new_tags = sorted(
        {r["tag_menu_1"] if r["tag_menu_1"] else "OTRO" for r in test_regs} - set(tag_le.classes_)
    )
    if new_tags:
        tag_le.classes_ = np.array(sorted(list(tag_le.classes_) + new_tags))

    X_train = extract_features(train_regs, label_encoders, category_stats)
    X_test = extract_features(test_regs, label_encoders, category_stats)

    cap_99 = float(np.percentile([r["multiplicador_eficiencia"] for r in train_regs], 99))
    y_train = np.array([min(r["multiplicador_eficiencia"], cap_99) for r in train_regs])
    y_test = np.array([min(r["multiplicador_eficiencia"], cap_99) for r in test_regs])

    model = XGBRegressor(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test).astype(float)
    metrics = {
        "rmse": float(np.sqrt(mean_squared_error(y_test, y_pred))),
        "mae": float(mean_absolute_error(y_test, y_pred)),
        "r2": float(r2_score(y_test, y_pred)),
        "n_samples": len(train_regs),
    }

    trained = TrainedModel(
        model=model,
        feature_names=get_feature_names(),
        label_encoders=label_encoders,
        category_stats=category_stats,
        train_metrics=metrics,
        trained_at=datetime.now(timezone.utc).isoformat(),
    )

    if save_path:
        dir_path = os.path.dirname(save_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        with open(save_path, "wb") as fh:
            pickle.dump(trained, fh)

    return trained
