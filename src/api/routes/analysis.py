import dataclasses
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from ...pipeline.engine import CopilotEngine
from ...pipeline.forecast import forecast_revenue
from ...pipeline.health_score import calcular_health_score
from ...pipeline.integrator import integrate
from ...pipeline.kpis import calcular_kpis
from ...pipeline.macro import MacroFetcher
from ...pipeline.parsers import ParseError
from ...pipeline.parsers.parser_bd import parse_bd
from ...pipeline.parsers.parser_er import parse_er
from ...pipeline.scenario import ScenarioConfig, simular_escenario
from ...ml.trainer import train

router = APIRouter(tags=["analysis"])

# ── background task workers ───────────────────────────────────────────────────

def _bg_analyze(task_id, bd_tmp, er_tmp, qual_tmps, cliente_id, config, train_model):
    from ..tasks import update_task
    update_task(task_id, "running")
    try:
        engine = CopilotEngine()
        result = engine.run_full_pipeline(
            bd_filepath=bd_tmp,
            er_filepath=er_tmp,
            qualitative_filepaths=qual_tmps,
            cliente_id=cliente_id,
            config=config,
            train_model=train_model,
        )
        update_task(task_id, "completed", result=dataclasses.asdict(result))
    except Exception as exc:
        update_task(task_id, "failed", error=str(exc))
    finally:
        _cleanup(bd_tmp, er_tmp, *qual_tmps)


def _bg_pdf(task_id, bd_tmp, er_tmp, qual_tmps, cliente_id, config, train_model,
            include_macro, include_recommendations):
    import tempfile
    from ..tasks import update_task
    update_task(task_id, "running")
    pdf_tmp = None
    try:
        from ...pipeline.report_generator import generar_reporte

        bd_data = parse_bd(bd_tmp)
        er_data = parse_er(er_tmp)
        fin_data = integrate(bd_data, er_data)
        kpi_report = calcular_kpis(fin_data, config)

        shap_narrative = None
        if train_model:
            try:
                from ...ml.predictor import predict_and_explain
                from ...ml.trainer import train as train_ml
                from ...pipeline.shap_translator import translate_shap
                trained = train_ml(bd_data)
                pred_report = predict_and_explain(trained, bd_data)
                shap_narrative = translate_shap(pred_report, config)
            except Exception:
                pass

        forecast_result = forecast_revenue(kpi_report)

        macro_indices = None
        if include_macro:
            try:
                fetcher = MacroFetcher()
                macro_data = fetcher.fetch_all()
                macro_indices = fetcher.calcular_indices(macro_data, config)
            except Exception:
                pass

        health_score_report = calcular_health_score(kpi_report, macro_indices, config)

        all_chunks: List[Any] = []
        for fp in qual_tmps:
            try:
                from ...ingestion.document_loader import load_document
                from ...ingestion.chunker import chunk_document
                doc = load_document(fp, cliente_id)
                all_chunks.extend(chunk_document(doc))
            except Exception:
                pass

        copilot_report = None
        if include_recommendations:
            try:
                engine = CopilotEngine()
                copilot_report = engine.generate(
                    kpi_report=kpi_report,
                    health_score_report=health_score_report,
                    macro_indices=macro_indices,
                    shap_narrative=shap_narrative,
                    forecast_result=forecast_result,
                    chunks=all_chunks,
                    cliente_id=cliente_id,
                )
            except Exception:
                pass

        pdf_bytes = generar_reporte(
            kpi_report=kpi_report,
            health_report=health_score_report,
            macro_indices=macro_indices,
            shap_narrative=shap_narrative,
            forecast_result=forecast_result,
            copilot_report=copilot_report,
            cliente_id=cliente_id,
        )

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf_bytes)
            pdf_tmp = f.name

        update_task(task_id, "completed", pdf_path=pdf_tmp)
    except Exception as exc:
        update_task(task_id, "failed", error=str(exc))
    finally:
        _cleanup(bd_tmp, er_tmp, *qual_tmps)


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


def _build_config(
    cliente_id: str,
    config_path: Optional[str],
    benchmarks: Optional[str],
) -> Dict[str, Any]:
    """Load config from file, then override benchmarks if provided."""
    config = _load_config(cliente_id, config_path)
    if benchmarks:
        try:
            bench_dict = json.loads(benchmarks)
            config["benchmarks"] = bench_dict
        except json.JSONDecodeError:
            raise HTTPException(status_code=422, detail="benchmarks debe ser un JSON válido")
    return config


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

@router.post("/analyze", status_code=202)
async def analyze(
    background_tasks: BackgroundTasks,
    bd_file: UploadFile = File(...),
    er_file: UploadFile = File(...),
    qualitative_files: Optional[List[UploadFile]] = File(default=None),
    cliente_id: str = Form(default="default"),
    include_macro: bool = Form(default=True),
    train_model: bool = Form(default=True),
    benchmarks: Optional[str] = Form(default=None, description="JSON con benchmarks personalizados, ej: {\"margen_bruto\": 0.65}"),
    config_path: Optional[str] = Form(default=None),
):
    from ..tasks import create_task

    bd_tmp = er_tmp = None
    qual_tmps: List[str] = []
    try:
        bd_tmp = await _save_upload(bd_file)
        er_tmp = await _save_upload(er_file)
        if qualitative_files:
            for qf in qualitative_files:
                suffix = Path(qf.filename or "doc.txt").suffix or ".txt"
                qual_tmps.append(await _save_upload(qf, suffix=suffix))

        config = _build_config(cliente_id, config_path, benchmarks)
        task_id = create_task("analyze")
        background_tasks.add_task(
            _bg_analyze, task_id, bd_tmp, er_tmp, qual_tmps, cliente_id, config, train_model
        )
        return {"task_id": task_id, "status": "pending", "poll_url": f"/api/v1/tasks/{task_id}"}

    except ParseError as exc:
        _cleanup(bd_tmp, er_tmp, *qual_tmps)
        raise HTTPException(status_code=422, detail=f"Error al procesar los archivos: {exc}")
    except Exception:
        _cleanup(bd_tmp, er_tmp, *qual_tmps)
        raise


# ── POST /kpis ────────────────────────────────────────────────────────────────

@router.post("/kpis")
async def get_kpis(
    bd_file: UploadFile = File(...),
    er_file: UploadFile = File(...),
    cliente_id: str = Form(default="default"),
    benchmarks: Optional[str] = Form(default=None, description="JSON con benchmarks personalizados"),
    config_path: Optional[str] = Form(default=None),
):
    bd_tmp = er_tmp = None
    try:
        bd_tmp = await _save_upload(bd_file)
        er_tmp = await _save_upload(er_file)

        config = _build_config(cliente_id, config_path, benchmarks)
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
    benchmarks: Optional[str] = Form(default=None, description="JSON con benchmarks personalizados"),
    config_path: Optional[str] = Form(default=None),
):
    bd_tmp = er_tmp = None
    try:
        bd_tmp = await _save_upload(bd_file)
        er_tmp = await _save_upload(er_file)

        config = _build_config(cliente_id, config_path, benchmarks)
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


# ── POST /pdf ─────────────────────────────────────────────────────────────────

@router.post("/pdf", status_code=202)
async def generate_pdf(
    background_tasks: BackgroundTasks,
    bd_file: UploadFile = File(...),
    er_file: UploadFile = File(...),
    qualitative_files: Optional[List[UploadFile]] = File(default=None),
    cliente_id: str = Form(default="default"),
    include_macro: bool = Form(default=True),
    train_model: bool = Form(default=True),
    include_recommendations: bool = Form(default=True, description="Llama al LLM para generar recomendaciones"),
    benchmarks: Optional[str] = Form(default=None, description="JSON con benchmarks personalizados"),
    config_path: Optional[str] = Form(default=None),
):
    from ..tasks import create_task

    bd_tmp = er_tmp = None
    qual_tmps: List[str] = []
    try:
        bd_tmp = await _save_upload(bd_file)
        er_tmp = await _save_upload(er_file)
        if qualitative_files:
            for qf in qualitative_files:
                suffix = Path(qf.filename or "doc.txt").suffix or ".txt"
                qual_tmps.append(await _save_upload(qf, suffix=suffix))

        config = _build_config(cliente_id, config_path, benchmarks)
        task_id = create_task("pdf")
        background_tasks.add_task(
            _bg_pdf, task_id, bd_tmp, er_tmp, qual_tmps,
            cliente_id, config, train_model, include_macro, include_recommendations
        )
        return {"task_id": task_id, "status": "pending", "poll_url": f"/api/v1/tasks/{task_id}"}

    except ParseError as exc:
        _cleanup(bd_tmp, er_tmp, *qual_tmps)
        raise HTTPException(status_code=422, detail=f"Error al procesar los archivos: {exc}")
    except Exception:
        _cleanup(bd_tmp, er_tmp, *qual_tmps)
        raise


# ── POST /scenario ────────────────────────────────────────────────────────────

@router.post("/scenario")
async def run_scenario(
    bd_file: UploadFile = File(...),
    er_file: UploadFile = File(...),
    cliente_id: str = Form(default="default"),
    variaciones: str = Form(
        ...,
        description=(
            "JSON con la variación esperada (%) por variable. "
            "Variables: revenue, costo_directo, nomina, gastos_financieros. "
            'Ejemplo: {"revenue": 0.05, "nomina": -0.03}'
        ),
    ),
    sigmas: Optional[str] = Form(
        default=None,
        description=(
            "JSON con la incertidumbre (desviación estándar) por variable. "
            "Defaults: revenue=0.05, costo_directo=0.04, nomina=0.03, gastos_financieros=0.02."
        ),
    ),
    n_simulaciones: int = Form(default=10_000, description="Iteraciones Monte Carlo (1 000 – 100 000)"),
    semilla: Optional[int] = Form(default=None, description="Semilla aleatoria para reproducibilidad"),
    benchmarks: Optional[str] = Form(default=None, description="JSON con benchmarks personalizados"),
    config_path: Optional[str] = Form(default=None),
):
    bd_tmp = er_tmp = None
    try:
        try:
            variaciones_dict: Dict[str, float] = json.loads(variaciones)
        except json.JSONDecodeError:
            raise HTTPException(status_code=422, detail="'variaciones' debe ser un JSON valido")

        sigmas_dict: Dict[str, float] = {}
        if sigmas:
            try:
                sigmas_dict = json.loads(sigmas)
            except json.JSONDecodeError:
                raise HTTPException(status_code=422, detail="'sigmas' debe ser un JSON valido")

        allowed = {"revenue", "costo_directo", "nomina", "gastos_financieros"}
        invalid_keys = set(variaciones_dict) - allowed
        if invalid_keys:
            raise HTTPException(
                status_code=422,
                detail=f"Variables no reconocidas: {invalid_keys}. Permitidas: {allowed}",
            )

        if not (1_000 <= n_simulaciones <= 100_000):
            raise HTTPException(status_code=422, detail="n_simulaciones debe estar entre 1 000 y 100 000")

        bd_tmp = await _save_upload(bd_file)
        er_tmp = await _save_upload(er_file)

        config = _build_config(cliente_id, config_path, benchmarks)
        bd_data = parse_bd(bd_tmp)
        er_data = parse_er(er_tmp)
        fin_data = integrate(bd_data, er_data)
        kpi_report = calcular_kpis(fin_data, config)

        scenario_config = ScenarioConfig(
            variaciones=variaciones_dict,
            sigmas=sigmas_dict,
            n_simulaciones=n_simulaciones,
            semilla=semilla,
        )
        result = simular_escenario(
            kpi_report=kpi_report,
            config=scenario_config,
            benchmarks=config.get("benchmarks"),
        )
        return dataclasses.asdict(result)

    except ParseError as exc:
        raise HTTPException(status_code=422, detail=f"Error al procesar los archivos: {exc}")
    finally:
        _cleanup(bd_tmp, er_tmp)
