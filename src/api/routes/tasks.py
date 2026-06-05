import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from ..tasks import get_task

router = APIRouter(tags=["tasks"])


@router.get("/tasks/{task_id}")
def get_task_status(task_id: str):
    """
    Consulta el estado de una tarea asíncrona.

    - **pending**: en cola, aún no inicia
    - **running**: ejecutándose
    - **completed**: terminada — el campo `result` contiene el análisis JSON,
      o `download_url` apunta al PDF si la tarea es de tipo `pdf`
    - **failed**: falló — el campo `error` describe la causa
    """
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada o expirada (TTL: 1 hora)")

    response: dict = {
        "task_id": task["task_id"],
        "type": task["type"],
        "status": task["status"],
        "created_at": task["created_at"],
        "completed_at": task["completed_at"],
        "error": task["error"],
    }

    if task["status"] == "completed":
        if task["type"] == "pdf":
            response["download_url"] = f"/api/v1/tasks/{task_id}/download"
        else:
            response["result"] = task["result"]

    return response


@router.get("/tasks/{task_id}/download", response_class=Response)
def download_task_pdf(task_id: str):
    """Descarga el PDF generado por una tarea de tipo `pdf` una vez completada."""
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada o expirada")
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"Tarea no completada (status: {task['status']})")
    if task["type"] != "pdf":
        raise HTTPException(status_code=400, detail="Esta tarea no genera un archivo descargable")

    pdf_path = task.get("pdf_path")
    if not pdf_path or not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="Archivo PDF no disponible")

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    filename = f"reporte_{task_id[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
