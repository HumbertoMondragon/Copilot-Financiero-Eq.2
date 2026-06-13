# Pipeline técnico — Detalles de implementación

Complementa `ml_xgboost.md`. Cubre las decisiones de implementación del pipeline general: parseo del ER, forecast, Health Score, RAG y Monte Carlo.

---

## Parser del ER — manejo de estructura no tabular

El CSV del estado de resultados no sigue el formato tabular estándar. Su estructura tiene tres zonas:

- **Fila 0:** título o metadata del reporte (ignorada; el parser lee sin encabezado con `header=None`).
- **Fila 1:** nombres de los meses en las columnas 1 en adelante. El parser la lee explícitamente con `df.iloc[1]` para extraer los índices de columna por mes.
- **Filas 2+:** datos. Solo la primera columna identifica el tipo de fila (etiqueta de concepto).

La lógica para filtrar subtotales, encabezados intermedios y filas vacías es por **exclusión implícita**: el parser define `_KPI_MAP`, un diccionario con las únicas 12 etiquetas que le interesan (NÓMINA, GASTOS OPERATIVOS, GASTOS FINANCIEROS, etc.). Cualquier fila cuya etiqueta no aparezca en ese mapa —subtotales, separadores visuales, filas en blanco, encabezados de sección— se salta sin procesamiento.

Para las columnas de mes, se ignoran explícitamente las columnas cuya celda en la fila de encabezado sea vacía, `"NAN"` o `"ACUMULADO"`. Así se descarta automáticamente la columna de acumulado anual que suelen incluir los ERs.

La función `clean_currency()` normaliza los valores monetarios antes de parsear: elimina símbolos `$` y comas, convierte notación contable negativa `(1,234)` a `-1234`, y mapea celdas vacías o `NaN` a `0.0`. Esto evita que filas con datos incompletos generen errores.

---

## Forecast de ingresos

### Horizonte y datos de entrenamiento

El modelo proyecta exactamente **un mes hacia adelante**: el mes calendario siguiente al último mes disponible en los datos. No genera proyecciones a 3 o 6 meses porque con pocos puntos la incertidumbre acumulada haría los intervalos no comunicables.

**Todos los meses disponibles** se usan como entrenamiento —ninguno se reserva para validación. Esto es distinto al XGBoost, donde sí se hace un split temporal (meses 1 y 2 de train, mes 3 de test). La diferencia es de escala: el XGBoost entrena sobre miles de transacciones individuales y puede ceder un mes entero para evaluación; la regresión lineal solo tiene 3 puntos (uno por mes), y reservar uno significaría ajustar una recta con 2 puntos, lo que no aporta información útil de validación.

### Método

Regresión lineal ordinaria por mínimos cuadrados (`numpy.polyfit` grado 1). El mes proyectado es el punto inmediatamente siguiente a la última observación:

```
revenue_proyectado = slope × n + intercept
```

donde `n` es el número de meses disponibles (el siguiente índice en la secuencia). El mismo procedimiento se aplica independientemente por sucursal para generar el desglose `por_sucursal`.

### Niveles de confianza

| Meses disponibles | Confianza |
|---|---|
| ≥ 9 | `alta` |
| 4 – 8 | `media` |
| < 4 | `baja` |

Con 3 meses (Nama actual) el nivel es `baja`. El campo `advertencia` en el response lo indica explícitamente. La tendencia se clasifica como `creciente` si la variación esperada supera +5%, `decreciente` si cae más de -5%, y `estable` en el rango intermedio.

---

## Health Score — dimensiones y escala

### Cinco dimensiones ponderadas

| Dimensión | Fuente | Peso por defecto | Dirección |
|---|---|---|---|
| `margen_bruto_vs_benchmark` | BD | 30% | Mayor es mejor |
| `nomina_vs_benchmark` | ER + BD | 25% | Menor es mejor |
| `gastos_financieros_vs_benchmark` | ER + BD | 20% | Menor es mejor |
| `presion_inflacionaria` | APIs macro | 15% | Menor es mejor |
| `tendencia_ingresos` | BD | 10% | Mayor es mejor |

Los pesos se leen del archivo de configuración del cliente (`health_score_weights`). Si el cliente no define pesos, se usan los valores anteriores. Los cinco pesos suman 1.0.

### Escala 0–100 por dimensión

Cada dimensión produce un score parcial discreto en el conjunto {0, 20, 40, 60, 80, 100}. La escala es relativa al benchmark sectorial del cliente.

**Para dimensiones donde mayor es mejor** (margen bruto):

| Resultado vs benchmark | Score |
|---|---|
| ≥ 110% del benchmark | 100 |
| ≥ 100% | 80 |
| ≥ 90% | 60 |
| ≥ 75% | 40 |
| ≥ 60% | 20 |
| < 60% | 0 |

**Para dimensiones donde menor es mejor** (nómina, gastos financieros):

| Resultado vs benchmark | Score |
|---|---|
| ≤ 90% del benchmark | 100 |
| ≤ 100% | 80 |
| ≤ 110% | 60 |
| ≤ 125% | 40 |
| ≤ 150% | 20 |
| > 150% | 0 |

**Presión inflacionaria** (índice entre ~−2 y +2):

| Valor del índice | Score |
|---|---|
| ≤ 0.2 | 100 |
| ≤ 0.5 | 80 |
| ≤ 0.8 | 60 |
| ≤ 1.2 | 40 |
| ≤ 1.6 | 20 |
| > 1.6 | 0 |

Si no hay datos macro disponibles, esta dimensión recibe un score neutral de 50.

**Tendencia de ingresos:**

| Condición | Score |
|---|---|
| Creciente > 5% | 100 |
| Creciente ≤ 5% | 75 |
| Estable (±5%) | 50 |
| Decreciente > −5% | 30 |
| Decreciente ≤ −5% | 10 |

### Score total y categorías

```
score_total = Σ (score_dimensión × peso_dimensión)
```

Como cada score parcial está en [0, 100] y los pesos suman 1, el resultado final está naturalmente en [0, 100] sin normalización adicional.

| Rango | Categoría |
|---|---|
| ≥ 75 | `saludable` |
| 55 – 74 | `en_observacion` |
| 35 – 54 | `en_riesgo` |
| < 35 | `critico` |

---

## RAG — modelo de embeddings y chunking

### Modelo de embeddings

`all-MiniLM-L6-v2` de sentence-transformers. Se ejecuta **localmente** — no requiere API key ni conexión durante la inferencia. El modelo pesa ~80 MB y se descarga y cachea en el primer uso.

ChromaDB almacena los vectores con métrica de **similitud coseno** (`hnsw:space: cosine`). El score que devuelve el sistema es `1 − distancia_coseno`, por lo que valores cercanos a 1.0 indican alta similitud semántica.

Las búsquedas retornan los **5 fragmentos más relevantes** por defecto, filtrados por `cliente_id` para garantizar aislamiento entre clientes.

### Estrategia de chunking

Los documentos se fragmentan en cuatro pasos secuenciales:

1. **División gruesa.** Si el documento tiene encabezados Markdown `##` o `###`, se divide en secciones por encabezado. Si no los tiene (texto plano, minutas), se divide por párrafos (`\n\n`).

2. **División fina.** Cualquier segmento que supere los **500 caracteres** se corta en el último límite de oración (`.`, `!`, `?`, salto de línea) encontrado en los 100 caracteres previos al límite. Si no hay límite de oración en esa ventana, el corte es exactamente en el carácter 500.

3. **Fusión de segmentos pequeños.** Segmentos consecutivos que caben juntos dentro de los 500 caracteres se fusionan greedily para evitar chunks demasiado cortos que no aportan contexto suficiente.

4. **Overlap.** Se anteponen los últimos **50 caracteres** del chunk anterior al inicio de cada chunk. Esto preserva contexto en los bordes de corte, evitando que una oración que cruza el límite quede sin contexto en ninguno de los dos fragmentos.

Los parámetros `chunk_size=500` y `chunk_overlap=50` son configurables al llamar `chunk_document()`.

---

## Monte Carlo — simulaciones y distribuciones

### Número de simulaciones

**10,000 iteraciones** por escenario (configurable vía `ScenarioConfig.n_simulaciones`). La semilla del generador aleatorio es configurable (`semilla`) para reproducibilidad; si se omite, cada corrida produce resultados ligeramente distintos.

### Variables simuladas y distribuciones

Cada variable se modela como una perturbación **normal** alrededor del cambio esperado definido por el usuario:

```
factor_variable = 1 + mu_usuario + N(0, sigma_default)
valor_simulado  = valor_base × factor_variable
```

| Variable | Sigma por defecto | Interpretación |
|---|---|---|
| `revenue` | 5% | Incertidumbre en ventas |
| `costo_directo` | 4% | Variación en costo de insumos |
| `nomina` | 3% | Fluctuación salarial |
| `gastos_financieros` | 2% | Variación en carga financiera |

Los `sigma` por defecto pueden sobreescribirse por variable en `ScenarioConfig.sigmas`. Los "otros gastos operativos" (todo el `total_gastos_operacion` menos nómina) se tratan como **fijos** — no se les aplica incertidumbre porque representan compromisos contractuales (renta, seguros) con variación baja.

### Variables de salida

Para cada simulación se calculan siete métricas de resultado. Al final de las 10,000 iteraciones se reporta la distribución completa de cada una:

- `revenue`, `margen_bruto`, `ebitda`, `margen_ebitda`, `margen_neto`, `nomina_pct`, `gastos_financieros_pct`

Cada distribución incluye percentiles p10, p25, p50, p75, p90, media y desviación estándar. Para la visualización de histogramas se devuelve una muestra aleatoria de 500 valores.

### Probabilidades vs benchmark

Adicionalmente se reporta la **probabilidad empírica** de que cada métrica supere (o quede bajo) su benchmark sectorial:

- `margen_bruto_sobre_benchmark`
- `nomina_bajo_benchmark`
- `gastos_fin_bajo_benchmark`
- `margen_neto_sobre_benchmark`
- `ebitda_positivo`

Estas probabilidades se calculan como la fracción de las 10,000 simulaciones en que se cumple la condición — no son distribuciones paramétricas, son frecuencias observadas directamente.
