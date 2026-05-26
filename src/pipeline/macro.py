import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_BANXICO_BASE = "https://www.banxico.org.mx/SieAPIRest/service/v1/series/{}/datos/oportuno"
_INEGI_BASE = (
    "https://www.inegi.org.mx/app/api/indicadores/desarrolladores/jsonxml"
    "/INDICATOR/{indicator}/es/0700/{token}/BIE/2.0/"
)

# Multipliers relative to general INPC used to estimate component variations
_COMPONENT_MULTIPLIERS = {
    "energia": 0.55,
    "servicios": 1.10,
    "mercancias": 0.82,
    "alimentos": 1.40,
}


@dataclass
class MacroData:
    fetched_at: str
    raw: Dict[str, Any]
    errores: List[str] = field(default_factory=list)


@dataclass
class MacroIndices:
    indice_presion_inflacionaria: Dict[str, Any]
    indice_entorno_economico: Dict[str, Any]
    indice_presion_financiera: Dict[str, Any]
    narrativa_consolidada: str


class MacroFetcher:
    def __init__(self) -> None:
        self.banxico_token = os.getenv("BANXICO_TOKEN", "")
        self.inegi_token = os.getenv("INEGI_TOKEN", "false")  # "false" = anonymous access
        if not self.banxico_token:
            logger.warning("BANXICO_TOKEN not set — Banxico requests will fail (free token at banxico.org.mx)")

    def _get_banxico(self, series: str) -> Dict[str, Any]:
        url = _BANXICO_BASE.format(series)
        headers = {"Bmx-Token": self.banxico_token} if self.banxico_token else {}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        dato = resp.json()["bmx"]["series"][0]["datos"][0]
        return {"valor": float(dato["dato"].replace(",", "")), "fecha": dato["fecha"]}

    def _get_banxico_inpc(self) -> Dict[str, Any]:
        from datetime import date, timedelta
        start = (date.today().replace(day=1) - timedelta(days=400)).strftime("%Y-%m-%d")
        end = date.today().strftime("%Y-%m-%d")
        url = f"https://www.banxico.org.mx/SieAPIRest/service/v1/series/SP1/datos/{start}/{end}"
        headers = {"Bmx-Token": self.banxico_token} if self.banxico_token else {}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        datos = resp.json()["bmx"]["series"][0]["datos"]
        if len(datos) < 2:
            raise ValueError("Datos insuficientes para calcular variación anual INPC")
        last = datos[-1]
        prev = datos[-13] if len(datos) >= 13 else datos[0]
        v_last = float(last["dato"].replace(",", ""))
        v_prev = float(prev["dato"].replace(",", ""))
        var_anual = round((v_last / v_prev - 1) * 100, 2)
        return {"valor": var_anual, "fecha": last["fecha"]}

    def _get_inegi(self, indicator: str) -> Dict[str, Any]:
        url = _INEGI_BASE.format(indicator=indicator, token=self.inegi_token)
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        obs = resp.json()["Series"][0]["OBSERVATIONS"]
        latest = next(
            o for o in reversed(obs) if o.get("OBS_VALUE") not in (None, "")
        )
        return {"valor": float(latest["OBS_VALUE"]), "fecha": latest["TIME_PERIOD"]}

    def fetch_all(self) -> MacroData:
        raw: Dict[str, Any] = {}
        errores: List[str] = []

        for key, series in [("tipo_cambio_usd", "SF43718"), ("tasa_interes", "SF61745")]:
            try:
                d = self._get_banxico(series)
                raw[key] = {**d, "fuente": f"Banxico {series}"}
            except Exception as exc:
                msg = "BANXICO_TOKEN requerido (registro gratuito en banxico.org.mx)" if not self.banxico_token else str(exc)
                errores.append(f"Banxico {series}: {msg}")
                raw[key] = None

        try:
            d = self._get_banxico_inpc()
            raw["inpc_variacion_anual"] = {**d, "fuente": "Banxico SP1"}
        except Exception as exc:
            errores.append(f"Banxico SP1: {exc}")
            raw["inpc_variacion_anual"] = None

        try:
            d = self._get_inegi("383162")
            raw["igae_variacion_anual"] = {**d, "fuente": "INEGI 383162"}
        except Exception as exc:
            msg = "INEGI_TOKEN requerido (registro en inegi.org.mx)" if self.inegi_token == "false" else str(exc)
            errores.append(f"INEGI IGAE: {msg}")
            raw["igae_variacion_anual"] = None

        inpc_val = (raw.get("inpc_variacion_anual") or {}).get("valor", 3.8)
        raw["inpc_por_componente"] = {
            comp: round(inpc_val * mult, 2)
            for comp, mult in _COMPONENT_MULTIPLIERS.items()
        }
        raw["expectativa_inflacion_12m"] = {
            "valor": round(inpc_val * 0.92, 2),
            "fuente": "Banxico encuesta (estimado desde INPC)",
        }

        return MacroData(
            fetched_at=datetime.now(timezone.utc).isoformat(),
            raw=raw,
            errores=errores,
        )

    def calcular_indices(self, macro_data: MacroData, config: Dict) -> MacroIndices:
        raw = macro_data.raw
        sensibilidad: Dict[str, float] = config.get(
            "macro_sensibilidad",
            {"energia": 0.15, "servicios": 0.40, "mercancias": 0.30, "alimentos": 0.15},
        )

        # 1. Presión inflacionaria: sum(variacion * peso) / 3.0
        componentes_raw = raw.get("inpc_por_componente") or {}
        componentes: Dict[str, Any] = {}
        presion_sum = 0.0
        for comp, peso in sensibilidad.items():
            variacion = componentes_raw.get(comp, 0.0)
            contribucion = variacion * peso
            presion_sum += contribucion
            componentes[comp] = {
                "variacion": variacion,
                "peso_cliente": peso,
                "contribucion": round(contribucion, 4),
            }
        valor_presion = round(presion_sum / 3.0, 4)
        if valor_presion > 1.0:
            interp_presion = "alta"
        elif valor_presion >= 0.3:
            interp_presion = "moderada"
        else:
            interp_presion = "baja"

        # 2. Entorno económico: weighted(IGAE=0.6, expectativa_norm=0.4)
        igae_raw = raw.get("igae_variacion_anual") or {}
        igae_val: float = igae_raw.get("valor", 0.0)
        expectativa_raw = raw.get("expectativa_inflacion_12m") or {}
        expectativa_val: float = expectativa_raw.get("valor", 3.5)

        igae_norm = max(0.0, min(1.0, (igae_val + 5.0) / 10.0))
        expect_norm = max(0.0, min(1.0, 1.0 - expectativa_val / 8.0))
        valor_entorno = round(igae_norm * 0.6 + expect_norm * 0.4, 4)

        if igae_val > 2.0:
            interp_entorno = "favorable"
        elif igae_val < -1.0:
            interp_entorno = "adverso"
        else:
            interp_entorno = "neutral"

        # 3. Presión financiera: based on tasa_interes (0–1 scale, normalized /15)
        tasa_raw = raw.get("tasa_interes") or {}
        tasa_val: float = tasa_raw.get("valor", 9.0)

        valor_presion_fin = round(max(0.0, min(1.0, tasa_val / 15.0)), 4)
        if tasa_val > 10.0:
            interp_fin = "alta"
        elif tasa_val >= 7.0:
            interp_fin = "moderada"
        else:
            interp_fin = "baja"

        narrativa = (
            f"El entorno macroeconómico muestra una presión inflacionaria {interp_presion} "
            f"con un índice de {valor_presion:.2f}. "
            f"El entorno económico general es {interp_entorno} "
            f"con una variación del IGAE de {igae_val:.1f}%. "
            f"La tasa de interés de referencia en {tasa_val:.1f}% representa "
            f"una presión financiera {interp_fin} para el servicio de deuda."
        )

        return MacroIndices(
            indice_presion_inflacionaria={
                "valor": valor_presion,
                "interpretacion": interp_presion,
                "componentes": componentes,
                "descripcion": (
                    f"Presión inflacionaria {interp_presion} sobre la estructura de costos "
                    f"con índice de {valor_presion:.2f}."
                ),
            },
            indice_entorno_economico={
                "valor": valor_entorno,
                "interpretacion": interp_entorno,
                "descripcion": (
                    f"El entorno económico general es {interp_entorno} para el crecimiento."
                ),
            },
            indice_presion_financiera={
                "valor": valor_presion_fin,
                "interpretacion": interp_fin,
                "descripcion": (
                    f"La tasa de referencia en {tasa_val:.1f}% representa "
                    f"presión financiera {interp_fin}."
                ),
            },
            narrativa_consolidada=narrativa,
        )
