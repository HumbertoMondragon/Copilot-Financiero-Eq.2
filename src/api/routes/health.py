import os
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    return {"status": "ok", "version": "2.0.0"}


@router.get("/health/detailed")
def health_detailed():
    api_key_ok = bool(os.getenv("ANTHROPIC_API_KEY"))
    return {
        "status": "ok" if api_key_ok else "degraded",
        "api_key_configured": api_key_ok,
        "chroma_db_present": Path("./chroma_db").exists(),
        "models_dir_present": Path("./models").exists(),
    }
