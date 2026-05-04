from typing import Any
from .utils import almost_equal
from .profiles import GROUPS

ValidationResult = dict  # {"valid": bool, "errors": list, "warnings": list}


def validate(normalized: dict) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    for mes_label, mes in normalized.get("meses", {}).items():
        ctx = f"[{mes_label}]"
        _check_ventas(mes, ctx, errors, warnings)
        _check_kpis(mes, ctx, errors, warnings)

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def _check_ventas(mes: dict, ctx: str, errors: list, warnings: list) -> None:
    ventas = mes.get("ventas", {})
    running_total = 0.0

    for group in GROUPS:
        g = ventas.get(group, {})
        if not g:
            continue
        total = g.get("total", 0.0)
        subline_sum = sum(v for k, v in g.items() if k != "total")
        if subline_sum != 0 and not almost_equal(total, subline_sum):
            errors.append(
                f"{ctx} ventas[{group}]: sublines sum {subline_sum:.2f} != total {total:.2f}"
            )
        running_total += total

    kpis = mes.get("kpis", {})
    reported_total = kpis.get("total_ventas", 0.0)
    if reported_total != 0 and not almost_equal(reported_total, running_total):
        errors.append(
            f"{ctx} total_ventas {reported_total:.2f} != sum of group totals {running_total:.2f}"
        )


def _check_kpis(mes: dict, ctx: str, errors: list, warnings: list) -> None:
    k = mes.get("kpis", {})

    tv = k.get("total_ventas", 0.0)
    tc = k.get("total_costo", 0.0)
    ub = k.get("utilidad_bruta", 0.0)
    if tv != 0:
        expected_ub = tv - tc
        if not almost_equal(ub, expected_ub):
            errors.append(
                f"{ctx} utilidad_bruta {ub:.2f} != total_ventas - total_costo ({expected_ub:.2f})"
            )
        mb = k.get("margen_bruto", 0.0)
        expected_mb = ub / tv if tv else 0.0
        if not almost_equal(mb, expected_mb):
            warnings.append(
                f"{ctx} margen_bruto {mb:.4f} != utilidad_bruta/total_ventas ({expected_mb:.4f})"
            )

    tgo = k.get("total_gastos_operacion", 0.0)
    ebitda = k.get("ebitda", 0.0)
    if ub != 0:
        expected_ebitda = ub - tgo
        if not almost_equal(ebitda, expected_ebitda):
            errors.append(
                f"{ctx} ebitda {ebitda:.2f} != utilidad_bruta - total_gastos_operacion ({expected_ebitda:.2f})"
            )
        if tv != 0:
            me = k.get("margen_ebitda", 0.0)
            expected_me = ebitda / tv
            if not almost_equal(me, expected_me):
                warnings.append(
                    f"{ctx} margen_ebitda {me:.4f} != ebitda/total_ventas ({expected_me:.4f})"
                )

    nomina = k.get("nomina", 0.0)
    gc = k.get("gastos_comerciales", 0.0)
    go = k.get("gastos_operativos", 0.0)
    ga = k.get("gastos_administrativos", 0.0)
    viat = k.get("viaticos", 0.0)
    expected_tgo = nomina + gc + go + ga + viat
    if expected_tgo != 0 and not almost_equal(tgo, expected_tgo):
        warnings.append(
            f"{ctx} total_gastos_operacion {tgo:.2f} != component sum {expected_tgo:.2f}"
        )
