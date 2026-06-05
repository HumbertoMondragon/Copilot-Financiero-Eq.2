from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    from dotenv import load_dotenv
    load_dotenv()
    yield


app = FastAPI(
    title="Copilot Financiero API",
    version="2.0.0",
    description="API de análisis financiero con IA para PyMEs mexicanas.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

from .auth import verify_api_key                          # noqa: E402
from .routes.health import router as health_router        # noqa: E402
from .routes.analysis import router as analysis_router   # noqa: E402
from .routes.tasks import router as tasks_router         # noqa: E402

# Health endpoints: públicos (sin autenticación)
app.include_router(health_router, prefix="/api/v1")

# Tasks y análisis requieren X-API-Key
app.include_router(
    tasks_router,
    prefix="/api/v1",
    dependencies=[Depends(verify_api_key)],
)
app.include_router(
    analysis_router,
    prefix="/api/v1",
    dependencies=[Depends(verify_api_key)],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": "Error interno", "detalle": str(exc)},
    )
