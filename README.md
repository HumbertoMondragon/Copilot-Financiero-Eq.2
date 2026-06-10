# Copilot Financiero Eq.2

Copiloto financiero con IA para PyMEs mexicanas. Analiza ventas y estado de resultados, calcula KPIs, genera un Health Score compuesto, proyecta ingresos y produce recomendaciones accionables mediante GPT-4o Mini.

El proyecto se entrega como dos componentes complementarios:

| Componente | Comando | Descripcion |
|---|---|---|
| **API REST** | `uvicorn src.api.app:app` | 12 endpoints FastAPI para integrarse sin instalar nada adicional |
| **Interfaz Streamlit** | `streamlit run streamlit/app.py` | Interfaz de 11 fases que visualiza cada etapa del pipeline |

---

## Requisitos

- Python 3.11+
- Variables de entorno en `.env` (ver seccion siguiente)

---

## Instalacion

```powershell
# 1. Clonar el repositorio
git clone <repo-url>
cd Copilot-Financiero-Eq.2

# 2. Crear y activar entorno virtual
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

# 3. Instalar dependencias
pip install fastapi uvicorn openai chromadb sentence-transformers xgboost shap numpy pandas fpdf2 streamlit plotly python-dotenv requests
```

---

## Variables de entorno

Crea un archivo `.env` en la raiz con:

```env
OPENAI_API_KEY=sk-proj-...        # Clave de API de OpenAI (GPT-4o Mini)
BANXICO_TOKEN=...                 # Token del API de Banxico (datos macro)
API_KEYS=copilot-<tu-clave>       # Keys de acceso a la API (separadas por coma)
```

> Si `API_KEYS` no esta definido, la autenticacion se deshabilita automaticamente (modo desarrollo).

---

## Uso rapido

### API REST

```powershell
# Activar entorno y arrancar el servidor
.venv\Scripts\activate
uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --reload
```

Documentacion interactiva disponible en `http://localhost:8000/docs`.

Llamada de ejemplo:

```python
import requests, time

BASE = "http://localhost:8000/api/v1"
HEADERS = {"X-API-Key": "copilot-<tu-clave>"}

with open("ventas.csv", "rb") as bd, open("er.csv", "rb") as er:
    r = requests.post(f"{BASE}/analyze", headers=HEADERS,
        data={"cliente_id": "mi_empresa"},
        files={"bd_file": ("ventas.csv", bd, "text/csv"),
               "er_file": ("er.csv", er, "text/csv")})

task_id = r.json()["task_id"]

# Polling hasta que termine
while True:
    s = requests.get(f"{BASE}/tasks/{task_id}", headers=HEADERS).json()
    if s["status"] == "completed":
        print(f"Health Score: {s['result']['health_score']}")
        break
    elif s["status"] == "failed":
        print(f"Error: {s['error']}")
        break
    time.sleep(5)
```

### Interfaz Streamlit

```powershell
.venv\Scripts\activate
streamlit run streamlit/app.py
```

La interfaz guia al usuario por las 11 fases del pipeline: carga de archivos, parseo, KPIs, ML/SHAP, forecast, indices macro, Health Score, ingestion de documentos cualitativos, recomendaciones LLM, reporte PDF y simulacion de escenarios Monte Carlo.

---

## Pipeline de 11 fases

| Fase | Nombre | Descripcion |
|------|--------|-------------|
| 1 | Carga de archivos | BD (ventas por SKU) + ER (gastos) en CSV |
| 2 | Parseo | Validacion de columnas y normalizacion |
| 3 | KPIs | Margenes, EBITDA, alertas vs benchmark |
| 4 | ML / XGBoost | Eficiencia por SKU, entrenamiento y prediccion |
| 5 | SHAP | Factores explicativos del modelo y narrativa |
| 6 | Forecast | Proyeccion de ingresos (regresion lineal) |
| 7 | Macro | Inflacion, tasa Banxico, tipo de cambio (INEGI/Banxico) |
| 8 | Health Score | Score compuesto 0-100 por mes con dimensiones ponderadas |
| 9 | Documentos cualitativos | Ingestion RAG, embeddings, ChromaDB |
| 10 | Recomendaciones LLM | GPT-4o Mini genera recomendaciones, narrativa ejecutiva y contexto macroeconomico sectorial (giro inferido de los documentos cualitativos y categorias de SKUs) |
| 11 | Escenarios Monte Carlo | Simulacion what-if con distribuciones de probabilidad |

---

## Estructura del proyecto

```
Copilot-Financiero-Eq.2/
├── src/
│   ├── api/
│   │   ├── app.py              # FastAPI app y registro de routers
│   │   ├── auth.py             # Autenticacion por X-API-Key
│   │   ├── models.py           # Modelos Pydantic
│   │   ├── tasks.py            # Store de tareas en memoria (TTL: 1h)
│   │   └── routes/
│   │       ├── analysis.py     # Endpoints de analisis (/analyze, /kpis, /pdf, etc.)
│   │       ├── health.py       # Endpoints publicos de health check
│   │       └── tasks.py        # Endpoints de polling y descarga
│   ├── ingestion/
│   │   ├── chunker.py          # Fragmentacion de texto en chunks
│   │   ├── document_loader.py  # Carga de PDF, TXT, XLSX
│   │   ├── document_store.py   # Store en memoria de documentos
│   │   └── vector_store.py     # ChromaDB + sentence-transformers
│   ├── ml/
│   │   ├── features.py         # Ingenieria de caracteristicas
│   │   ├── predictor.py        # Prediccion con modelo guardado
│   │   └── trainer.py          # Entrenamiento XGBoost
│   └── pipeline/
│       ├── engine.py           # Motor LLM (GPT-4o Mini via OpenAI SDK)
│       ├── forecast.py         # Proyeccion de ingresos
│       ├── health_score.py     # Health Score compuesto
│       ├── integrator.py       # Orquestador del pipeline completo
│       ├── kpis.py             # Calculo de KPIs financieros
│       ├── macro.py            # Indices macroeconomicos
│       ├── report_generator.py # Generacion de PDF (fpdf2)
│       ├── scenario.py         # Simulacion Monte Carlo
│       ├── shap_translator.py  # Narrativa SHAP
│       └── parsers/
│           ├── parser_bd.py    # Parser CSV de ventas
│           ├── parser_er.py    # Parser CSV de estado de resultados
│           └── parser_utils.py
├── streamlit/
│   └── app.py                  # Interfaz de 11 fases
├── tests/
│   ├── fixtures/
│   │   ├── sample_bd.csv
│   │   └── sample_er.csv
│   └── test_*.py               # Suite de tests
├── configs/
│   └── nama.json               # Ejemplo de configuracion de cliente
├── models/
│   └── default/
│       └── xgboost_efficiency.pkl
├── .env                        # Variables de entorno (no se versiona)
├── .gitignore
├── load_env.ps1                # Script PowerShell para cargar el entorno
└── API_DOCUMENTATION.md        # Documentacion completa de la API
```

---

## Tests

```powershell
# Ejecutar todos los tests
pytest tests/

# Un modulo especifico
pytest tests/test_kpis.py -v
```

---

## Endpoints principales

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| `GET` | `/api/v1/health` | Health check publico |
| `GET` | `/api/v1/health/detailed` | Verifica API keys y directorios |
| `POST` | `/api/v1/analyze` | Analisis completo con LLM (async, 202) |
| `POST` | `/api/v1/kpis` | Solo KPIs, sin LLM (sincrono) |
| `POST` | `/api/v1/health-score` | Health Score compuesto (sincrono) |
| `POST` | `/api/v1/forecast` | Proyeccion de ingresos (sincrono) |
| `GET` | `/api/v1/macro` | Indices macroeconomicos |
| `POST` | `/api/v1/train` | Entrenar modelo XGBoost |
| `POST` | `/api/v1/pdf` | Reporte PDF ejecutivo (async, 202) |
| `POST` | `/api/v1/scenario` | Simulacion Monte Carlo (sincrono) |
| `GET` | `/api/v1/tasks/{id}` | Estado de tarea async |
| `GET` | `/api/v1/tasks/{id}/download` | Descargar PDF generado |

Ver `API_DOCUMENTATION.md` para la especificacion completa con ejemplos.

Ver `docs/ml_xgboost.md` para el detalle del modelo XGBoost: features, ajuste de hiperparámetros y métricas de evaluación.

---

## Dependencias principales

| Paquete | Uso |
|---|---|
| `openai` | GPT-4o Mini (recomendaciones y narrativa ejecutiva) |
| `fastapi` + `uvicorn` | API REST |
| `streamlit` | Interfaz de 11 fases |
| `chromadb` | Base de datos vectorial para RAG |
| `sentence-transformers` | Embeddings (all-MiniLM-L6-v2) |
| `xgboost` + `shap` | Modelo de eficiencia por SKU |
| `numpy` + `pandas` | Calculo de KPIs y simulacion Monte Carlo |
| `fpdf2` | Generacion de reportes PDF |
| `plotly` | Graficas interactivas en Streamlit |
