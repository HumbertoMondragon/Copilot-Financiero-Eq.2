from dataclasses import dataclass
from typing import Any, Dict, List

from .parsers.parser_bd import BDData
from .parsers.parser_er import ERData
from .parsers.parser_utils import month_sort_key


@dataclass
class FinancialData:
    meses: List[str]
    por_mes: Dict[str, Any]


def integrate(bd_data: BDData, er_data: ERData) -> FinancialData:
    common_meses = sorted(
        set(bd_data.meses) & set(er_data.meses),
        key=month_sort_key,
    )

    por_mes: Dict[str, Any] = {}

    for mes in common_meses:
        registros = [r for r in bd_data.registros if r["mes"] == mes]

        por_sucursal: Dict[str, Any] = {}
        for r in registros:
            suc = r["sucursal"]
            if suc not in por_sucursal:
                por_sucursal[suc] = {
                    "revenue": 0.0,
                    "costo_directo": 0.0,
                    "utilidad_bruta": 0.0,
                    "por_categoria": {},
                }
            por_sucursal[suc]["revenue"] += r["subtotal"]
            por_sucursal[suc]["costo_directo"] += r["costo_sin_iva"]
            por_sucursal[suc]["utilidad_bruta"] += r["utilidad_bruta"]

            cat = r["categoria"]
            cat_map = por_sucursal[suc]["por_categoria"]
            if cat not in cat_map:
                cat_map[cat] = {"revenue": 0.0, "costo": 0.0, "utilidad": 0.0, "margen": 0.0, "unidades": 0}
            cat_map[cat]["revenue"] += r["subtotal"]
            cat_map[cat]["costo"] += r["costo_sin_iva"]
            cat_map[cat]["utilidad"] += r["utilidad_bruta"]
            cat_map[cat]["unidades"] += r["cantidad"]

        for sdata in por_sucursal.values():
            rev = sdata["revenue"]
            sdata["margen_bruto"] = sdata["utilidad_bruta"] / rev if rev else 0.0
            for cdata in sdata["por_categoria"].values():
                c_rev = cdata["revenue"]
                cdata["margen"] = cdata["utilidad"] / c_rev if c_rev else 0.0

        total_revenue = sum(s["revenue"] for s in por_sucursal.values())
        total_costo = sum(s["costo_directo"] for s in por_sucursal.values())
        utilidad_bruta_bd = sum(s["utilidad_bruta"] for s in por_sucursal.values())

        por_mes[mes] = {
            "total_revenue": total_revenue,
            "total_costo_directo": total_costo,
            "utilidad_bruta_bd": utilidad_bruta_bd,
            "por_sucursal": por_sucursal,
            "por_sku": registros,
            "gastos_operativos": er_data.gastos_operativos.get(mes, {}),
        }

    return FinancialData(meses=common_meses, por_mes=por_mes)
