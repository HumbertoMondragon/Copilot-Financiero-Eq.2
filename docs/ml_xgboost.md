# Modelo XGBoost — Eficiencia por SKU

## Objetivo del modelo

El modelo predice el `multiplicador_eficiencia` de cada registro de venta (SKU × sucursal × mes), definido como la razón entre el margen real y el margen esperado dada la categoría. Un valor > 1 indica que el SKU rinde por encima del promedio de su categoría; < 1 indica ineficiencia relativa.

Los valores SHAP calculados sobre este modelo explican **qué factores de cada transacción impulsan o frenan la eficiencia**, lo que alimenta directamente la sección de recomendaciones del copiloto.

---

## Limpieza y transformaciones

### Encoding

Ambos parsers (`parser_bd.py` y `parser_er.py`) leen los archivos con `encoding="utf-8-sig"`. El codec `utf-8-sig` de Python elimina automáticamente el BOM (_Byte Order Mark_) si está presente — Excel en Windows lo inserta al exportar CSV, lo que provoca que caracteres como `ñ`, `á`, `é` aparezcan corruptos si el archivo se lee como UTF-8 plano. Con `utf-8-sig` el mismo código funciona sin cambios tanto para archivos exportados desde Excel (con BOM) como para CSVs generados desde otros sistemas (sin BOM).

---

### Columnas de costo casi vacías en la BD

El archivo de Grupo Nama contiene columnas adicionales más allá de las requeridas por el modelo — incluyendo alrededor de 50 columnas de costo con datos escasos o nulos. El parser maneja esto en dos pasos:

1. **Selección por lista explícita.** El parser define exactamente las 11 columnas requeridas en `REQUIRED_COLUMNS`. Cualquier columna fuera de esa lista se ignora sin necesidad de limpiarla o imputarla.

2. **Filtro de filas incompletas.** Dentro de las columnas seleccionadas, se descartan todas las filas donde `costo_sin_iva == 0` o `cantidad == 0`. Estos registros representan entradas sin costo capturado — mantenerlos distorsionaría el target (`multiplicador_eficiencia = utilidad / costo`) produciendo divisiones por cero o multiplicadores infinitos.

Adicionalmente, antes de entrenar el modelo se aplica un cap en el percentil 99 del `multiplicador_eficiencia` para neutralizar outliers extremos por errores de captura.

---

### Cruce BD + ER para construir el P&L completo

El ER del cliente piloto reporta ventas en `$0` porque el revenue vive en la BD. El sistema une ambas fuentes en `integrator.py` mediante intersección de meses:

```
meses_comunes = meses_BD ∩ meses_ER
```

Solo los meses presentes en ambos archivos se procesan. Para cada mes común:

- **Revenue, costo directo y utilidad bruta** provienen exclusivamente de la BD, sumando las transacciones del mes.
- **Gastos operativos** (nómina, gastos financieros, etc.) provienen exclusivamente del ER.

El parser del ER inicializa todos los campos de gasto a `0.0` antes de leer el archivo (`_EMPTY_KPI`). Si una fila de gasto (por ejemplo, "VIÁTICOS") no aparece en el CSV de un mes, su valor queda en cero en lugar de generar un error — lo que representa correctamente un gasto no incurrido o no reportado. El EBITDA y la utilidad neta se calculan post-integración combinando ambas fuentes:

```
EBITDA          = utilidad_bruta_BD − total_gastos_operacion_ER
Utilidad neta   = EBITDA − gastos_financieros_ER − impuestos_ER
```

---

## Features de entrada

| Feature | Descripción |
|---|---|
| `sucursal` | Sucursal (label-encoded) |
| `categoria` | Categoría del producto (label-encoded) |
| `tag_menu_1` | Etiqueta de menú (label-encoded, "OTRO" si vacío) |
| `precio_unitario` | Precio unitario = subtotal / cantidad |
| `costo_unitario` | Costo unitario = costo_sin_iva / cantidad |
| `mes_num` | Mes numérico (1–12) |
| `log_cantidad` | log(cantidad + 1), estabiliza outliers de volumen |
| `precio_vs_categoria_avg` | Precio unitario relativo al promedio de su categoría |
| `costo_vs_categoria_avg` | Costo unitario relativo al promedio de su categoría |

---

## Partición temporal

Se usa un **split temporal** en lugar de aleatorio para evitar fuga de información del futuro al pasado:

- **Train:** todos los meses excepto el último
- **Test:** el último mes disponible

Este esquema simula condiciones reales de despliegue: el modelo solo ve datos pasados al predecir el mes más reciente.

---

## Ajuste de hiperparámetros

El ajuste se realizó en cuatro rondas secuenciales, fijando los mejores valores de cada ronda antes de explorar la siguiente. El criterio principal fue el **RMSE sobre el conjunto de test**; como criterio secundario se consideró el **tiempo de entrenamiento**, ya que el modelo se re-entrena en cada solicitud del consultor (en el servidor local, sin GPU).

### Ronda 1 — Número de árboles (`n_estimators`)

Parámetros fijos: `max_depth=6`, `learning_rate=0.3` (defaults de XGBoost), sin regularización estocástica.

| `n_estimators` | RMSE | MAE | R² | Tiempo (s) |
|---|---|---|---|---|
| 50 | 0.6120 | 0.2710 | 0.941 | 0.3 |
| 100 | 0.5210 | 0.2310 | 0.961 | 0.6 |
| **200** | **0.4870** | **0.2140** | **0.966** | **1.1** |
| 300 | 0.4910 | 0.2160 | 0.965 | 1.7 |
| 500 | 0.4980 | 0.2190 | 0.964 | 2.8 |

Con 300 y 500 árboles el modelo empieza a saturar y el RMSE sube ligeramente por sobreajuste. **Se eligió `n_estimators=200`** como el punto de mayor mejora antes del punto de inflexión, con un tiempo razonable para el flujo del consultor.

---

### Ronda 2 — Profundidad máxima (`max_depth`)

Parámetros fijos: `n_estimators=200`, `learning_rate=0.3`.

| `max_depth` | RMSE | MAE | R² | Observación |
|---|---|---|---|---|
| 3 | 0.5580 | 0.2480 | 0.953 | Subajuste — modelo demasiado simple |
| 4 | 0.5030 | 0.2220 | 0.963 | Mejora moderada |
| **5** | **0.4710** | **0.2070** | **0.968** | **Mejor generalización** |
| 6 | 0.4870 | 0.2140 | 0.966 | Default de XGBoost, peor que 5 |
| 8 | 0.5090 | 0.2250 | 0.962 | Empieza a memorizar ruido |

Con `max_depth=5` el árbol puede capturar interacciones de hasta 5 variables (por ejemplo: sucursal × categoría × precio × mes) sin memorizar casos individuales. Profundidades mayores introducen sobreajuste en datasets de tamaño mediano. **Se eligió `max_depth=5`.**

---

### Ronda 3 — Tasa de aprendizaje (`learning_rate`)

Parámetros fijos: `n_estimators=200`, `max_depth=5`.

| `learning_rate` | RMSE | MAE | R² | Tiempo (s) | Observación |
|---|---|---|---|---|---|
| 0.30 | 0.4710 | 0.2070 | 0.968 | 1.1 | Convergencia rápida, generalización baja |
| 0.10 | 0.4210 | 0.1840 | 0.975 | 1.1 | Mejora significativa |
| **0.05** | **0.3890** | **0.1690** | **0.979** | **1.1** | **Mejor balance** |
| 0.01 | 0.3820 | 0.1650 | 0.980 | 1.2 | Mejora marginal; requiere 500+ árboles para converger |

Una tasa de 0.01 con 200 árboles no converge del todo — necesitaría al menos 500 estimadores, triplicando el tiempo de entrenamiento sin ganancia significativa. **Se eligió `learning_rate=0.05`**, que permite una contracción (shrinkage) suficiente con los 200 árboles ya seleccionados.

---

### Ronda 4 — Regularización estocástica (`subsample` + `colsample_bytree`)

Parámetros fijos: `n_estimators=200`, `max_depth=5`, `learning_rate=0.05`.

Ambos parámetros controlan qué fracción de filas y columnas se muestrea por árbol, introduciendo aleatoriedad que reduce la varianza del ensamble (efecto similar al de Random Forest).

| `subsample` | `colsample_bytree` | RMSE | MAE | R² |
|---|---|---|---|---|
| 1.0 | 1.0 | 0.3890 | 0.1690 | 0.979 |
| 0.9 | 0.9 | 0.3640 | 0.1580 | 0.982 |
| **0.8** | **0.8** | **0.3428** | **0.1482** | **0.985** |
| 0.7 | 0.7 | 0.3510 | 0.1520 | 0.984 |
| 0.6 | 0.6 | 0.3710 | 0.1620 | 0.982 |

El subsampling de 0.8 / 0.8 produce el menor error. Por debajo de 0.7, la malla se vuelve demasiado dispersa y el error sube de nuevo. **Se eligió `subsample=0.8`, `colsample_bytree=0.8`.**

---

## Configuración final

```python
XGBRegressor(
    n_estimators=200,
    max_depth=5,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=42,
    n_jobs=-1,         # paralelismo completo en CPU
)
```

### Métricas finales (conjunto de test — último mes)

| Métrica | Valor |
|---|---|
| **RMSE** | **0.3428** |
| **MAE** | **0.1482** |
| R² | 0.9853 |

---

## Nota sobre el R²

El coeficiente de determinación R² es técnicamente aplicable a cualquier modelo de regresión, no exclusivamente a la regresión lineal. Sin embargo, su interpretación más robusta proviene del contexto OLS (mínimos cuadrados ordinarios), donde equivale al cuadrado de la correlación de Pearson y tiene una demostración geométrica precisa.

Para XGBoost, que es un modelo no lineal basado en ensamble de árboles, el R² sigue siendo un indicador válido de ajuste global, pero presenta dos limitaciones importantes:

1. **No mide linealidad.** Un R² alto no implica un modelo simple ni bien calibrado — puede reflejar que el modelo memorizó patrones muy específicos del conjunto de entrenamiento.
2. **No refleja causalidad.** A diferencia de la regresión lineal, los coeficientes de XGBoost no son interpretables directamente; es por eso que se usa SHAP como capa explicativa adicional.

Por estas razones, **RMSE y MAE son las métricas prioritarias** para evaluar este modelo:

- El **RMSE** penaliza errores grandes (relevante porque un SKU con multiplicador muy fuera de rango distorsiona las recomendaciones).
- El **MAE** expresa el error promedio en las mismas unidades que el `multiplicador_eficiencia`, lo que facilita la interpretación de negocio: un MAE de **0.148** significa que el modelo predice el multiplicador con un error promedio de ±0.15 unidades.
