# Copilot Financiero — Documentación de API

**Versión:** 2.0.0  
**Modelo LLM:** GPT-4o Mini (OpenAI)  
**Framework:** FastAPI + Uvicorn  
**Formato de respuesta:** JSON (excepto `/pdf` que devuelve binario)

---

## Tabla de contenidos

1. [Descripción general](#1-descripción-general)
2. [Arquitectura del pipeline](#2-arquitectura-del-pipeline)
3. [Instalación y arranque](#3-instalación-y-arranque)
4. [Formatos de archivo de entrada](#4-formatos-de-archivo-de-entrada)
5. [Benchmarks personalizados](#5-benchmarks-personalizados)
6. [Autenticación](#6-autenticación)
7. [Endpoints](#7-endpoints)
   - [GET /health](#get-apiv1health)
   - [GET /health/detailed](#get-apiv1healthdetailed)
   - [GET /tasks/{task_id}](#get-apiv1taskstask_id)
   - [GET /tasks/{task_id}/download](#get-apiv1taskstask_iddownload)
   - [POST /analyze](#post-apiv1analyze)
   - [POST /kpis](#post-apiv1kpis)
   - [POST /health-score](#post-apiv1health-score)
   - [POST /forecast](#post-apiv1forecast)
   - [GET /macro](#get-apiv1macro)
   - [POST /train](#post-apiv1train)
   - [POST /pdf](#post-apiv1pdf)
   - [POST /scenario](#post-apiv1scenario)
8. [Estructura de respuestas](#8-estructura-de-respuestas)
9. [Códigos de error](#9-códigos-de-error)
10. [Ejemplos de integración](#10-ejemplos-de-integración)
11. [Consideraciones para producción](#11-consideraciones-para-producción)

---

## 1. Descripción general

El **Copilot Financiero** es una API REST que recibe los archivos contables de una PyME mexicana y entrega un análisis financiero completo impulsado por inteligencia artificial. No requiere que el cliente instale software adicional: basta con enviar los archivos CSV al servidor y la API devuelve KPIs, Health Score, forecast, recomendaciones generadas por GPT-4o Mini y opcionalmente un reporte PDF listo para presentar.

### Flujo de uso básico

```
Cliente → [BD.csv + ER.csv] → POST /analyze → JSON con análisis completo
Cliente → [BD.csv + ER.csv] → POST /pdf    → Archivo PDF ejecutivo
```

### URL base

```
http://<servidor>:8000/api/v1
```

La documentación interactiva (Swagger UI) está disponible en:

```
http://<servidor>:8000/docs
```

---

## 2. Arquitectura del pipeline

Cuando se llama a `/analyze` o `/pdf`, la API ejecuta internamente las siguientes etapas en secuencia:

| Fase | Módulo | Descripción |
|------|--------|-------------|
| 1 | Parsers | Lectura y validación de archivos BD y ER |
| 2 | KPIs | Cálculo de márgenes, EBITDA, ratios y comparación vs benchmark |
| 3 | ML (XGBoost) | Entrenamiento de modelo de eficiencia por SKU/sucursal y explicación SHAP |
| 4 | Forecast | Proyección de ingresos del siguiente mes (regresión lineal) |
| 5 | Macro | Consulta de índices macroeconómicos (Banxico, INEGI) |
| 6 | Health Score | Score compuesto 0–100 basado en KPIs y contexto macro |
| 7 | RAG | Ingestión de documentos cualitativos y recuperación semántica |
| 8 | LLM | Generación de recomendaciones, narrativa ejecutiva y **contexto macroeconómico sectorial** con GPT-4o Mini — el giro del negocio se infiere automáticamente de los documentos cualitativos y las categorías de SKUs |
| 9 | PDF | Composición del reporte ejecutivo con 7 secciones (solo en `/pdf`) |

Los endpoints individuales (`/kpis`, `/health-score`, `/forecast`) ejecutan únicamente las fases que necesitan, sin llamar al LLM.

---

## 3. Instalación y arranque

### Requisitos

- Python 3.11+
- Variables de entorno configuradas en `.env`

### Variables de entorno requeridas

```env
OPENAI_API_KEY=sk-proj-...        # Clave de API de OpenAI
BANXICO_TOKEN=...                 # Token del API de Banxico (para datos macro)
```

### Arrancar el servidor

```powershell
# Windows
.venv\Scripts\activate
uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --reload
```

```bash
# Linux / Mac
source .venv/bin/activate
uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --reload
```

El flag `--reload` es para desarrollo. En producción omitirlo y usar múltiples workers:

```bash
uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --workers 4
```

---

## 4. Formatos de archivo de entrada

Todos los endpoints que reciben archivos esperan **CSV con codificación UTF-8**. Los archivos pueden tener separador `,` o `;`.

### Archivo BD (Base de Datos de ventas)

Contiene el detalle transaccional por SKU, sucursal y mes.

**Columnas requeridas:**

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `MES` | texto | Nombre del mes y año, ej. `Enero 2026` |
| `LÍNEA DE NEGOCIO` | texto | Sucursal o unidad de negocio |
| `SUBCATEGORÍA 1` | texto | Categoría del producto/servicio |
| `SUBCATEGORÍA 2` | texto | SKU o subcategoría específica |
| `CANTIDAD` | número | Unidades vendidas |
| `SUBTOTAL` | número | Ingresos antes de descuentos |
| `TOTAL` | número | Ingresos netos |
| `COSTO TOTAL SIN IVA` | número | Costo directo sin impuestos |
| `COSTO TOTAL DEL SERVICIO` | número | Costo total incluyendo overhead |
| `UTILIDAD BRUTA` | número | Total - Costo total sin IVA |
| `MARGEN BRUTO` | número | Utilidad bruta / Total (puede ser 0–1 o 0–100) |

**Ejemplo:**

```csv
MES,LÍNEA DE NEGOCIO,SUBCATEGORÍA 1,SUBCATEGORÍA 2,CANTIDAD,SUBTOTAL,TOTAL,COSTO TOTAL SIN IVA,COSTO TOTAL DEL SERVICIO,UTILIDAD BRUTA,MARGEN BRUTO
Enero 2026,Sucursal Norte,Servicios,Consultoría,10,150000,150000,55000,60000,95000,0.633
```

### Archivo ER (Estado de Resultados)

Contiene los gastos operativos y financieros consolidados por mes.

**Filas requeridas** (columna de etiqueta + una columna por cada mes):

| Etiqueta | Descripción |
|----------|-------------|
| `NÓMINA` | Gasto total de nómina |
| `GASTOS COMERCIALES` | Publicidad, ventas, etc. |
| `GASTOS OPERATIVOS` | Arrendamiento, servicios, etc. |
| `GASTOS ADMINISTRATIVOS` | Dirección, finanzas, RRHH |
| `VIÁTICOS` | Gastos de viaje |
| `TOTAL GASTOS DE OPERACIÓN` | Suma de los anteriores |
| `GASTOS FINANCIEROS` | Intereses, comisiones bancarias |
| `COSTO INTEGRAL DE FINANCIAMIENTO` | CIF completo |
| `IMPUESTOS` | ISR, participaciones |

**Ejemplo:**

```csv
CONCEPTO,Enero 2026,Febrero 2026
NÓMINA,320000,325000
GASTOS COMERCIALES,45000,48000
GASTOS OPERATIVOS,80000,82000
GASTOS ADMINISTRATIVOS,60000,61000
VIÁTICOS,12000,10000
TOTAL GASTOS DE OPERACIÓN,197000,201000
GASTOS FINANCIEROS,35000,36000
COSTO INTEGRAL DE FINANCIAMIENTO,35000,36000
IMPUESTOS,48000,50000
```

---

## 5. Benchmarks personalizados

Todos los endpoints que calculan KPIs o Health Score aceptan un parámetro opcional `benchmarks` con los valores de referencia sectoriales. Si no se proporciona, la API usa los defaults del sector PyME mexicano.

El parámetro se envía como **JSON en formato string** en el form-data.

**Campos disponibles:**

| Campo | Default | Descripción |
|-------|---------|-------------|
| `margen_bruto` | `0.65` | Margen bruto objetivo (fracción) |
| `margen_neto` | `0.12` | Margen neto objetivo |
| `margen_ebitda` | `0.20` | Margen EBITDA objetivo |
| `nomina_pct` | `0.30` | Nómina / Revenue máximo aceptable |
| `gastos_op_pct` | `0.50` | Gastos operativos / Revenue máximo |
| `gastos_financieros_pct` | `0.08` | Gastos financieros / Revenue máximo |
| `costo_directo_pct` | `0.35` | Costo directo / Revenue máximo |

**Ejemplo:**

```json
{
  "margen_bruto": 0.60,
  "margen_neto": 0.10,
  "nomina_pct": 0.35
}
```

---

## 6. Autenticación

Todos los endpoints de análisis requieren el header `X-API-Key`. Los endpoints de health check (`/health`, `/health/detailed`) son públicos.

### Configuración de keys

Las keys válidas se definen en la variable de entorno `API_KEYS` del servidor, separadas por coma:

```env
API_KEYS=copilot-DsG41F0y5GsGtz9r25gGmMKtnXyimj0K,copilot-otraclave456
```

Para agregar un nuevo cliente basta con añadir su key a esta lista y reiniciar el servidor. Para revocar acceso, se elimina su key.

### Uso en requests

```http
POST /api/v1/analyze
X-API-Key: copilot-DsG41F0y5GsGtz9r25gGmMKtnXyimj0K
```

```python
# Python
headers = {"X-API-Key": "copilot-DsG41F0y5GsGtz9r25gGmMKtnXyimj0K"}
response = requests.post(url, headers=headers, data={...}, files={...})
```

```bash
# cURL
curl -H "X-API-Key: copilot-DsG41F0y5GsGtz9r25gGmMKtnXyimj0K" \
     -X POST http://localhost:8000/api/v1/analyze ...
```

### Errores de autenticación

| Código | Causa |
|--------|-------|
| `401` | Header `X-API-Key` ausente |
| `403` | Key presente pero inválida o revocada |

> **Modo desarrollo:** si `API_KEYS` no está definido en el `.env`, la autenticación se deshabilita automáticamente y la API acepta todas las peticiones. Se registra un warning en los logs.

---

## 7. Endpoints

---

### GET /api/v1/tasks/{task_id}

Consulta el estado de una tarea asíncrona iniciada por `/analyze` o `/pdf`.

**Parámetros:**

| Parámetro | Ubicación | Descripción |
|-----------|-----------|-------------|
| `task_id` | path | ID de la tarea devuelto al crearla |

**Respuesta — tarea en curso:**

```json
{
  "task_id": "a3f2c1d4-...",
  "type": "analyze",
  "status": "running",
  "created_at": 1749123456.78,
  "completed_at": null,
  "error": null
}
```

**Respuesta — tarea completada (`type: analyze`):**

```json
{
  "task_id": "a3f2c1d4-...",
  "type": "analyze",
  "status": "completed",
  "created_at": 1749123456.78,
  "completed_at": 1749123498.12,
  "error": null,
  "result": { "health_score": 73.4, "recomendaciones": [...] }
}
```

**Respuesta — tarea completada (`type: pdf`):**

```json
{
  "task_id": "b7e9a2f1-...",
  "type": "pdf",
  "status": "completed",
  "download_url": "/api/v1/tasks/b7e9a2f1-.../download"
}
```

**Respuesta — tarea fallida:**

```json
{
  "task_id": "c1d2e3f4-...",
  "status": "failed",
  "error": "ParseError: columna MES no encontrada en el archivo BD"
}
```

| `status` | Significado |
|----------|-------------|
| `pending` | En cola, aún no inicia |
| `running` | Ejecutándose |
| `completed` | Lista — ver campo `result` o `download_url` |
| `failed` | Falló — ver campo `error` |

> Las tareas expiran y se eliminan **1 hora** después de su creación.

---

### GET /api/v1/tasks/{task_id}/download

Descarga el PDF generado por una tarea de tipo `pdf` una vez que su `status` es `completed`.

- **Content-Type:** `application/pdf`
- **Body:** Binario del PDF

---

### GET /api/v1/health

Verificación básica de disponibilidad del servicio.

**Respuesta:**

```json
{
  "status": "ok",
  "version": "2.0.0"
}
```

---

### GET /api/v1/health/detailed

Verifica que la API key de OpenAI esté configurada y que los directorios de datos existan.

**Respuesta:**

```json
{
  "status": "ok",
  "api_key_configured": true,
  "chroma_db_present": true,
  "models_dir_present": true
}
```

| `status` | Significado |
|----------|-------------|
| `"ok"` | Todo listo |
| `"degraded"` | Falta la API key de OpenAI — el endpoint `/analyze` fallará |

---

### POST /api/v1/analyze

**Endpoint principal.** Ejecuta el pipeline completo (fases 1–8) y devuelve el análisis financiero con recomendaciones generadas por GPT-4o Mini en JSON.

**Parámetros (multipart/form-data):**

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `bd_file` | archivo CSV | Sí | Base de datos de ventas |
| `er_file` | archivo CSV | Sí | Estado de Resultados |
| `qualitative_files` | archivos (múltiples) | No | Documentos cualitativos: contratos, reportes, notas (PDF, TXT, XLSX) |
| `cliente_id` | string | No | Identificador del cliente. Default: `"default"` |
| `train_model` | boolean | No | Entrena el modelo ML de eficiencia. Default: `true` |
| `include_macro` | boolean | No | Incluye contexto macroeconómico. Default: `true` |
| `benchmarks` | string (JSON) | No | Benchmarks sectoriales personalizados |
| `config_path` | string | No | Ruta a un archivo JSON de configuración en el servidor |

**Respuesta exitosa (202 — tarea iniciada):**

```json
{
  "task_id": "a3f2c1d4-9e8b-4c2a-b1f3-7d6e5a4c3b2a",
  "status": "pending",
  "poll_url": "/api/v1/tasks/a3f2c1d4-9e8b-4c2a-b1f3-7d6e5a4c3b2a"
}
```

El análisis se ejecuta en segundo plano. Consulta `GET /tasks/{task_id}` hasta que `status` sea `completed`. El campo `result` de esa respuesta contiene el JSON completo:

```json
{
  "cliente_id": "empresa_xyz",
  "periodo": "Enero 2026",
  "generated_at": "2026-06-05T14:32:10.123456+00:00",
  "model_used": "gpt-4o-mini",
  "health_score": 73.4,
  "health_categoria": "saludable",
  "recomendaciones": [
    {
      "id": "REC-001",
      "area": "costos",
      "prioridad": "alta",
      "titulo": "Reducir nómina en Sucursal Norte para alinear al benchmark",
      "descripcion": "La nómina representa el 38.2% de los ingresos en Sucursal Norte, superando el benchmark sectorial de 30%...",
      "evidencia": [
        {
          "tipo": "kpi",
          "fuente": "nomina_pct",
          "valor": "0.382"
        }
      ],
      "accion_sugerida": "Revisar plantilla de Sucursal Norte e identificar posiciones duplicadas o con baja productividad...",
      "impacto_estimado": "Reducción de 8 pp en nomina_pct equivale a ~$240,000 MXN mensuales de ahorro"
    }
  ],
  "narrativa_ejecutiva": "La empresa presenta un Health Score de 73.4/100 en categoría saludable...",
  "shap_top_factores": [
    {
      "feature": "costo_directo",
      "importancia": 0.3241,
      "descripcion": "El costo directo es el principal driver de eficiencia..."
    }
  ],
  "forecast": {
    "mes_proyectado": "Febrero 2026",
    "revenue_proyectado": 1840000.0,
    "tendencia": "creciente",
    "confianza": "media",
    "advertencia": ""
  },
  "contexto_sectorial": {
    "giro_detectado": "restaurantes",
    "resumen": "El sector restaurantero en México enfrenta presión de costos por el alza del salario mínimo (+12% en 2026) y la inflación de insumos alimentarios por encima del INPC general. La reforma laboral de subcontratación impacta la estructura de nómina. La demanda muestra recuperación moderada en zonas urbanas, impulsada por turismo nacional.",
    "factores": [
      { "tipo": "regulatorio", "descripcion": "Incremento del salario mínimo general y zona libre fronteriza para 2026 — presión directa sobre la línea de nómina." },
      { "tipo": "riesgo", "descripcion": "Inflación de alimentos y bebidas por encima del INPC general, con impacto en el costo directo de insumos." },
      { "tipo": "oportunidad", "descripcion": "Recuperación del turismo nacional e internacional en zonas metropolitanas favorece el ticket promedio en segmento premium." }
    ]
  },
  "limitaciones": [
    "Solo 1 mes de datos — tendencias poco confiables."
  ],
  "metadata": {
    "meses_analizados": 1,
    "total_skus": 24,
    "skus_bajo_rendimiento": 5,
    "chunks_cualitativos_usados": 0,
    "prompt_tokens": 1842,
    "completion_tokens": 987
  }
}
```

**Notas:**
- El endpoint responde en milisegundos con un `task_id`; el análisis completo tarda **15–45 segundos** en segundo plano.
- Si `train_model=false`, el tiempo se reduce ~10 segundos pero se omite el análisis SHAP.

---

### POST /api/v1/kpis

Calcula únicamente los KPIs financieros. No llama al LLM. Útil para tableros o verificaciones rápidas.

**Parámetros (multipart/form-data):**

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `bd_file` | archivo CSV | Sí | Base de datos de ventas |
| `er_file` | archivo CSV | Sí | Estado de Resultados |
| `cliente_id` | string | No | Identificador del cliente |
| `benchmarks` | string (JSON) | No | Benchmarks personalizados |
| `config_path` | string | No | Ruta a config JSON en servidor |

**Respuesta exitosa (200):**

```json
{
  "meses_analizados": ["Enero 2026"],
  "por_mes": {
    "Enero 2026": {
      "consolidado": {
        "total_revenue": 1720000.0,
        "margen_bruto": 0.612,
        "ebitda": 344000.0,
        "margen_ebitda": 0.200,
        "margen_neto": 0.108,
        "nomina_pct": 0.382,
        "gastos_financieros_pct": 0.058
      },
      "vs_benchmark": {
        "margen_bruto": {
          "valor": 0.612,
          "benchmark": 0.65,
          "diferencia": -0.038,
          "estado": "alerta"
        },
        "nomina_pct": {
          "valor": 0.382,
          "benchmark": 0.30,
          "diferencia": 0.082,
          "estado": "critico"
        }
      },
      "efficiency_ranking": [
        {
          "sku": "Consultoría Premium",
          "sucursal": "Sucursal Norte",
          "multiplicador_eficiencia": 1.42
        }
      ]
    }
  },
  "tendencias": {},
  "resumen_ejecutivo": {}
}
```

**Estados de benchmark:**

| Estado | Significado |
|--------|-------------|
| `en_rango` | El KPI está dentro del benchmark (±5%) |
| `alerta` | Desviación de 5–15% respecto al benchmark |
| `critico` | Desviación mayor al 15% |

---

### POST /api/v1/health-score

Calcula el Health Score compuesto (0–100) con datos macro opcionales. No llama al LLM.

**Parámetros (multipart/form-data):**

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `bd_file` | archivo CSV | Sí | Base de datos de ventas |
| `er_file` | archivo CSV | Sí | Estado de Resultados |
| `cliente_id` | string | No | Identificador del cliente |
| `include_macro` | boolean | No | Incluir presión inflacionaria en el score. Default: `true` |
| `benchmarks` | string (JSON) | No | Benchmarks personalizados |

**Respuesta exitosa (200):**

```json
{
  "health_score": {
    "por_mes": {
      "Enero 2026": {
        "score_total": 73.4,
        "categoria": "saludable",
        "dimension_mas_debil": "nomina_vs_benchmark",
        "dimension_mas_fuerte": "margen_bruto_vs_benchmark",
        "dimensiones": {
          "margen_bruto_vs_benchmark": {
            "score": 80,
            "peso": 0.30,
            "contribucion": 24.0,
            "valor_base": 0.612,
            "benchmark": 0.65
          },
          "nomina_vs_benchmark": {
            "score": 40,
            "peso": 0.25,
            "contribucion": 10.0,
            "valor_base": 0.382,
            "benchmark": 0.30
          },
          "presion_inflacionaria": {
            "score": 80,
            "peso": 0.20,
            "contribucion": 16.0
          },
          "tendencia_ingresos": {
            "score": 50,
            "peso": 0.15,
            "contribucion": 7.5
          }
        }
      }
    },
    "tendencia_score": {}
  },
  "macro_indices": {
    "narrativa_consolidada": "La inflación general se ubica en 3.8%..."
  }
}
```

**Categorías del Health Score:**

| Rango | Categoría |
|-------|-----------|
| 80–100 | `excelente` |
| 65–79 | `saludable` |
| 50–64 | `en_riesgo` |
| 35–49 | `critico` |
| 0–34 | `muy_critico` |

---

### POST /api/v1/forecast

Proyecta los ingresos del siguiente mes usando regresión lineal sobre el histórico disponible. No llama al LLM.

**Parámetros (multipart/form-data):**

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `bd_file` | archivo CSV | Sí | Base de datos de ventas |
| `er_file` | archivo CSV | Sí | Estado de Resultados |
| `cliente_id` | string | No | Identificador del cliente |

**Respuesta exitosa (200):**

```json
{
  "mes_proyectado": "Febrero 2026",
  "revenue_proyectado": 1840000.0,
  "tendencia": "creciente",
  "variacion_pct_esperada": 0.07,
  "confianza": "media",
  "advertencia": "Forecast basado en 3 meses de datos. Se recomienda al menos 6 meses para mayor precisión.",
  "metodo": "regresion_lineal",
  "puntos_usados": 3,
  "por_sucursal": {
    "Sucursal Norte": {
      "revenue_proyectado": 920000.0,
      "tendencia": "creciente"
    }
  }
}
```

**Niveles de confianza:**

| Confianza | Meses de datos disponibles |
|-----------|---------------------------|
| `baja` | 1–2 meses |
| `media` | 3–5 meses |
| `alta` | 6+ meses |

---

### GET /api/v1/macro

Obtiene los índices macroeconómicos de México (inflación, tasa de referencia Banxico, tipo de cambio). Los resultados se cachean 1 hora para evitar llamadas innecesarias.

**Parámetros (query string):**

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `cliente_id` | string | No | Para configuración sectorial. Default: `"default"` |

**Respuesta exitosa (200):**

```json
{
  "macro_data": {
    "inflacion_general": 3.82,
    "inflacion_subyacente": 3.57,
    "tasa_banxico": 8.50,
    "tipo_cambio_usd": 17.23,
    "fecha_consulta": "2026-06-05"
  },
  "macro_indices": {
    "presion_inflacionaria": 0.45,
    "ambiente_tasas": "restrictivo",
    "narrativa_consolidada": "La inflación general de 3.82% se mantiene dentro del rango objetivo..."
  }
}
```

---

### POST /api/v1/train

Entrena el modelo de machine learning (XGBoost) de eficiencia por SKU y lo guarda en disco. Se puede llamar independientemente para pre-entrenar el modelo antes de ejecutar `/analyze`.

**Parámetros (multipart/form-data):**

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `bd_file` | archivo CSV | Sí | Base de datos de ventas |
| `cliente_id` | string | No | El modelo se guarda en `models/{cliente_id}/`. Default: `"default"` |

**Respuesta exitosa (200):**

```json
{
  "train_metrics": {
    "r2_score": 0.847,
    "mae": 0.0312,
    "feature_importance": {
      "costo_directo": 0.324,
      "cantidad": 0.218,
      "margen_bruto": 0.196
    }
  },
  "trained_at": "2026-06-05T14:10:00+00:00"
}
```

---

### POST /api/v1/pdf

Ejecuta el pipeline completo y devuelve un **reporte PDF ejecutivo** listo para presentar. Incluye: portada con Health Score, KPIs vs benchmark, análisis SHAP, forecast, contexto macro y recomendaciones del LLM.

**Parámetros (multipart/form-data):**

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `bd_file` | archivo CSV | Sí | Base de datos de ventas |
| `er_file` | archivo CSV | Sí | Estado de Resultados |
| `qualitative_files` | archivos (múltiples) | No | Documentos cualitativos adicionales |
| `cliente_id` | string | No | Aparece en la portada del PDF. Default: `"default"` |
| `train_model` | boolean | No | Entrenar modelo ML para SHAP. Default: `true` |
| `include_macro` | boolean | No | Incluir sección macro. Default: `true` |
| `include_recommendations` | boolean | No | Llamar al LLM para recomendaciones. Default: `true` |
| `benchmarks` | string (JSON) | No | Benchmarks personalizados |

**Respuesta exitosa (202 — tarea iniciada):**

```json
{
  "task_id": "b7e9a2f1-4d3c-4a5e-8f2b-1c0d9e8a7b6c",
  "status": "pending",
  "poll_url": "/api/v1/tasks/b7e9a2f1-4d3c-4a5e-8f2b-1c0d9e8a7b6c"
}
```

El PDF se genera en segundo plano. Consulta `GET /tasks/{task_id}` hasta `status: completed` y luego descarga con `GET /tasks/{task_id}/download`.

El PDF contiene las siguientes secciones:

1. **Portada** — Nombre del cliente, período, Health Score destacado y resumen ejecutivo
2. **KPIs consolidados** — Tarjetas de métricas clave y tabla vs benchmark con semáforo de colores
3. **Dimensiones del Health Score** — Barras por dimensión ponderada
4. **Análisis ML / SHAP** — Top 3 factores de eficiencia y narrativa explicativa
5. **Forecast e Índices Macro** — Proyección de ingresos por sucursal y contexto económico general
6. **Contexto Macroeconómico Sectorial** — Giro del negocio detectado automáticamente, entorno del sector en México y factores externos clasificados (regulatorio, riesgo, oportunidad, tendencia)
7. **Recomendaciones del Copilot** — Entre 3 y 5 recomendaciones con evidencia, acción e impacto estimado; todo el texto con word-wrap garantizado

**Nota:** Con `include_recommendations=false` el PDF se genera sin llamar al LLM en ~5 segundos (la sección de Contexto Sectorial requiere el LLM). Con recomendaciones, el tiempo total es de 20–50 segundos.

---

### POST /api/v1/scenario

Ejecuta una simulación **Monte Carlo** sobre los datos financieros del cliente, proyectando la distribución de KPIs ante variaciones en las variables clave. Responde de forma **síncrona** en menos de 2 segundos — no requiere polling.

**Parámetros (multipart/form-data):**

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `bd_file` | archivo CSV | Sí | Base de datos de ventas |
| `er_file` | archivo CSV | Sí | Estado de Resultados |
| `variaciones` | string (JSON) | Sí | Variación esperada (%) por variable |
| `sigmas` | string (JSON) | No | Incertidumbre por variable. Si se omite se usan los defaults |
| `n_simulaciones` | integer | No | Iteraciones (1 000 – 100 000). Default: `10000` |
| `semilla` | integer | No | Semilla aleatoria para resultados reproducibles |
| `benchmarks` | string (JSON) | No | Benchmarks personalizados para calcular probabilidades |
| `cliente_id` | string | No | Identificador del cliente |

**Variables disponibles en `variaciones` y `sigmas`:**

| Variable | Descripción | Sigma default |
|----------|-------------|---------------|
| `revenue` | Ingresos totales | 0.05 |
| `costo_directo` | Costo directo de ventas | 0.04 |
| `nomina` | Gasto de nómina | 0.03 |
| `gastos_financieros` | Gastos financieros | 0.02 |

**Ejemplo de `variaciones`:** `{"revenue": 0.08, "nomina": -0.05}` → +8% ingresos esperado, -5% nómina.

**Respuesta exitosa (200):**

```json
{
  "n_simulaciones": 10000,
  "mes_base": "Enero 2026",
  "variables_input": {
    "variaciones_esperadas": {"revenue": 0.08, "nomina": -0.05},
    "sigmas_incertidumbre": {"revenue": 0.05, "costo_directo": 0.04, "nomina": 0.03, "gastos_financieros": 0.02}
  },
  "distribuciones": {
    "margen_bruto": {
      "p10": 0.548, "p25": 0.581, "p50": 0.614,
      "p75": 0.648, "p90": 0.681,
      "media": 0.614, "desviacion": 0.042,
      "valores": [0.601, 0.623, "...500 muestras para histograma..."]
    },
    "ebitda": { "p10": 180000, "p50": 310000, "p90": 445000, "..." : "..." },
    "revenue": { "...": "..." },
    "margen_ebitda": { "...": "..." },
    "margen_neto": { "...": "..." },
    "nomina_pct": { "...": "..." },
    "gastos_financieros_pct": { "...": "..." }
  },
  "probabilidades_benchmark": {
    "margen_bruto_sobre_benchmark": 0.72,
    "nomina_bajo_benchmark": 0.88,
    "gastos_fin_bajo_benchmark": 0.95,
    "margen_neto_sobre_benchmark": 0.61,
    "ebitda_positivo": 0.97
  },
  "narrativa": "Bajo el escenario simulado con 10,000 iteraciones, el margen bruto proyectado tiene una mediana de 61.4% con 72% de probabilidad de superar el benchmark sectorial..."
}
```

**Ejemplo de uso (Python):**

```python
import requests, json

HEADERS = {"X-API-Key": "copilot-DsG41F0y5GsGtz9r25gGmMKtnXyimj0K"}

with open("ventas_enero.csv", "rb") as bd, open("er_enero.csv", "rb") as er:
    r = requests.post(
        "http://localhost:8000/api/v1/scenario",
        headers=HEADERS,
        data={
            "cliente_id": "empresa_xyz",
            "variaciones": json.dumps({"revenue": 0.08, "nomina": -0.05}),
            "n_simulaciones": "10000",
            "benchmarks": json.dumps({"margen_bruto": 0.60}),
        },
        files={"bd_file": ("ventas.csv", bd, "text/csv"), "er_file": ("er.csv", er, "text/csv")},
    )

res = r.json()
print(res["narrativa"])
print(f"Prob. EBITDA positivo: {res['probabilidades_benchmark']['ebitda_positivo']:.0%}")
```

---

## 8. Estructura de respuestas

### Objeto `contexto_sectorial`

Generado por el LLM a partir de los documentos cualitativos y las categorías de SKUs. Si no hay documentos, el giro se infiere de los nombres de categorías del archivo BD.

```json
{
  "giro_detectado": "string — sector o giro identificado (ej: restaurantes, retail, manufactura)",
  "resumen": "string — párrafo de 4-6 oraciones con el entorno macroeconómico específico del giro en México",
  "factores": [
    {
      "tipo": "regulatorio | tendencia | riesgo | oportunidad",
      "descripcion": "string — descripción concisa del factor y su impacto potencial"
    }
  ]
}
```

---

### Objeto `recomendacion`

```json
{
  "id": "REC-001",
  "area": "costos",
  "prioridad": "alta",
  "titulo": "string",
  "descripcion": "string — análisis detallado con cifras y causa raíz",
  "evidencia": [
    {
      "tipo": "kpi | shap | sku | macro | documento",
      "fuente": "nombre del indicador o documento",
      "valor": "valor numérico exacto"
    }
  ],
  "accion_sugerida": "string — pasos concretos y secuenciados",
  "impacto_estimado": "string — estimación cuantitativa del impacto"
}
```

**Áreas posibles:** `rentabilidad`, `costos`, `sucursales`, `mix_productos`, `macro`, `operaciones`

**Prioridades:** `alta`, `media`, `baja`

---

## 9. Códigos de error

| Código HTTP | Causa | Respuesta |
|-------------|-------|-----------|
| `422` | Archivo CSV con formato incorrecto o columnas faltantes | `{"detail": "Error al procesar los archivos: ColumnaFaltante"}` |
| `422` | JSON de `benchmarks` inválido | `{"detail": "benchmarks debe ser un JSON válido"}` |
| `500` | Error interno del servidor (fallo en LLM, error inesperado) | `{"error": "Error interno", "detalle": "mensaje"}` |

---

## 10. Ejemplos de integración

### Python (con `requests`)

#### Análisis completo (con polling)

```python
import requests
import json
import time

BASE = "http://localhost:8000/api/v1"
HEADERS = {"X-API-Key": "copilot-DsG41F0y5GsGtz9r25gGmMKtnXyimj0K"}

# 1. Lanzar tarea
with open("ventas_enero.csv", "rb") as bd, open("er_enero.csv", "rb") as er:
    response = requests.post(f"{BASE}/analyze", headers=HEADERS, data={
        "cliente_id": "empresa_xyz",
        "train_model": "true",
        "benchmarks": json.dumps({"margen_bruto": 0.60, "nomina_pct": 0.35}),
    }, files={
        "bd_file": ("ventas_enero.csv", bd, "text/csv"),
        "er_file": ("er_enero.csv", er, "text/csv"),
    })

task_id = response.json()["task_id"]
print(f"Tarea iniciada: {task_id}")

# 2. Polling hasta completarse
while True:
    status = requests.get(f"{BASE}/tasks/{task_id}", headers=HEADERS).json()
    print(f"Estado: {status['status']}")
    if status["status"] == "completed":
        resultado = status["result"]
        print(f"Health Score: {resultado['health_score']:.1f} ({resultado['health_categoria']})")
        for rec in resultado["recomendaciones"]:
            print(f"  [{rec['prioridad'].upper()}] {rec['titulo']}")
        break
    elif status["status"] == "failed":
        print(f"Error: {status['error']}")
        break
    time.sleep(5)
```

#### Descargar PDF (con polling)

```python
import requests
import json
import time

BASE = "http://localhost:8000/api/v1"
HEADERS = {"X-API-Key": "copilot-DsG41F0y5GsGtz9r25gGmMKtnXyimj0K"}

# 1. Lanzar tarea de PDF
with open("ventas_enero.csv", "rb") as bd, open("er_enero.csv", "rb") as er:
    response = requests.post(f"{BASE}/pdf", headers=HEADERS, data={
        "cliente_id": "empresa_xyz",
        "include_recommendations": "true",
        "benchmarks": json.dumps({"margen_bruto": 0.60}),
    }, files={
        "bd_file": ("ventas_enero.csv", bd, "text/csv"),
        "er_file": ("er_enero.csv", er, "text/csv"),
    })

task_id = response.json()["task_id"]

# 2. Polling
while True:
    status = requests.get(f"{BASE}/tasks/{task_id}", headers=HEADERS).json()
    if status["status"] == "completed":
        pdf = requests.get(f"{BASE}/tasks/{task_id}/download", headers=HEADERS)
        with open("reporte.pdf", "wb") as f:
            f.write(pdf.content)
        print("PDF guardado como reporte.pdf")
        break
    elif status["status"] == "failed":
        print(f"Error: {status['error']}")
        break
    time.sleep(5)
```

#### Solo KPIs (sin LLM, respuesta rápida)

```python
import requests

url = "http://localhost:8000/api/v1/kpis"

with open("ventas_enero.csv", "rb") as bd, open("er_enero.csv", "rb") as er:
    response = requests.post(url, headers=HEADERS, data={
        "cliente_id": "empresa_xyz",
    }, files={
        "bd_file": ("ventas_enero.csv", bd, "text/csv"),
        "er_file": ("er_enero.csv", er, "text/csv"),
    })

kpis = response.json()
consolidado = kpis["por_mes"]["Enero 2026"]["consolidado"]
print(f"Margen bruto: {consolidado['margen_bruto']:.1%}")
print(f"EBITDA: ${consolidado['ebitda']:,.0f}")
```

### cURL

#### Health check

```bash
curl http://localhost:8000/api/v1/health
```

#### Análisis completo (lanzar tarea)

```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "X-API-Key: copilot-DsG41F0y5GsGtz9r25gGmMKtnXyimj0K" \
  -F "bd_file=@ventas_enero.csv" \
  -F "er_file=@er_enero.csv" \
  -F "cliente_id=empresa_xyz" \
  -F 'benchmarks={"margen_bruto":0.60,"nomina_pct":0.35}'
# Responde: {"task_id": "...", "status": "pending", "poll_url": "..."}
```

#### Consultar estado de tarea

```bash
curl http://localhost:8000/api/v1/tasks/<task_id> \
  -H "X-API-Key: copilot-DsG41F0y5GsGtz9r25gGmMKtnXyimj0K"
```

#### Lanzar PDF y descargarlo

```bash
# 1. Lanzar
curl -X POST http://localhost:8000/api/v1/pdf \
  -H "X-API-Key: copilot-DsG41F0y5GsGtz9r25gGmMKtnXyimj0K" \
  -F "bd_file=@ventas_enero.csv" \
  -F "er_file=@er_enero.csv" \
  -F "cliente_id=empresa_xyz" \
  -F "include_recommendations=true"
# 2. Descargar cuando status=completed
curl http://localhost:8000/api/v1/tasks/<task_id>/download \
  -H "X-API-Key: copilot-DsG41F0y5GsGtz9r25gGmMKtnXyimj0K" \
  --output reporte.pdf
```

---

## 11. Consideraciones para producción

La versión actual es funcional para integraciones reales. Los siguientes puntos son recomendaciones para un despliegue productivo a escala:

### Persistencia de tareas
Las tareas async se almacenan en memoria con TTL de 1 hora. Si el servidor se reinicia, las tareas en vuelo se pierden. Para alta disponibilidad se recomienda:
- Migrar el store de tareas a **Redis** con expiración nativa
- Usar **Celery + Redis** para una cola de trabajos distribuida con reintentos automáticos

### Rate limiting
Agregar límites de llamadas por API Key para controlar costos del LLM y evitar abuso. Se puede implementar con middleware FastAPI o un API Gateway externo (Kong, AWS API Gateway, Nginx).

### HTTPS
En producción, servir la API detrás de un proxy inverso (nginx, Caddy) con certificado TLS. La API ya incluye CORS permisivo — restringir `allow_origins` a los dominios del cliente.

### Logging y monitoreo
Implementar logging estructurado (JSON) por request, incluyendo `cliente_id`, `prompt_tokens`, `completion_tokens` y tiempos de cada fase, para monitorear costos de API y detectar cuellos de botella.

### Escalado horizontal
`uvicorn` con `--workers N` distribuye carga entre procesos. Considerar que el store de tareas en memoria no se comparte entre workers — requiere la migración a Redis mencionada arriba.

### Gestión de API Keys
Agregar o revocar acceso editando `API_KEYS` en el `.env` y reiniciando el servidor. Para gestión dinámica sin reinicio, migrar la validación a una base de datos.
