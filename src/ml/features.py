from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder

from ..pipeline.parsers.parser_bd import BDData
from ..pipeline.parsers.parser_utils import MONTH_ORDER

FEATURE_NAMES: List[str] = [
    "sucursal",
    "categoria",
    "tag_menu_1",
    "precio_unitario",
    "costo_unitario",
    "mes_num",
    "log_cantidad",
    "precio_vs_categoria_avg",
    "costo_vs_categoria_avg",
]


def get_feature_names() -> List[str]:
    return list(FEATURE_NAMES)


def calc_category_stats(registros: List[dict]) -> Dict[str, Dict[str, float]]:
    cat_precios: Dict[str, List[float]] = {}
    cat_costos: Dict[str, List[float]] = {}
    for r in registros:
        qty = r["cantidad"]
        if qty <= 0:
            continue
        cat = r["categoria"]
        cat_precios.setdefault(cat, []).append(r["subtotal"] / qty)
        cat_costos.setdefault(cat, []).append(r["costo_sin_iva"] / qty)
    cats = set(cat_precios) | set(cat_costos)
    return {
        cat: {
            "mean_precio": float(np.mean(cat_precios[cat])) if cat in cat_precios else 1.0,
            "mean_costo": float(np.mean(cat_costos[cat])) if cat in cat_costos else 1.0,
        }
        for cat in cats
    }


def fit_label_encoders(registros: List[dict]) -> Dict[str, LabelEncoder]:
    sucursales = [r["sucursal"] for r in registros]
    categorias = [r["categoria"] for r in registros]
    tags = [r["tag_menu_1"] if r["tag_menu_1"] else "OTRO" for r in registros]
    encoders: Dict[str, LabelEncoder] = {}
    for col, values in [("sucursal", sucursales), ("categoria", categorias), ("tag_menu_1", tags)]:
        le = LabelEncoder()
        le.fit(sorted(set(values)))
        encoders[col] = le
    return encoders


def extract_features(
    registros: List[dict],
    label_encoders: Dict[str, LabelEncoder],
    category_stats: Dict[str, Dict[str, float]],
) -> pd.DataFrame:
    rows = []
    for r in registros:
        qty = r["cantidad"]
        precio_unitario = r["subtotal"] / qty if qty > 0 else 0.0
        costo_unitario = r["costo_sin_iva"] / qty if qty > 0 else 0.0

        tag = r["tag_menu_1"] if r["tag_menu_1"] else "OTRO"
        parts = r["mes"].split()
        mes_num = float(MONTH_ORDER.get(parts[0], 0)) if parts else 0.0

        cstat = category_stats.get(r["categoria"], {"mean_precio": 1.0, "mean_costo": 1.0})
        mp = cstat["mean_precio"] or 1.0
        mc = cstat["mean_costo"] or 1.0

        rows.append({
            "sucursal": r["sucursal"],
            "categoria": r["categoria"],
            "tag_menu_1": tag,
            "precio_unitario": precio_unitario,
            "costo_unitario": costo_unitario,
            "mes_num": mes_num,
            "log_cantidad": float(np.log(qty + 1)),
            "precio_vs_categoria_avg": precio_unitario / mp,
            "costo_vs_categoria_avg": costo_unitario / mc,
        })

    df = pd.DataFrame(rows, columns=FEATURE_NAMES)

    for col in ("sucursal", "categoria", "tag_menu_1"):
        le = label_encoders[col]
        known = set(le.classes_)
        df[col] = [float(le.transform([v])[0]) if v in known else 0.0 for v in df[col]]

    return df.astype(float)


def build_features(bd_data: BDData) -> Tuple[pd.DataFrame, pd.Series]:
    registros = [
        r for r in bd_data.registros
        if r["multiplicador_eficiencia"] > 0
        and r["cantidad"] > 0
        and r["subtotal"] / r["cantidad"] > 0
    ]
    if not registros:
        return pd.DataFrame(columns=FEATURE_NAMES), pd.Series(dtype=float)

    mults = np.array([r["multiplicador_eficiencia"] for r in registros], dtype=float)
    cap_99 = float(np.percentile(mults, 99))

    category_stats = calc_category_stats(registros)
    label_encoders = fit_label_encoders(registros)

    X = extract_features(registros, label_encoders, category_stats)
    y = pd.Series(
        [min(r["multiplicador_eficiencia"], cap_99) for r in registros],
        name="multiplicador_eficiencia",
    )
    return X, y
