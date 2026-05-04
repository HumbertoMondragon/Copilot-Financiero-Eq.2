"""
Synthetic, arithmetically consistent P&L data for tests.

One month: ENERO 2026
Groups A–E each have ventas sublines that sum to group total.
KPIs are fully consistent.
"""

# --- Ventas (5 groups) ---
# Group totals and sublines
VENTAS = {
    "A": {"Alimentos": 2_318_182.87, "Bebidas": 416_592.10, "Cafe_Inf": 27_135.50,
          "Destilados": 312_036.99, "Vinos": 90_831.26},
    "B": {"Alimentos": 1_850_000.00, "Bebidas": 320_000.00, "Cafe_Inf": 18_500.00,
          "Destilados": 210_000.00, "Vinos": 65_000.00},
    "C": {"Alimentos": 980_000.00, "Bebidas": 145_000.00, "Cafe_Inf": 9_200.00,
          "Destilados": 85_000.00, "Vinos": 32_000.00},
    "D": {"Alimentos": 560_000.00, "Bebidas": 92_000.00, "Cafe_Inf": 5_100.00,
          "Destilados": 44_000.00, "Vinos": 18_900.00},
    "E": {"Alimentos": 310_000.00, "Bebidas": 55_000.00, "Cafe_Inf": 3_800.00,
          "Destilados": 28_000.00, "Vinos": 12_200.00},
}

for grp in VENTAS:
    VENTAS[grp]["total"] = round(sum(v for k, v in VENTAS[grp].items() if k != "total"), 2)

TOTAL_VENTAS = round(sum(g["total"] for g in VENTAS.values()), 2)

# --- Egresos (cost of goods) — same subline structure as ventas ---
EGRESOS = {
    "A": {"Alimentos": 780_000.00, "Bebidas": 240_000.00, "Cafe_Inf": 60_000.00,
          "Destilados": 80_000.00, "Vinos": 40_000.00},
    "B": {"Alimentos": 570_000.00, "Bebidas": 180_000.00, "Cafe_Inf": 45_000.00,
          "Destilados": 65_000.00, "Vinos": 30_000.00},
    "C": {"Alimentos": 275_000.00, "Bebidas": 88_000.00, "Cafe_Inf": 22_000.00,
          "Destilados": 32_000.00, "Vinos": 13_000.00},
    "D": {"Alimentos": 140_000.00, "Bebidas": 44_000.00, "Cafe_Inf": 12_000.00,
          "Destilados": 16_000.00, "Vinos": 8_000.00},
    "E": {"Alimentos": 82_000.00, "Bebidas": 26_000.00, "Cafe_Inf": 7_000.00,
          "Destilados": 10_000.00, "Vinos": 5_000.00},
}

for grp in EGRESOS:
    EGRESOS[grp]["total"] = round(sum(v for k, v in EGRESOS[grp].items() if k != "total"), 2)

TOTAL_COSTO = round(sum(g["total"] for g in EGRESOS.values()), 2)

# --- P&L derivations ---
UTILIDAD_BRUTA = round(TOTAL_VENTAS - TOTAL_COSTO, 2)
MARGEN_BRUTO = round(UTILIDAD_BRUTA / TOTAL_VENTAS, 6)

NOMINA            = 520_000.00
GASTOS_COMERCIALES   = 95_000.00
GASTOS_OPERATIVOS    = 145_000.00
GASTOS_ADMIN         = 88_000.00
VIATICOS             = 22_000.00
TOTAL_GASTOS_OP = round(NOMINA + GASTOS_COMERCIALES + GASTOS_OPERATIVOS + GASTOS_ADMIN + VIATICOS, 2)

MARGEN_COSTO = round(TOTAL_COSTO / TOTAL_VENTAS, 4)
MARGEN_OPERACION = round(TOTAL_GASTOS_OP / TOTAL_VENTAS, 4)

EBITDA = round(UTILIDAD_BRUTA - TOTAL_GASTOS_OP, 2)
MARGEN_EBITDA = round(EBITDA / TOTAL_VENTAS, 4)

GASTOS_FINANCIEROS = 35_000.00
COSTO_INTEGRAL_FINANCIAMIENTO = 0.0
IMPUESTOS = round((EBITDA - GASTOS_FINANCIEROS) * 0.30, 2)
UTILIDAD_NETA = round(EBITDA - GASTOS_FINANCIEROS - IMPUESTOS, 2)
MARGEN_NETO = round(UTILIDAD_NETA / TOTAL_VENTAS, 4)


def build_normalized_month() -> dict:
    return {
        "ventas": {grp: dict(VENTAS[grp]) for grp in "ABCDE"},
        "egresos": {grp: dict(EGRESOS[grp]) for grp in "ABCDE"},
        "kpis": {
            "total_ventas": TOTAL_VENTAS,
            "total_costo": TOTAL_COSTO,
            "margen_costo": MARGEN_COSTO,
            "utilidad_bruta": UTILIDAD_BRUTA,
            "margen_bruto": MARGEN_BRUTO,
            "nomina": NOMINA,
            "gastos_comerciales": GASTOS_COMERCIALES,
            "gastos_operativos": GASTOS_OPERATIVOS,
            "gastos_administrativos": GASTOS_ADMIN,
            "viaticos": VIATICOS,
            "total_gastos_operacion": TOTAL_GASTOS_OP,
            "margen_operacion": MARGEN_OPERACION,
            "ebitda": EBITDA,
            "margen_ebitda": MARGEN_EBITDA,
            "gastos_financieros": GASTOS_FINANCIEROS,
            "costo_integral_financiamiento": COSTO_INTEGRAL_FINANCIAMIENTO,
            "impuestos": IMPUESTOS,
            "utilidad_neta": UTILIDAD_NETA,
            "margen_neto": MARGEN_NETO,
        },
    }


def build_normalized_doc() -> dict:
    return {
        "periodo": "2026",
        "fuente": "excel",
        "cliente_id": "test_client",
        "meses": {"ENERO 2026": build_normalized_month()},
    }


# --- Prose text that mimics an unstructured PDF ---
PROSE_PDF_TEXT = f"""
ESTADO DE RESULTADOS - ENERO 2026

VENTAS
Grupo A - ENERO 2026
  Alimentos: $2,318,182.87
  Bebidas: $416,592.10
  Cafe_Inf: $27,135.50
  Destilados: $312,036.99
  Vinos: $90,831.26
  Total Grupo A: ${VENTAS["A"]["total"]:,.2f}

Grupo B - ENERO 2026
  Alimentos: $1,850,000.00
  Bebidas: $320,000.00
  Cafe_Inf: $18,500.00
  Destilados: $210,000.00
  Vinos: $65,000.00
  Total Grupo B: ${VENTAS["B"]["total"]:,.2f}

Total Ventas: ${TOTAL_VENTAS:,.2f}

EGRESOS / COSTO DE VENTAS
Total Costo: ${TOTAL_COSTO:,.2f}

UTILIDAD BRUTA: ${UTILIDAD_BRUTA:,.2f}
Margen Bruto: {MARGEN_BRUTO:.4f}

GASTOS DE OPERACIÓN
Nómina: ${NOMINA:,.2f}
Gastos Comerciales: ${GASTOS_COMERCIALES:,.2f}
Gastos Operativos: ${GASTOS_OPERATIVOS:,.2f}
Gastos Administrativos: ${GASTOS_ADMIN:,.2f}
Viáticos: ${VIATICOS:,.2f}
Total Gastos de Operación: ${TOTAL_GASTOS_OP:,.2f}

EBITDA: ${EBITDA:,.2f}
Margen EBITDA: {MARGEN_EBITDA:.4f}

Gastos Financieros: ${GASTOS_FINANCIEROS:,.2f}
Impuestos: ${IMPUESTOS:,.2f}
Utilidad Neta: ${UTILIDAD_NETA:,.2f}
Margen Neto: {MARGEN_NETO:.4f}
"""
