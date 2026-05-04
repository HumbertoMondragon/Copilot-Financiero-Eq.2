from typing import Dict, Any

# Each profile: hint (injected into LLM prompt), synonyms (their names → canonical),
# scale (multiply all values by this factor, e.g. 1000 if they report in thousands).
PROFILES: Dict[str, Dict[str, Any]] = {
    "default": {
        "hint": "",
        "synonyms": {},
        "scale": 1.0,
    },
}

VENTAS_SUBLINES = ["Alimentos", "Bebidas", "Cafe_Inf", "Destilados", "Vinos"]
GROUPS = ["A", "B", "C", "D", "E"]


def get_profile(cliente_id: str) -> Dict[str, Any]:
    return PROFILES.get(cliente_id, PROFILES["default"])


def resolve_synonym(name: str, synonyms: Dict[str, str]) -> str:
    return synonyms.get(name, synonyms.get(name.upper(), name))


def empty_ventas_group() -> dict:
    return {"total": 0.0, "Alimentos": 0.0, "Bebidas": 0.0, "Cafe_Inf": 0.0,
            "Destilados": 0.0, "Vinos": 0.0}


def empty_egresos_group() -> dict:
    return {"total": 0.0, "Alimentos": 0.0, "Bebidas": 0.0, "Cafe_Inf": 0.0,
            "Destilados": 0.0, "Vinos": 0.0}


def empty_kpis() -> dict:
    return {
        "total_ventas": 0.0,
        "total_costo": 0.0,
        "margen_costo": 0.0,
        "utilidad_bruta": 0.0,
        "margen_bruto": 0.0,
        "nomina": 0.0,
        "gastos_comerciales": 0.0,
        "gastos_operativos": 0.0,
        "gastos_administrativos": 0.0,
        "viaticos": 0.0,
        "total_gastos_operacion": 0.0,
        "margen_operacion": 0.0,
        "ebitda": 0.0,
        "margen_ebitda": 0.0,
        "gastos_financieros": 0.0,
        "costo_integral_financiamiento": 0.0,
        "impuestos": 0.0,
        "utilidad_neta": 0.0,
        "margen_neto": 0.0,
    }


def empty_month() -> dict:
    return {
        "ventas": {g: empty_ventas_group() for g in GROUPS},
        "egresos": {g: empty_egresos_group() for g in GROUPS},
        "kpis": empty_kpis(),
    }
