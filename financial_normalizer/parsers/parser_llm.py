"""
LLM parser: sends raw text to claude-sonnet-4-20250514 and asks for normalized JSON.
Used as primary parser for unstructured prose PDFs and as fallback when other parsers fail validation.
"""
from __future__ import annotations

import json
import os
import re

import anthropic

from . import ParseError
from ..profiles import get_profile, empty_month, GROUPS

_SYSTEM_PROMPT = """\
You are a financial data extraction assistant specializing in Mexican P&L statements (Estado de Resultados).
Extract the data and return ONLY a valid JSON object. No markdown fences, no explanation.

The JSON must follow this exact schema:
{
  "periodo": "<4-digit year>",
  "fuente": "pdf_texto",
  "cliente_id": "<cliente_id>",
  "meses": {
    "<MES YYYY>": {
      "ventas": {
        "A": {"total": 0.0, "Alimentos": 0.0, "Bebidas": 0.0, "Cafe_Inf": 0.0, "Destilados": 0.0, "Vinos": 0.0},
        "B": {"total": 0.0, "Alimentos": 0.0, "Bebidas": 0.0, "Cafe_Inf": 0.0, "Destilados": 0.0, "Vinos": 0.0},
        "C": {"total": 0.0, "Alimentos": 0.0, "Bebidas": 0.0, "Cafe_Inf": 0.0, "Destilados": 0.0, "Vinos": 0.0},
        "D": {"total": 0.0, "Alimentos": 0.0, "Bebidas": 0.0, "Cafe_Inf": 0.0, "Destilados": 0.0, "Vinos": 0.0},
        "E": {"total": 0.0, "Alimentos": 0.0, "Bebidas": 0.0, "Cafe_Inf": 0.0, "Destilados": 0.0, "Vinos": 0.0}
      },
      "egresos": {
        "A": {"total": 0.0}, "B": {"total": 0.0}, "C": {"total": 0.0},
        "D": {"total": 0.0}, "E": {"total": 0.0}
      },
      "kpis": {
        "total_ventas": 0.0, "total_costo": 0.0, "utilidad_bruta": 0.0,
        "margen_bruto": 0.0, "nomina": 0.0, "gastos_comerciales": 0.0,
        "gastos_operativos": 0.0, "gastos_administrativos": 0.0, "viaticos": 0.0,
        "total_gastos_operacion": 0.0, "ebitda": 0.0, "margen_ebitda": 0.0,
        "gastos_financieros": 0.0, "impuestos": 0.0, "utilidad_neta": 0.0,
        "margen_neto": 0.0
      }
    }
  }
}

Rules:
- All monetary values must be floats, never strings.
- Month keys must be uppercase Spanish: "ENERO 2026", "FEBRERO 2026", etc.
- If a value is not present in the source, use 0.0.
- Return ONLY the JSON object, nothing else.
"""


def parse(raw_text: str, cliente_id: str = "default") -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ParseError("ANTHROPIC_API_KEY not set in environment.")

    profile = get_profile(cliente_id)
    hint = profile.get("hint", "")
    scale = profile.get("scale", 1.0)

    user_content = raw_text
    if hint:
        user_content = f"[Client hint: {hint}]\n\n{raw_text}"

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
    except anthropic.APIError as exc:
        raise ParseError(f"Anthropic API error: {exc}") from exc

    raw_response = response.content[0].text if response.content else ""
    json_str = _strip_fences(raw_response)

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise ParseError(f"LLM returned invalid JSON: {exc}\nRaw: {raw_response[:500]}") from exc

    data["fuente"] = "pdf_texto"
    data.setdefault("cliente_id", cliente_id)

    if scale != 1.0:
        _apply_scale(data, scale)

    return data


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _apply_scale(data: dict, scale: float) -> None:
    for mes_data in data.get("meses", {}).values():
        for section in ("ventas", "egresos"):
            for grp in mes_data.get(section, {}).values():
                for k in grp:
                    if isinstance(grp[k], (int, float)):
                        grp[k] = grp[k] * scale
        kpis = mes_data.get("kpis", {})
        # Don't scale margin ratios
        ratio_keys = {"margen_bruto", "margen_ebitda", "margen_neto"}
        for k in kpis:
            if k not in ratio_keys and isinstance(kpis[k], (int, float)):
                kpis[k] = kpis[k] * scale
