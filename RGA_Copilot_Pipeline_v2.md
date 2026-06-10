# RGA Financial Copilot — Documentación del Pipeline

**Versión:** Prototipo v1.1  
**Cliente piloto:** Grupo Nama (restaurante premium, 5 sucursales)  
**Fecha:** Mayo 2026

---

## 1. Propósito y visión del modelo

El RGA Financial Copilot es un sistema de inteligencia financiera diseñado para consultoras de crecimiento empresarial que trabajan con PyMEs. Su propósito central es integrar información cuantitativa (datos financieros tabulares) con información cualitativa (minutas de reuniones, notas del consultor) para producir reportes ejecutivos automatizados, alertas tempranas y recomendaciones accionables.

El sistema no reemplaza al consultor — lo potencia. Donde antes el consultor dedicaba horas a consolidar datos antes de cada reunión, el copilot entrega un reporte estructurado, fundamentado y narrado que el consultor puede presentar directamente o usar como punto de partida para la conversación estratégica con el cliente.

### Problema que resuelve

La mayoría de las PyMEs en México tienen acceso a sus datos financieros históricos en alguna forma (Excel, sistemas de punto de venta, estados de cuenta), pero carecen de la capacidad analítica para convertir esos datos en decisiones. El problema no es falta de datos — es falta de interpretación integrada.

El copilot resuelve específicamente:

- La brecha entre lo que dicen los números y lo que significa para el negocio
- La desconexión entre señales cualitativas (lo que preocupa al dueño) y señales cuantitativas (lo que muestran los KPIs)
- La incapacidad de identificar empíricamente dónde está el dinero mal invertido dentro del negocio
- La ausencia de visión prospectiva: el dueño siempre sabe lo que pasó, raramente sabe lo que viene

### Alcance del prototipo

El prototipo trabaja con los datos disponibles del restaurante Grupo Nama: base de datos transaccional (BD 2026) con ventas por producto y sucursal para enero, febrero y marzo 2026; y estado de resultados nivel 2 (ER nivel 2 2026) con estructura de gastos operativos para el mismo período. Las minutas de reuniones están pendientes de recibir y se incorporarán al sistema en cuanto estén disponibles.

El prototipo valida el pipeline con datos de Nama, pero la arquitectura está diseñada para ser agnóstica a la industria desde su concepción — los KPIs, benchmarks y el modelo de eficiencia se parametrizan por cliente, no por sector específico.

### Arquitectura de entrega — enfoque API-first

El sistema se entrega como una API REST construida en FastAPI. RGA integra los endpoints directamente en su plataforma existente. No existe una interfaz propia de producción — el frontend vive en la plataforma de RGA. El prototipo incluye una interfaz Streamlit ligera con el único propósito de validar y demostrar los outputs del pipeline durante el desarrollo; esta interfaz no forma parte de la entrega final.

La estructura del repositorio refleja este enfoque:

```
proyecto/
├── data/               # Datos crudos y procesados por cliente
├── models/             # Modelos entrenados serializados (.pkl, .json)
├── notebooks/          # Exploración y validación del pipeline
└── src/
    ├── api/
    │   └── app.py      # Endpoints FastAPI + inference.py (lógica de predicción)
    └── streamlit/      # Interfaz de validación (solo desarrollo)
```

ChromaDB corre como servicio independiente accesible desde la API, con colecciones separadas por cliente.

---

## 2. Arquitectura del pipeline — cinco capas

### Capa 1 — Ingesta de datos

El sistema recibe datos de tres fuentes que operan en paralelo y tienen roles complementarios. Ninguna fuente es suficiente por sí sola; el valor emerge de su integración.

**Base de datos transaccional (BD)**  
Es la fuente principal del modelo predictivo. Cada fila representa una unidad vendida en una fecha, sucursal y categoría específica, con precio de venta, cantidad, costo directo, utilidad bruta y margen bruto. Para el cliente piloto (Nama), el archivo cubre enero, febrero y marzo 2026 con registros de las cinco sucursales (ANT, SOK, JUR, MOR, CAM) y múltiples categorías de producto. Esta granularidad es lo que hace posible el modelo de eficiencia por SKU o unidad de producto.

El esquema de ingesta está diseñado para recibir estructuras tabulares equivalentes de cualquier industria: retail, servicios, manufactura ligera. Lo que varía entre clientes es el nombre de las columnas y las categorías — no la lógica del pipeline.

**Estado de resultados (ER)**  
Aporta la estructura de costos operativos que la BD transaccional no contiene: nómina, gastos operativos, gastos administrativos y gastos financieros. Para el cliente piloto, los gastos financieros (~$685,000 mensuales constantes en los tres meses disponibles) representan una carga de deuda estructural significativa que debe aparecer como factor de riesgo en el análisis de salud del negocio. El ER muestra ventas en $0 porque el revenue vive en la BD — el sistema une ambas fuentes internamente en la Capa 2 para construir el P&L completo.

**APIs externas — contexto macroeconómico general**  
Proveen el contexto económico que afecta los costos y la demanda del negocio sin que el dueño lo controle directamente. El sistema consume fuentes de propósito general aplicables a cualquier industria; el contexto específico del giro lo genera el LLM en la Capa 4 a partir de los documentos cualitativos:

- **Banxico:** tipo de cambio MXN/USD y tasas de interés de referencia. El tipo de cambio impacta los costos de cualquier empresa con insumos o deuda en dólares; la tasa de referencia contextualiza el costo financiero del negocio.
- **INEGI — INPC general y por componente:** inflación general y por grandes rubros (energía, servicios, mercancías). Permite construir un índice de presión inflacionaria sobre la estructura de costos del cliente sin depender de precios de commodities específicos por sector.
- **INEGI — IGAE (Indicador Global de la Actividad Económica):** proxy mensual del PIB que contextualiza si el negocio crece o se contrae en relación con la economía en general.
- **Banxico — Encuesta sobre las Expectativas de los Especialistas en Economía:** expectativas de inflación y crecimiento a 12 meses, útiles para el componente prospectivo del reporte.

Estas cuatro fuentes generan señales de contexto válidas para cualquier PyME mexicana, independientemente de su giro. La lógica de cómo cada señal afecta al negocio específico se parametriza en el archivo de configuración del cliente.

**Minutas y notas de reuniones**  
El texto libre de reuniones con el cliente se ingresa al sistema como documentos de texto plano. El sistema los procesa para extraer señales numéricas (frecuencia de menciones de riesgo, tono del dueño, temas recurrentes) y los indexa en una base de datos vectorial (ChromaDB) para el componente RAG descrito en la sección de innovación tecnológica. Esta fuente está pendiente de recibir para el cliente piloto y es el elemento diferenciador más importante del sistema.

---

### Capa 2 — Procesamiento

La Capa 2 transforma los datos crudos de las tres fuentes en tres tipos de señales que el modelo puede usar: features del modelo de eficiencia, KPIs de salud operativa, e índices externos contextuales.

**Features del modelo de eficiencia (de la BD)**

Para cada transacción de la BD se calculan las variables que entran al modelo XGBoost. El proceso incluye:

- **Target por transacción:** utilidad bruta dividida entre costo directo total. Este ratio mide cuántos pesos de ganancia genera cada peso invertido en el insumo principal. Es el objetivo que el modelo aprende a predecir y explicar. Es universal: aplica a un platillo de restaurante, una SKU de retail o una unidad de servicio.
- **Features categóricas:** unidad de negocio o sucursal, categoría de producto o servicio, tipo de ítem, tipo de día de la semana.
- **Features numéricas derivadas:** precio de venta unitario, costo unitario, mes como número entero para capturar estacionalidad.
- **Limpieza y validación:** se eliminan filas con costos en cero o cantidades nulas, se detectan outliers extremos (errores de captura) y se normalizan las features numéricas para que el modelo no sobrepese las variables de mayor escala.

**KPIs de salud operativa (BD + ER unidos)**

Una vez que el sistema une los ingresos de la BD con los gastos del ER, calcula los ratios de salud del negocio mes a mes. Todos los KPIs están definidos en términos generales — ratios financieros universales que aplican a cualquier empresa con estructura de costos separable en directos e indirectos:

- Costo directo como porcentaje de ingresos (equivalente al COGS/Revenue)
- Nómina como porcentaje de ingresos
- Gastos operativos como porcentaje de ingresos
- Gastos financieros como porcentaje de ingresos (señal de carga de deuda)
- Margen bruto por categoría y por unidad de negocio
- EBITDA aproximado (ingresos menos costos directos, nómina y gastos operativos)
- Variación mensual (MoM) de cada ratio para detectar tendencias

Los benchmarks contra los que se comparan estos KPIs se almacenan en el archivo de configuración del cliente y pueden actualizarse sin tocar el código. Para el cliente piloto se usan referencias del sector restaurantero; para un cliente nuevo en otra industria, se carga su archivo de configuración correspondiente.

**Señales macroeconómicas (de APIs)**

De las cuatro fuentes externas se calculan tres índices de propósito general:

- **Índice de presión inflacionaria:** variación del INPC en los últimos tres meses ponderada por la sensibilidad del negocio a cada componente (energía, servicios, mercancías), definida en el archivo de configuración del cliente.
- **Índice de entorno económico:** combinación del IGAE y las expectativas de los especialistas, que contextualiza si el momento macroeconómico es favorable o adverso para el crecimiento de ingresos.
- **Índice de presión financiera:** nivel actual de la tasa de referencia de Banxico en relación con la media histórica reciente y el tipo de cambio, que contextualiza el costo del financiamiento del negocio.

**Señales cualitativas (de minutas vía NLP)**

Cuando las minutas están disponibles, el procesamiento de texto extrae señales numéricas que se unen a los datos cuantitativos: conteo de menciones de términos de riesgo en las últimas tres reuniones, score de sentimiento del propietario (-1 a +1), días transcurridos desde la última mención de temas críticos como "proveedores", "renta" o "deuda". Los textos completos se convierten en vectores de embeddings semánticos y se almacenan en ChromaDB para recuperación posterior.

---

### Capa 3 — Modelado

El modelado del sistema se divide en tres componentes con roles distintos. Es importante distinguirlos: solo uno de ellos es un modelo de machine learning entrenado; los otros dos son cálculos deterministas y proyecciones estadísticas simples.

**Modelo de eficiencia — XGBoost**

El modelo XGBoost se entrena con las transacciones de la BD como unidad de observación. Cada fila del dataset de entrenamiento representa una unidad vendida y tiene sus features calculadas en la Capa 2 más su target (el multiplicador de eficiencia UB/Costo directo). Con miles de transacciones distribuidas en múltiples meses y unidades de negocio, el dataset tiene la masa suficiente para entrenar un modelo de gradient boosting bien regularizado.

Lo que el modelo aprende: qué combinaciones de unidad de negocio, categoría, tipo de ítem, precio y costo predicen multiplicadores de eficiencia altos o bajos. El modelo no recibe explícitamente cuáles categorías deberían ser más rentables — lo descubre de los patrones en los datos.

SHAP (SHapley Additive exPlanations) se aplica post-entrenamiento para descomponer cada predicción en contribuciones individuales por variable. Para cualquier ítem o agrupación, el sistema puede cuantificar exactamente qué variables y en qué magnitud están arrastrando o elevando el multiplicador de eficiencia. Esa granularidad es lo que convierte al modelo en una herramienta de consultoría, no solo un número.

**Health score — cálculo determinista**

El health score es un número entre 0 y 100 que representa el estado general del negocio en el mes analizado. No se entrena — se calcula como una suma ponderada de KPIs normalizados contra benchmarks del archivo de configuración del cliente:

| Componente | Fuente | Peso |
|---|---|---|
| Margen bruto vs benchmark sectorial | BD | 30% |
| Nómina / Ingresos vs benchmark | ER + BD | 25% |
| Gastos financieros / Ingresos | ER + BD | 20% |
| Índice de presión inflacionaria | APIs | 15% |
| Tendencia de ingresos (3+ meses) | BD | 10% |

Los pesos son configurables por cliente e industria. Un negocio con margen bruto en benchmark, nómina controlada, sin presión de deuda, entorno inflacionario estable y tendencia positiva de ingresos alcanza scores cercanos a 100. El cliente piloto, con gastos financieros de $685K/mes y costo directo por encima del benchmark sectorial en los meses analizados, parte desde un score que refleja esas presiones.

**Forecast de ingresos — regresión lineal**

Con los meses de datos de ingresos disponibles se ajusta una regresión lineal para proyectar el mes siguiente. El resultado es un número puntual con dirección de tendencia explícita. Se reporta con una advertencia de confianza proporcional a los datos disponibles: con tres puntos se muestra dirección, no precisión. No se utiliza Monte Carlo para el forecast porque con pocas observaciones la varianza estimada es estadísticamente poco confiable y los intervalos resultantes serían tan amplios que perderían utilidad comunicativa. A medida que se acumulen más meses de datos, el forecast podrá incorporar componentes de estacionalidad y mayor robustez estadística.

---

### Capa 4 — Integración

La Capa 4 es el puente entre los outputs del modelado y el reporte final. Su función es traducir resultados técnicos en evidencia comunicable y ensamblar el contexto que recibe el LLM.

**Traducción de SHAP values a lenguaje financiero**

Los SHAP values son contribuciones numéricas de cada variable a la predicción del modelo. Para que sean útiles en un reporte ejecutivo, se traducen automáticamente a plantillas de lenguaje financiero parametrizables. Un SHAP value negativo en "costo_unitario_vs_promedio_categoria" se convierte en una oración que cuantifica cuántos puntos del multiplicador de eficiencia se pierden por ese costo elevado y en qué magnitud supera al promedio de ítems similares en esa unidad de negocio. Las plantillas son configurables por industria.

**RAG sobre ChromaDB**

Cuando el sistema va a generar el reporte del mes, primero convierte el contexto del análisis actual (health score, alertas activas, KPIs más relevantes) en un vector de búsqueda y lo compara contra el índice de minutas almacenado en ChromaDB. Los fragmentos de texto con mayor similitud semántica se recuperan y se incorporan al prompt del LLM como evidencia contextual.

El resultado es que el LLM no genera texto genérico sobre el negocio — genera texto fundamentado en lo que el consultor y el dueño discutieron en reuniones específicas y documentadas. La trazabilidad es completa: cada afirmación del reporte que proviene de una minuta puede rastrearse hasta el documento específico que la fundamenta.

**Ensamblado del contexto para el LLM**

El prompt que recibe el LLM incluye todos los elementos en un formato estructurado:

- Health score del mes con sus componentes y pesos
- Los tres SHAP values más relevantes ya traducidos a lenguaje financiero
- KPIs del mes comparados contra benchmark sectorial
- Proyección de ingresos para el mes siguiente
- Índices macroeconómicos y su interpretación para el negocio
- Fragmentos de minutas recuperados por RAG, con fecha y contexto
- Instrucciones de formato y tono para el reporte

El LLM produce cuatro outputs estructurados en un único JSON: las recomendaciones accionables, la narrativa ejecutiva, las limitaciones del análisis, y el **contexto macroeconómico sectorial** — un análisis del entorno específico del giro del negocio (reformas regulatorias, presiones de costos sectoriales, riesgos y oportunidades) que el LLM infiere directamente de los documentos cualitativos y las categorías de SKUs, sin necesidad de APIs especializadas por industria. Este diseño hace que el sistema sea agnóstico al sector: el mismo pipeline funciona para restaurantes, clínicas, manufacturas o retail sin modificar código.

---

### Capa 5 — Output (entregado vía API)

El sistema produce tres salidas complementarias, todas accesibles como respuestas JSON desde los endpoints de FastAPI. RGA consume estos endpoints desde su plataforma y decide cómo presentar los datos al consultor y al cliente final.

**Reporte ejecutivo mensual**

Es el conjunto de datos principal que alimenta la vista de reporte en la plataforma de RGA. Los campos del response incluyen:

1. **health_score:** número entre 0 y 100 con sus componentes, pesos y tendencia respecto al mes anterior.
2. **shap_factors:** los tres factores que más influyeron en el score del mes, con magnitud con signo y descripción en lenguaje financiero.
3. **kpis:** lista de métricas clave comparadas contra benchmark, con estado por métrica (en_rango / alerta / critico).
4. **efficiency_ranking:** ranking de categorías de producto y unidades de negocio por multiplicador de eficiencia, con outliers señalados.
5. **narrative:** texto generado por el LLM que integra hallazgos cuantitativos con contexto de minutas.
6. **recommendations:** lista de tres a cinco acciones concretas con evidencia trazable, acción sugerida e impacto estimado.
7. **forecast:** ingreso proyectado para el mes siguiente con indicación de tendencia y nivel de confianza.
8. **contexto_sectorial:** análisis del entorno macroeconómico específico del giro del negocio — generado por el LLM a partir de los documentos cualitativos. Incluye: giro detectado, resumen del entorno sectorial en México, y lista de factores clasificados como regulatorios, riesgos, oportunidades o tendencias. Este campo hace que el reporte sea relevante al sector del cliente sin requerir fuentes de datos especializadas.

**Alertas automáticas**

El sistema evalúa reglas sobre los KPIs calculados y devuelve alertas clasificadas en tres niveles: `info` para cambios que merecen seguimiento, `warning` para deterioros que requieren revisión en la próxima reunión, y `critical` para situaciones que requieren atención inmediata. Cada alerta incluye un campo de texto explicativo listo para comunicar sin traducción técnica.

**Simulador de escenarios what-if**

Endpoint independiente que acepta modificaciones hipotéticas a las variables del modelo — por ejemplo, eliminar los ítems con menor multiplicador de eficiencia o reducir el costo directo de una categoría en N puntos porcentuales. Para cada escenario, el sistema corre 10,000 simulaciones de Monte Carlo y devuelve una distribución de resultados: health score estimado con rango de variación, cambio esperado en utilidad bruta con percentiles 10 y 90, y probabilidad de que el cambio sea positivo. Monte Carlo se justifica aquí —a diferencia del forecast— porque el escenario what-if involucra múltiples fuentes de incertidumbre que interactúan de manera no lineal: cambiar el mix de ventas altera la distribución de costos, que altera la presión sobre la nómina, cada una con su propio rango de variación. Un número puntual sería engañosamente preciso; una distribución es honesta con la incertidumbre real.

---

## 3. Innovación financiera

### Índice de presión inflacionaria sobre costos

La mayoría de los sistemas de análisis financiero tratan los costos como datos históricos que se reportan cuando ya ocurrieron. El copilot introduce un índice prospectivo de propósito general que anticipa compresión de margen antes de que aparezca en el estado de resultados, usando exclusivamente datos del INPC de INEGI.

El índice se construye en tres pasos. Primero, se mapea la estructura de costos del negocio contra los grandes componentes del INPC: energía, servicios, mercancías no alimentarias y alimentos (cuando aplica). Segundo, se obtienen las variaciones recientes de cada componente y se expresan como desviación porcentual respecto al promedio de los últimos seis meses. Tercero, se pondera cada desviación por el peso estimado de ese componente en la estructura de costos del negocio, definido en el archivo de configuración del cliente.

El resultado es un índice entre aproximadamente -2 y +2. Un valor positivo elevado señala que los costos de operación enfrentan una presión inusual que, con el desfase típico entre el cambio de precios externos y su impacto en el costo de lo vendido, se traducirá en compresión de margen en las semanas siguientes. Esto le da al consultor una ventana de anticipación que los estados de resultados no ofrecen, sin depender de fuentes de datos específicas por sector.

### KPIs de eficiencia universales

Más allá de los ratios financieros estándar, el sistema introduce métricas de alto poder explicativo definidas en términos universales:

**Multiplicador de eficiencia por SKU o unidad de producto/servicio:** utilidad bruta dividida entre costo directo, calculado por cada ítem del catálogo. Permite identificar qué productos o servicios son generadores netos de valor y cuáles destruyen rentabilidad relativa — información que los estados de resultados agregados ocultan completamente. Aplica a un platillo de restaurante, una referencia de retail o una línea de servicio.

**Eficiencia relativa por unidad de negocio:** el mismo ítem vendido en distintas sucursales o canales puede tener multiplicadores de eficiencia diferentes. El sistema detecta estas diferencias automáticamente e identifica si el problema es de precio, de costo o de mix.

**Contribución marginal del mix de ventas:** cuánto mejora o empeora el margen promedio por cada punto porcentual de participación que gana una categoría sobre otra. Permite cuantificar el impacto de estrategias de mezcla antes de implementarlas.

### Benchmarking sectorial configurable

Los KPIs del negocio se contextualizan automáticamente contra benchmarks del sector correspondiente al cliente, almacenados en su archivo de configuración. Un costo directo del 38% sobre ingresos no significa lo mismo en abstracto que comparado contra un benchmark sectorial — la diferencia expresada en pesos sobre el volumen de ingresos del negocio cuantifica la oportunidad de mejora en términos accionables, no en porcentajes abstractos. Esa traducción es parte del reporte automático. Agregar un cliente de una nueva industria requiere únicamente definir sus benchmarks en el archivo de configuración correspondiente.

---

## 4. Innovación tecnológica

### XGBoost con SHAP values — predicción interpretable

XGBoost (Extreme Gradient Boosting) es un algoritmo de machine learning basado en árboles de decisión secuenciales con desempeño consistente en datos tabulares. Su elección responde a tres razones específicas para este contexto: maneja nativamente datos heterogéneos (variables categóricas y numéricas en el mismo modelo sin transformaciones complejas), es robusto frente a datos faltantes, y es inherentemente interpretable mediante SHAP.

SHAP fundamenta su interpretabilidad en la teoría de valores de Shapley de la teoría de juegos cooperativos. Para cada predicción, SHAP calcula la contribución marginal de cada variable probando todas las combinaciones posibles de variables presentes y ausentes. El resultado es un valor por variable que indica exactamente cuántos puntos subió o bajó el multiplicador de eficiencia por cada factor, de manera que la suma de todos los SHAP values más el valor base reproduce exactamente la predicción. Las explicaciones no son aproximaciones — son descomposiciones matemáticamente exactas.

### Monte Carlo para escenarios what-if

Las simulaciones de Monte Carlo resuelven un problema fundamental de los análisis de escenarios deterministas: la falsa precisión. Modificar una variable del negocio afecta simultáneamente otras variables que interactúan de manera no lineal, cada una con su propio rango de incertidumbre. Monte Carlo aborda esto corriendo 10,000 simulaciones donde cada variable se muestrea de su distribución de probabilidad — normal centrada en el valor histórico con desviación estándar observada, o triangular cuando los datos son escasos. El resultado es una distribución de resultados posibles que comunica tanto el valor esperado como la incertidumbre real, significativamente más útil para la toma de decisiones que un número puntual.

### RAG — integración de información cualitativa

RAG (Retrieval-Augmented Generation) es la arquitectura que resuelve cómo integrar texto no estructurado (minutas, notas) con análisis cuantitativo sin perder trazabilidad ni introducir alucinaciones del modelo de lenguaje.

En la fase de indexación, cada documento se divide en fragmentos de aproximadamente 300 palabras y se convierte en un vector de embeddings semánticos. Estos vectores se almacenan en ChromaDB en colecciones separadas por cliente — las minutas de un cliente nunca contaminan el contexto de otro. En la fase de generación, el sistema construye un vector de consulta a partir del contexto analítico del mes y recupera los fragmentos con mayor similitud semántica. Esos fragmentos se insertan en el prompt del LLM con sus metadatos (fecha, reunión de origen), permitiendo que la narrativa del reporte se fundamente en evidencia documental real y trazable.

---

## 5. Consideraciones de escalabilidad

El sistema está diseñado para operar con un cliente y escalar a múltiples clientes sin cambios arquitecturales.

**Configuración por cliente e industria:** los benchmarks, KPIs relevantes, pesos del health score y la parametrización de los índices macroeconómicos se almacenan en archivos de configuración separados por cliente. Incorporar un cliente de una nueva industria requiere crear su archivo de configuración, no modificar código.

**Base vectorial por cliente:** ChromaDB mantiene colecciones separadas por cliente identificadas con un UUID. No hay riesgo de contaminación cruzada entre contextos cualitativos de distintos clientes.

**Modelo global como prior:** cuando la masa de datos de clientes del mismo sector sea suficiente (estimado en ocho a doce clientes por industria con al menos seis meses de historial cada uno), el modelo XGBoost entrenado con todos ellos puede servir como punto de partida para nuevos clientes que aún no tienen historial propio — resolviendo el problema de cold start de manera estadísticamente sólida.

**Pipeline modular:** cada capa opera de manera independiente y puede actualizarse sin afectar las demás. Nuevos componentes analíticos (predicción de liquidez, análisis de rotación de inventario) se agregan como módulos adicionales en la Capa 3 sin modificar el resto del pipeline.

**Integración API-first:** al entregar exclusivamente via FastAPI, el sistema no impone restricciones sobre el frontend ni la plataforma de presentación. RGA puede evolucionar su interfaz de usuario de forma completamente independiente al backend analítico.

---

*Documento generado para uso interno de RGA — Prototipo v1.1*
