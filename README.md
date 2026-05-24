  # Copilot Financiero Eq.2

  Copiloto financiero impulsado por IA que analiza Estados de Resultados, calcula indicadores clave y genera recomendaciones basadas en evidencia usando la API de Claude (Anthropic).

  ---

  ## Descripcion general

  El sistema toma un archivo financiero (Excel, PDF de texto o PDF escaneado) junto con documentos cualitativos opcionales (reportes, actas, notas), y produce:

  - JSON normalizado del Estado de Resultados
  - Indicadores financieros por mes y sucursal (margen bruto, EBITDA, margen neto, alertas)
  - Contexto cualitativo recuperado por busqueda semantica
  - Recomendaciones accionables generadas por Claude, citando valores reales del analisis

  Hay dos interfaces Streamlit incluidas:

  | Archivo | Publico | Descripcion |
  |---|---|---|
  | `app_consultant.py` | Usuario final | Carga archivo → ve indicadores y graficas → descarga reporte PDF |
  | `app.py` | Desarrollador | Demo tecnica con 6 pestanas, una por fase del pipeline |

  ---

  ## Requisitos del sistema

  - Python 3.11+
  - Una `ANTHROPIC_API_KEY` valida (modelo `claude-sonnet-4-20250514`)
  - Para PDFs escaneados (opcional):
    - [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) (Windows) o `brew install tesseract`
    - [Poppler](https://github.com/oschwartz10612/poppler-windows/releases) (Windows) o `brew install poppler`

  ---

  ## Instalacion

  ```bash
  # 1. Clonar el repositorio
  git clone <repo-url>
  cd Copilot-Financiero-Eq.2

  # 2. Crear y activar entorno virtual
  python -m venv .venv
  .venv\Scripts\activate          # Windows
  # source .venv/bin/activate     # macOS / Linux

  # 3. Instalar dependencias
  pip install -r financial_normalizer/requirements.txt

  # 4. Configurar variables de entorno
  # Crea un archivo .env en la raiz con:
  # ANTHROPIC_API_KEY=sk-ant-...
  ```

  ---

  ## Uso rapido

  ### Interfaz de usuario final

  ```bash
  streamlit run app_consultant.py
  ```

  1. Ingresa el **ID de cliente**
  2. Sube el **Estado de Resultados** (Excel o PDF)
  3. Sube documentos de contexto opcionales (PDF, TXT, MD)
  4. Haz clic en **Analizar**
  5. Revisa indicadores, graficas y recomendaciones
  6. Descarga el **Reporte PDF**

  ### Demo tecnica (para desarrolladores)

  ```bash
  streamlit run app.py
  ```

  Muestra en detalle cada fase del pipeline, los datos intermedios, embeddings, queries generadas y el JSON completo de cada etapa.

  ### Uso como libreria

  ```python
  from financial_normalizer.normalizer import normalize

  resultado = normalize("ruta/al/estado_resultados.xlsx", cliente_id="mi_cliente")
  print(resultado["meses"]["ENERO 2026"]["kpis"]["ebitda"])
  ```

  ---

  ## Pipeline de 6 fases

  ```
  Fase 0  Normalizacion     Excel / PDF texto / PDF escaneado / LLM fallback  →  JSON estandar
  Fase 1  Indicadores       Python puro, sin LLM  →  margenes, alertas, estructura de costos
  Fase 2  Ingesta docs      Carga y chunking de documentos cualitativos  →  DocumentStore
  Fase 3  Embeddings        all-MiniLM-L6-v2, 384 dimensiones  →  ChromaDB
  Fase 4  Orquestador       Indicadores + contexto cualitativo  →  AnalysisPackage
  Fase 5  Recomendaciones   Claude API  →  RecommendationReport con evidencia citada
  ```

  ### Fase 0 — Normalizacion

  El modulo `normalizer.py` selecciona automaticamente el parser correcto:

  | Tipo de archivo | Parser usado |
  |---|---|
  | `.xlsx / .xls / .xlsm` | `parser_excel` — openpyxl + pandas, maneja celdas combinadas |
  | PDF con texto | `parser_pdf_texto` — pdfplumber, extraccion de tablas y lineas |
  | PDF escaneado | `parser_pdf_escaneado` — pdf2image + OpenCV + pytesseract |
  | Cualquier otro | `parser_llm` — Claude API como fallback universal |

  Salida: JSON con estructura `{ "cliente_id", "periodo", "meses": { "MES": { "ventas": {...}, "kpis": {...} } } }`

  El `validator.py` verifica consistencia aritmetica con tolerancia del 2%.

  ### Fase 1 — Indicadores

  Calculo determinista (sin LLM) de:

  - **Rentabilidad**: margen bruto, margen EBITDA, margen neto
  - **Estructura de costos**: nomina/ventas, gastos operativos/ventas, costo/ventas
  - **Analisis por sucursal**: venta, egreso, margen, participacion, alerta si margen < umbral
  - **Alertas**: severidad alta/media/baja con tipo y umbral superado

  Umbrales por defecto: margen bruto < 40%, EBITDA < 10%, margen neto < 5%, margen sucursal < 15%, nomina/ventas > 30%, gastos op/ventas > 40%.

  ### Fases 2 y 3 — Ingesta y Embeddings

  Los documentos cualitativos se fragmentan en chunks de ~500 caracteres con solapamiento de 50 caracteres. Cada chunk se convierte en un vector de 384 dimensiones usando el modelo `all-MiniLM-L6-v2` (sentence-transformers) y se persiste en ChromaDB.

  ### Fase 4 — Orquestador

  Para cada mes con datos, genera entre 4 y 8 queries de busqueda semantica basadas en los indicadores (las 4 bases siempre se incluyen; las condicionales se activan cuando se superan umbrales). Recupera los 8 chunks mas relevantes por mes, los deduplica y los incluye en el `AnalysisPackage`.

  ### Fase 5 — Motor de Recomendaciones

  Construye un prompt estructurado con los indicadores reales y el contexto cualitativo recuperado, y llama a `claude-sonnet-4-20250514`. Claude responde en JSON con recomendaciones que citan exclusivamente valores del `AnalysisPackage` (no inventa numeros). Cada recomendacion incluye: `id`, `titulo`, `descripcion`, `prioridad` (alta/media/baja), `evidencia[]` y `accion_sugerida`.

  ---

  ## Estructura del proyecto

  ```
  Copilot-Financiero-Eq.2/
  ├── app_consultant.py              # Interfaz de usuario final (Streamlit)
  ├── app.py                         # Demo tecnica para desarrolladores (Streamlit)
  ├── .env                           # Variables de entorno (no se versiona)
  ├── financial_normalizer/
  │   ├── normalizer.py              # Entrada principal, seleccion de parser
  │   ├── validator.py               # Verificacion aritmetica (tolerancia 2%)
  │   ├── indicators.py              # Calculo de KPIs y alertas
  │   ├── orchestrator.py            # Orquestador cuantitativo + cualitativo
  │   ├── recommendations.py         # Motor de recomendaciones con Claude API
  │   ├── profiles.py                # Perfiles de cliente (sinonimos, escala, hints)
  │   ├── utils.py                   # Helpers: clean_currency, almost_equal, detect_months
  │   ├── parsers/
  │   │   ├── parser_excel.py        # openpyxl + pandas
  │   │   ├── parser_pdf_texto.py    # pdfplumber
  │   │   ├── parser_pdf_escaneado.py# pdf2image + OpenCV + pytesseract
  │   │   └── parser_llm.py          # Fallback con Claude API
  │   ├── ingestion/
  │   │   ├── document_loader.py     # Carga de PDF, TXT, MD
  │   │   ├── chunker.py             # Fragmentacion de texto
  │   │   ├── document_store.py      # Almacen en memoria de documentos y chunks
  │   │   └── vector_store.py        # ChromaDB + sentence-transformers
  │   ├── requirements.txt
  │   └── tests/
  │       ├── fixtures.py            # Datos sinteticos aritmeticamente consistentes
  │       ├── create_fixtures.py     # Genera .xlsx y .txt de prueba
  │       ├── test_validator.py
  │       ├── test_indicators.py
  │       ├── test_ingestion.py
  │       ├── test_orchestrator.py
  │       ├── test_recommendations.py
  │       └── test_vector_store.py
  └── chroma_db/                     # Base de datos vectorial persistente (local)
  ```

  ---

  ## Tests

  ```bash
  # Ejecutar todos los tests (226 tests, 0 fallos)
  pytest

  # Solo un modulo
  pytest financial_normalizer/tests/test_validator.py -v

  # Generar fixtures sinteticas
  python -m financial_normalizer.tests.create_fixtures
  ```

  ---

  ## Perfiles de cliente

  Edita `financial_normalizer/profiles.py` para agregar sinonimos, hints o factores de escala por cliente:

  ```python
  PROFILES["mi_cliente"] = {
      "hint": "Este cliente reporta costos de alimentos separado bajo 'Costo Alimentos'.",
      "synonyms": {"Costo Alimentos": "total_costo"},
      "scale": 1000.0,  # reporta en miles
  }
  ```

  ---

  ## Variables de entorno

  | Variable | Requerida | Descripcion |
  |---|---|---|
  | `ANTHROPIC_API_KEY` | Si | Clave API de Anthropic para los parsers LLM y el motor de recomendaciones |

  ---

  ## Dependencias principales

  | Paquete | Uso |
  |---|---|
  | `anthropic` | Claude API (parser LLM + recomendaciones) |
  | `streamlit` | Interfaces de usuario |
  | `chromadb` | Base de datos vectorial para busqueda semantica |
  | `sentence-transformers` | Modelo de embeddings (all-MiniLM-L6-v2) |
  | `plotly` | Graficas interactivas |
  | `pandas` / `openpyxl` | Parseo de Excel |
  | `pdfplumber` | Extraccion de texto en PDFs |
  | `reportlab` | Exportacion a PDF |
  | `pytesseract` | OCR para PDFs escaneados (opcional) |
