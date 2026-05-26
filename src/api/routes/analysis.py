import dataclasses
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ...pipeline.engine import CopilotEngine
from ...pipeline.forecast import forecast_revenue
from ...pipeline.health_score import calcular_health_score
from ...pipeline.integrator import integrate
from ...pipeline.kpis import calcular_kpis
from ...pipeline.macro import MacroFetcher
from ...pipeline.parsers import ParseError
from ...pipeline.parsers.parser_bd import parse_bd
from ...pipeline.parsers.parser_er import parse_er
from ...ml.trainer import train

router = APIRouter(tags=["analysis"])

# ── simple in-memory cache for /macro (1-hour TTL) ────────────────────────────
_macro_cache: Optional[Dict[str, Any]] = None
_macro_cache_ts: float = 0.0
_MACRO_TTL = 3600.0


def _load_config(cliente_id: str, config_path: Optional[str] = None) -> Dict[str, Any]:
    path = config_path or f"configs/{cliente_id}.json"
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


async def _save_upload(upload: UploadFile, suffix: str = ".csv") -> str:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
        fh.write(await upload.read())
        return fh.name


def _cleanup(*paths: Optional[str]) -> None:
    for path in paths:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


# ── POST /analyze ─────────────────────────────────────────────────────────────

@router.post("/analyze")
async def analyze(
    bd_file: UploadFile = File(...),
    er_file: UploadFile = File(...),
    qualitative_files: Optional[List[UploadFile]] = File(default=None),
    cliente_id: str = Form(default="default"),
    include_macro: bool = Form(default=True),
    train_model: bool = Form(default=True),
):
    bd_tmp = er_tmp = None
    qual_tmps: List[str] = []
    try:
        bd_tmp = await _save_upload(bd_file)
        er_tmp = await _save_upload(er_file)

        qual_paths: List[str] = []
        if qualitative_files:
            for qf in qualitative_files:
                suffix = Path(qf.filename or "doc.txt").suffix or ".txt"
                p = await _save_upload(qf, suffix=suffix)
                qual_tmps.append(p)
                qual_paths.append(p)

        engine = CopilotEngine()
        result = engine.run_full_pipeline(
            bd_filepath=bd_tmp,
            er_filepath=er_tmp,
            qualitative_filepaths=qual_paths,
            cliente_id=cliente_id,
            train_model=train_model,
        )
        return dataclasses.asdict(result)

    except ParseError as exc:
        raise HTTPException(status_code=422, detail=f"Error al procesar los archivos: {exc}")
    finally:
        _cleanup(bd_tmp, er_tmp, *qual_tmps)


# ── POST /kpis ────────────────────────────────────────────────────────────────

@router.post("/kpis")
async def get_kpis(
    bd_file: UploadFile = File(...),
    er_file: UploadFile = File(...),
    cliente_id: str = Form(default="default"),
    config_path: Optional[str] = Form(default=None),
):
    bd_tmp = er_tmp = None
    try:
        bd_tmp = await _save_upload(bd_file)
        er_tmp = await _save_upload(er_file)

        config = _load_config(cliente_id, config_path)
        bd_data = parse_bd(bd_tmp)
        er_data = parse_er(er_tmp)
        fin_data = integrate(bd_data, er_data)
        kpi_report = calcular_kpis(fin_data, config)
        return dataclasses.asdict(kpi_report)

    except ParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    finally:
        _cleanup(bd_tmp, er_tmp)


# ── POST /health-score ────────────────────────────────────────────────────────

@router.post("/health-score")
async def get_health_score(
    bd_file: UploadFile = File(...),
    er_file: UploadFile = File(...),
    cliente_id: str = Form(default="default"),
    include_macro: bool = Form(default=True),
    config_path: Optional[str] = Form(default=None),
):
    bd_tmp = er_tmp = None
    try:
        bd_tmp = await _save_upload(bd_file)
        er_tmp = await _save_upload(er_file)

        config = _load_config(cliente_id, config_path)
        bd_data = parse_bd(bd_tmp)
        er_data = parse_er(er_tmp)
        fin_data = integrate(bd_data, er_data)
        kpi_report = calcular_kpis(fin_data, config)

        macro_indices = None
        if include_macro:
            try:
                fetcher = MacroFetcher()
                macro_data = fetcher.fetch_all()
                macro_indices = fetcher.calcular_indices(macro_data, config)
            except Exception:
                pass

        hs_report = calcular_health_score(kpi_report, macro_indices, config)
        result: Dict[str, Any] = {"health_score": dataclasses.asdict(hs_report)}
        if macro_indices is not None:
            result["macro_indices"] = dataclasses.asdict(macro_indices)
        return result

    except ParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    finally:
        _cleanup(bd_tmp, er_tmp)


# ── POST /forecast ────────────────────────────────────────────────────────────

@router.post("/forecast")
async def get_forecast(
    bd_file: UploadFile = File(...),
    er_file: UploadFile = File(...),
    cliente_id: str = Form(default="default"),
    config_path: Optional[str] = Form(default=None),
):
    bd_tmp = er_tmp = None
    try:
        bd_tmp = await _save_upload(bd_file)
        er_tmp = await _save_upload(er_file)

        config = _load_config(cliente_id, config_path)
        bd_data = parse_bd(bd_tmp)
        er_data = parse_er(er_tmp)
        fin_data = integrate(bd_data, er_data)
        kpi_report = calcular_kpis(fin_data, config)
        result = forecast_revenue(kpi_report)
        return dataclasses.asdict(result)

    except ParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    finally:
        _cleanup(bd_tmp, er_tmp)


# ── GET /macro ────────────────────────────────────────────────────────────────

@router.get("/macro")
def get_macro(cliente_id: str = "default", config_path: Optional[str] = None):
    global _macro_cache, _macro_cache_ts

    now = time.time()
    if _macro_cache is not None and (now - _macro_cache_ts) < _MACRO_TTL:
        return _macro_cache

    config = _load_config(cliente_id, config_path)
    fetcher = MacroFetcher()
    macro_data = fetcher.fetch_all()
    macro_indices = fetcher.calcular_indices(macro_data, config)

    _macro_cache = {
        "macro_data": dataclasses.asdict(macro_data),
        "macro_indices": dataclasses.asdict(macro_indices),
    }
    _macro_cache_ts = now
    return _macro_cache


# ── POST /train ───────────────────────────────────────────────────────────────

@router.post("/train")
async def train_model(
    bd_file: UploadFile = File(...),
    cliente_id: str = Form(default="default"),
):
    bd_tmp = None
    try:
        bd_tmp = await _save_upload(bd_file)
        bd_data = parse_bd(bd_tmp)
        save_path = f"models/{cliente_id}/xgboost_efficiency.pkl"
        trained = train(bd_data, save_path=save_path)
        return {"train_metrics": trained.train_metrics, "trained_at": trained.trained_at}

    except ParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    finally:
        _cleanup(bd_tmp)
