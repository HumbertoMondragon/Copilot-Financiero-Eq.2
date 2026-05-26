from dataclasses import dataclass
from typing import Any, Dict, List

from ..ml.predictor import PredictionReport

_TEMPLATES: Dict[str, Dict[str, str]] = {
    "costo_unitario": {
        "positivo": "El costo unitario relativamente bajo impulsa el multiplicador en {val:.2f} puntos.",
        "negativo": "El costo unitario elevado reduce el multiplicador en {val:.2f} puntos.",
    },
    "precio_unitario": {
        "positivo": "El precio de venta impulsa el multiplicador en {val:.2f} puntos.",
        "negativo": "El precio de venta bajo reduce el multiplicador en {val:.2f} puntos.",
    },
    "costo_vs_categoria_avg": {
        "positivo": "El costo por debajo del promedio de la categoría aporta {val:.2f} puntos.",
        "negativo": "El costo por encima del promedio de la categoría arrastra el multiplicador en {val:.2f} puntos.",
    },
    "precio_vs_categoria_avg": {
        "positivo": "El precio por encima del promedio de la categoría aporta {val:.2f} puntos.",
        "negativo": "El precio por debajo del promedio de la categoría reduce el multiplicador en {val:.2f} puntos.",
    },
    "sucursal": {
        "positivo": "El efecto de la sucursal contribuye positivamente con {val:.2f} puntos.",
        "negativo": "El efecto de la sucursal reduce el multiplicador en {val:.2f} puntos.",
    },
    "categoria": {
        "positivo": "La categoría contribuye positivamente con {val:.2f} puntos.",
        "negativo": "La categoría arrastra el multiplicador en {val:.2f} puntos.",
    },
}

_DEFAULT: Dict[str, str] = {
    "positivo": "El factor '{feature}' aporta {val:.2f} puntos al multiplicador.",
    "negativo": "El factor '{feature}' reduce el multiplicador en {val:.2f} puntos.",
}


@dataclass
class SHAPNarrative:
    por_sucursal_mes: Dict[str, Any]
    global_: Dict[str, Any]


def get_magnitud(shap_val: float) -> str:
    a = abs(shap_val)
    if a > 0.5:
        return "alta"
    elif a >= 0.2:
        return "media"
    return "baja"


def get_direccion(shap_val: float) -> str:
    return "positivo" if shap_val >= 0 else "negativo"


def _describe(feature: str, shap_val: float) -> str:
    dir_ = get_direccion(shap_val)
    abs_val = abs(shap_val)
    tmpl = _TEMPLATES.get(feature, _DEFAULT)
    return tmpl[dir_].format(val=abs_val, feature=feature)


def _top_factores(shap_promedio: Dict[str, float], n: int = 3) -> List[Dict]:
    ranked = sorted(shap_promedio.items(), key=lambda x: -abs(x[1]))
    return [
        {
            "feature": feat,
            "shap": round(val, 4),
            "direccion": get_direccion(val),
            "magnitud": get_magnitud(val),
            "descripcion": _describe(feat, val),
        }
        for feat, val in ranked[:n]
    ]


def _narrativa_sucursal_mes(key: str, factores: List[Dict]) -> str:
    parts = key.split("_", 1)
    suc, mes = parts[0], parts[1] if len(parts) > 1 else ""
    negs = [f for f in factores if f["direccion"] == "negativo"]
    pos = [f for f in factores if f["direccion"] == "positivo"]
    sentences: List[str] = []
    if negs:
        f = negs[0]
        sentences.append(
            f"En {suc} durante {mes}, el factor que más impacta negativamente el "
            f"multiplicador de eficiencia es {f['feature']}, "
            f"arrastrando {abs(f['shap']):.2f} puntos."
        )
    if pos:
        f = pos[0]
        sentences.append(
            f"El factor {f['feature']} contribuye positivamente con {abs(f['shap']):.2f} puntos."
        )
    if not sentences:
        sentences.append(f"En {suc} durante {mes}, el impacto de los factores es equilibrado.")
    return " ".join(sentences)


def translate_shap(prediction_report: PredictionReport, config: Dict) -> SHAPNarrative:
    por_sucursal_mes: Dict[str, Any] = {}
    for key, data in prediction_report.por_sucursal_mes.items():
        factores = _top_factores(data["shap_promedio"])
        por_sucursal_mes[key] = {
            "narrativa": _narrativa_sucursal_mes(key, factores),
            "factores": factores,
        }

    importancia = prediction_report.global_["shap_importancia"]
    top3 = prediction_report.global_["top_3_factores"]
    top_feat = max(importancia, key=importancia.get)

    global_narrativa = (
        f"El factor más influyente en el multiplicador de eficiencia del portafolio es "
        f"{top_feat} con importancia media absoluta de {importancia[top_feat]:.4f}. "
        f"Los tres factores principales son: {', '.join(top3)}."
    )

    top_3_desc = [
        {
            "feature": feat,
            "importancia": round(importancia[feat], 4),
            "descripcion": _TEMPLATES.get(feat, _DEFAULT)["positivo"].format(
                val=importancia[feat], feature=feat
            ),
        }
        for feat in top3
    ]

    return SHAPNarrative(
        por_sucursal_mes=por_sucursal_mes,
        global_={"narrativa": global_narrativa, "top_3_factores_descripcion": top_3_desc},
    )
