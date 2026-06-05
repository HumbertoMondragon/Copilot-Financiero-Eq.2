import logging
import os

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _valid_keys() -> set:
    raw = os.getenv("API_KEYS", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


async def verify_api_key(api_key: str = Security(_API_KEY_HEADER)) -> str:
    keys = _valid_keys()
    if not keys:
        logger.warning("API_KEYS no configurado — autenticación deshabilitada (modo desarrollo)")
        return "dev"
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Se requiere el header X-API-Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    if api_key not in keys:
        raise HTTPException(status_code=403, detail="API Key inválida o revocada")
    return api_key
