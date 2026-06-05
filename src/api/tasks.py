import os
import time
import uuid
from typing import Any, Dict, Optional

_store: Dict[str, Dict[str, Any]] = {}
_TTL = 3600.0  # tasks expire after 1 hour


def create_task(task_type: str) -> str:
    task_id = str(uuid.uuid4())
    _store[task_id] = {
        "task_id": task_id,
        "type": task_type,
        "status": "pending",
        "created_at": time.time(),
        "completed_at": None,
        "result": None,
        "pdf_path": None,
        "error": None,
    }
    return task_id


def update_task(
    task_id: str,
    status: str,
    result: Optional[Any] = None,
    pdf_path: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    if task_id not in _store:
        return
    _store[task_id]["status"] = status
    _store[task_id]["completed_at"] = time.time()
    if result is not None:
        _store[task_id]["result"] = result
    if pdf_path is not None:
        _store[task_id]["pdf_path"] = pdf_path
    if error is not None:
        _store[task_id]["error"] = error


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    _purge_expired()
    return _store.get(task_id)


def _purge_expired() -> None:
    now = time.time()
    expired = [tid for tid, t in _store.items() if now - t["created_at"] > _TTL]
    for tid in expired:
        # delete any associated PDF temp file
        pdf_path = _store[tid].get("pdf_path")
        if pdf_path:
            try:
                os.unlink(pdf_path)
            except OSError:
                pass
        del _store[tid]
