# Registro de decisiones

Bitácora de decisiones técnicas no obvias tomadas durante el proyecto: qué se decidió, por qué, y qué alternativas se descartaron. Exigido en las reglas de trabajo del `README.md`.

## [Fecha] Título de la decisión

- **Contexto:** qué problema o disyuntiva motivó la decisión.
- **Decisión:** qué se hizo.
- **Alternativas descartadas:** qué otras opciones se consideraron y por qué no se eligieron.
- **Impacto:** qué partes del pipeline afecta.

---

## [2026-07-20] Almacenamiento de capas: PostgreSQL para Bronze/Silver/Gold, Parquet solo como exportación

- **Contexto:** se evaluó una arquitectura estilo lakehouse con Bronze y Silver como archivos Parquet y solo Gold en PostgreSQL. Es un patrón válido y común en la industria (separa almacenamiento barato de datos crudos/limpios del motor de serving analítico).
- **Decisión:** las tres capas (Bronze, Silver, Gold) se implementan como schemas de PostgreSQL, y Parquet se usa como formato de **exportación** de las capas en `data/parquet/` (fase 11 del proyecto).
- **Alternativas descartadas:** Bronze/Silver en Parquet + Gold en Postgres. Descartada porque la consigna es explícita en dos puntos: el stack define "PostgreSQL — motor de base de datos para las capas Bronze, Silver y Gold" y los entregables exigen "Modelo Bronze, Silver y Gold — implementado en PostgreSQL". Parquet aparece definido como "formato de exportación de las capas finales". Desviarse del spec en un proyecto evaluado agrega riesgo sin beneficio equivalente.
- **Impacto:** `sql/{bronze,silver,gold}/` (DDL sobre schemas Postgres), `src/` (ingesta a Postgres), fase de exportación a Parquet como paso final del DAG.

---

## [2026-07-21] Bronze preserva el CSV y separa metadatos de control

- **Contexto:** el discovery encontró datos válidos a nivel de formato y FK, pero múltiples inconsistencias semánticas. Tipar, deduplicar o corregir durante la ingesta impediría distinguir el valor original del tratamiento posterior.
- **Decisión:** las 18 tablas Bronze conservan todas las columnas fuente como `TEXT` y agregan metadatos de trazabilidad (`_batch_id`, `_source_file`, `_source_domain`, `_source_row_number`, `_row_hash`, `_ingested_at`). Una tabla de control registra checksum, estado y conteos de cada archivo.
- **Alternativas descartadas:** aplicar tipos finales y constraints de negocio en Bronze (rechazada porque podría impedir cargar evidencia defectuosa); copiar CSV sin batch/checksum (rechazada porque no permite auditar ni hacer reejecuciones idempotentes).
- **Impacto:** `sql/bronze/ddl.sql`, `src/ingest/bronze_loader.py`, validaciones CSV → Bronze y futura tarea de ingesta en Airflow.

---

## [2026-07-21] Problemas semánticos: preservar, flaggear y reconciliar sin sobrescribir

- **Contexto:** ninguna de las tres medidas financieras (`invoices.total`, suma de líneas y suma de payments) está demostrada como fuente única de revenue. También existen fechas, estados, relaciones CRM y atributos cross-domain contradictorios.
- **Decisión:** Silver conservará los valores reportados y añadirá medidas derivadas, flags y estados de reconciliación. No se reemplazarán fechas, no se anularán valores y no se elegirán supervivientes de duplicados sin una regla formal adicional. Student y customer se relacionarán mediante un bridge técnico, sin fusionar PII; CRM permanecerá separado.
- **Alternativas descartadas:** recalcular la cabecera desde items, usar payments como revenue, sustituir `enrolled_at` por el inicio del semester y deduplicar por prioridad de status. Todas fueron rechazadas porque los datos no demuestran cuál valor es verdadero.
- **Impacto:** especificación de Silver/Gold, pruebas de calidad, métricas financieras, documentación y presentación ejecutiva.

---

## [2026-07-22] Silver: adopción de reglas formales de tratamiento (refina la decisión del 2026-07-21)

- **Contexto:** la decisión previa optó por *no* recalcular, sustituir ni deduplicar mientras no hubiera una regla formal. Al implementar Silver, con el discovery ya verificado dos veces (pandas + NUMERIC exacto), la evidencia sí permite definir reglas formales, siempre **preservando el valor original en paralelo**.
- **Decisión:** cada regla materializa una columna derivada/canónica *junto a* la original y un flag, nunca en reemplazo:
  1. **Facturas:** `total` = Σ(line_total) de items (los items son la única medida internamente consistente: `line_total = qty·unit_price` en 150.000/150.000). El original se conserva en `total_reported` + flag `is_total_mismatch`. Para las 2.502 facturas sin items, `total` queda NULL y se usa `total_reported`.
  2. **Notas:** nota final por inscripción renormalizada `Σ(score·w)/Σ(w)` (tabla `silver.enrollment_grade_summary`), porque los pesos crudos no suman 1. Flag `weight_sum_ok`.
  3. **Inscripciones:** `enrolled_at` canónico = `semester.start_date` (el crudo es ruido: 91% fuera de ventana); el original se conserva en `enrolled_at_raw` + flag `enrolled_at_out_of_window`. Los duplicados lógicos NO se borran: se marcan `is_duplicate_enrollment` y se elige superviviente con regla formal de prioridad de status (`completed > failed > dropped > active`, desempate por id) vía `is_duplicate_survivor`. Silver conserva las 25.000 filas; Gold filtra a supervivientes.
  4. **Pagos:** NO se usan como revenue (montos sin relación aritmética con el total). Se deriva `payment_status_derived` (unpaid/partial/full/overpaid).
  5. **CRM y cross-domain:** solo flags (`account_mismatch`, `is_orphan`, `person_attributes_mismatch` implícito), sin merge de PII entre student y customer.
- **Nota sobre conteos exactos:** al reproducir los flags con NUMERIC exacto de Postgres, algunos conteos difieren levemente del perfilado original en pandas (float) por redondeo en los bordes de tolerancia: `weight_sum_ok` da **401** con tolerancia 0,01 (banda [0,99; 1,01]) en vez de 141 — el 141 era un artefacto de float (`0.99 - 1 = -0.01000000009` se excluía). También las bandas de `payment_status_derived` (overpaid 20.482, partial 10.943, full 8). El cálculo exacto es el correcto y es el que valida `src/validate_silver.py`.
- **Alternativas descartadas:** mantener la postura de "no tratar" (rechazada: con la evidencia verificada, no aplicar reglas dejaría a Gold sin medidas confiables); borrar físicamente duplicados/outliers (rechazada: se pierde evidencia y trazabilidad).
- **Impacto:** `sql/silver/ddl.sql`, `sql/silver/transform.sql`, `src/validate_silver.py`, y las medidas de `gold.fact_*`.

---

## [2026-07-24] Revenue: transparencia sobre tres medidas que no concilian (5×)

- **Contexto:** una revisión de QA independiente detectó que las cifras de revenue de `docs/insights.md` (medida de items) son ~5× las que se obtienen sumando `invoices.total`. Verificado contra los CSV crudos: header `Σ invoices.total` = 6,79M ≈ `Σ payments` = 6,49M (0,96×), pero `Σ items line_total` = 34,93M (5,14×). Las tres "fuentes de verdad" del revenue divergen radicalmente.
- **Decisión:** se mantiene `invoiced_amount` = suma de items como medida del modelo (coherente con Gold, KPIs y dashboard; los items son internamente consistentes `line_total = qty·unit`), **pero se documenta explícitamente la divergencia**: nota crítica al inicio de la sección 1 de `insights.md`, nuevo Insight 0 (en el doc y en el notebook, calculado en vivo) que presenta las tres medidas, y aclaración de escala (÷5 a header/pagos) donde el monto absoluto importa. Las conclusiones de tendencia y mix son proporcionales y no dependen de la medida.
- **Alternativas descartadas:** cambiar la medida del modelo a header/pagos (rechazado: rompería Gold/dashboard el día previo a la presentación, y el header está descorrelacionado de los items por factura — no es "más verdadero", solo más chico); ocultar la divergencia y quedarse solo con items (rechazado: un evaluador reproduce `invoices.total` y ve 1/5 — la transparencia convierte la debilidad del dato en evidencia de criterio).
- **Impacto:** `docs/insights.md` (nota de medida + Insight 0 + escalas), `notebooks/02_pipeline_y_kpis.ipynb` (Insight 0 en vivo). El modelo Gold no cambia (ya publicaba `total_reported`, `invoiced_amount` y pagos por separado).

---

## [2026-07-22] Gold: modelo estrella y definiciones de KPI

- **Contexto:** hay que exponer los datos limpios para analítica y dashboard (Superset), habilitando los KPIs de negocio con definiciones inequívocas.
- **Decisión:** modelo dimensional (estrella) con 7 dimensiones (`dim_date` 2005–2027, `dim_student`, `dim_customer`, `dim_product`, `dim_course`, `dim_semester`, `dim_account`) y 7 hechos (`fact_enrollment` solo supervivientes, `fact_invoice`, `fact_payment`, `fact_subscription`, `fact_opportunity`, `fact_activity`, `fact_lead`). Dimensiones y hechos son **tablas materializadas** (para dashboard y export a Parquet); los KPIs son **vistas** que se recalculan al consultarse. Definiciones clave:
  - **Revenue = `invoiced_amount`** = Σ items (o `total_reported` si no hay items). Los montos **nunca se suman entre monedas**: todo KPI financiero segmenta por `currency`.
  - **Cobranza** medida por estado de factura (`status='paid'`), no por suma de pagos (los montos de pago son inconsistentes).
  - **Aprobación académica** = `final_score_weighted >= 60`.
  - **MRR** = Σ `monthly_price` de suscripciones `active` y no `is_effectively_expired`.
  - `dim_customer` ↔ `dim_student` enlazadas por `external_ref` como clave técnica, sin fusionar atributos de persona.
- **Alternativas descartadas:** KPIs como tablas materializadas (rechazado: las vistas dan frescura sin recarga y el volumen es chico); sumar revenue multi-moneda a una moneda única (rechazado: no hay tipo de cambio en los datos, sería inventar un número).
- **Impacto:** `sql/gold/ddl.sql`, `sql/gold/load.sql`, `src/run_sql.py`, el dashboard de Superset (Día 4) y el export a Parquet.

---

## [2026-07-23] Orquestación: un DAG con validadores como gates, reusando los scripts existentes

- **Contexto:** fases 10–12 de la consigna (automatización, export Parquet, validación del pipeline). Toda la lógica ya existía como scripts probados individualmente; el riesgo era duplicarla dentro del DAG.
- **Decisión:** `dags/pipeline_medallion.py` orquesta con `BashOperator` los scripts existentes (`bronze_loader.py`, `run_sql.py`, `validate_*.py`) sin duplicar lógica. Cada capa está protegida por su validador como *gate*: si una validación falla, el pipeline se detiene antes de propagar datos malos. La ingesta Bronze se paraleliza por dominio (fan-out de 3 tareas) tras aplicar el DDL una sola vez. `schedule=None` (fuentes estáticas, ejecución bajo demanda), documentado que con fuentes vivas bastaría un `@daily`. `retries=1` con `retry_delay` de 2 min.
- **Alternativas descartadas:** `PythonOperator` importando las funciones (rechazado: acopla el parseo del DAG a imports pesados como pandas y duplica el manejo de entorno); reescribir la lógica dentro del DAG (rechazado: dos fuentes de verdad); un DAG por capa (rechazado: las dependencias entre capas son exactamente lo que el grafo debe expresar).
- **Impacto:** `dags/pipeline_medallion.py`. Corrida completa verificada en Airflow: 12/12 tareas success, con Bronze omitiendo por checksum (idempotencia demostrada en el propio run).

---

## [2026-07-23] Exportación Parquet: Silver y Gold completas, con validación de paridad

- **Contexto:** la consigna define Parquet como formato de exportación de las capas finales; la guía v2 lo deja opcional pero valora la justificación.
- **Decisión:** `src/export/parquet_exporter.py` exporta todas las tablas de Silver y Gold (más las vistas KPI de Gold) a `data/parquet/{silver,gold}/` con compresión snappy, y `src/validate_parquet.py` valida paridad archivo↔tabla (conteos por relación + sumas de medidas clave) como última tarea del DAG. Los archivos exportados se versionan en el repo (13 MB) porque son un entregable explícito. El exportador tolera ejecuciones desde contenedores con distinto UID (Airflow 50000 / Jupyter 1000) sobre el mismo bind mount: directorio permisivo + unlink previo — un `PermissionError` real detectado en la primera corrida del DAG.
- **Alternativas descartadas:** exportar solo Gold (rechazado: Silver exportado permite reconstruir análisis sin acceso a Postgres); particionar por fecha (rechazado: volúmenes chicos, la partición agregaría complejidad sin beneficio de lectura).
- **Impacto:** `src/export/parquet_exporter.py`, `src/validate_parquet.py`, tareas `exportar_parquet`/`validar_parquet` del DAG, `data/parquet/`.

---

## [2026-07-23] Dashboard: Superset en Docker, aprovisionado por API

- **Contexto:** la guía v2 agrega el dashboard como entregable (10%), sugiriendo Power BI u otra herramienta. El usuario eligió Superset.
- **Decisión:** servicio `superset` (imagen oficial 3.1.1 fijada) en el mismo `docker-compose`, conectado a la capa Gold por la red interna. Metadata propia de Superset en volumen dedicado (SQLite) para no ensuciar el data warehouse. `SUPERSET_SECRET_KEY` desde `.env`. En el comando de arranque, `|| true` protege **solo** a `create-admin` (falla esperada en reinicios si el usuario ya existe) con `set -e` para el resto — lección aprendida del bug de `airflow-init`. La conexión a la base, los 7 datasets (vistas KPI), 4 gráficos y el dashboard se aprovisionaron vía REST API, y se verificó con queries reales que cada gráfico devuelve datos.
- **Alternativas descartadas:** Power BI Desktop (rechazado: no es reproducible dentro del compose, requiere instalación y licencia en Windows); Metabase (más liviano, pero el usuario prefirió Superset); metadata de Superset en el Postgres del proyecto (rechazado: mezcla metadata de herramienta con el warehouse).
- **Impacto:** `docker-compose.yml`, `.env`/`.env.example`, dashboard "KPIs — CRM · Billing · Universidad" en `http://localhost:8088` (admin/admin).

---

## [2026-07-24] Dashboard como código: aprovisionamiento reproducible de Superset

- **Contexto:** el dashboard se había creado con llamadas a la API de Superset ejecutadas manualmente. Vivía solo dentro del volumen del contenedor: al recrearlo (o al levantar el proyecto desde cero) se perdía por completo. Eso rompía la reproducibilidad y dejaba el entregable "dashboard" fuera del control de versiones.
- **Decisión:** `src/dashboard/provision_superset.py` reconstruye todo el dashboard vía la REST API de Superset, de forma **idempotente** (busca-o-crea cada objeto por nombre: conexión a Gold, 7 datasets KPI, 4 gráficos, dashboard con `position_json` explícito para el layout 2×2). Reejecutarlo actualiza en vez de duplicar. Se documenta como paso final del arranque desde cero (tras la primera corrida del pipeline, que crea las vistas de Gold). No se cablea como servicio automático del compose porque depende de que Gold ya exista (lo produce el DAG), y esa dependencia de orden sería frágil en `depends_on`.
- **Alternativas descartadas:** exportar el dashboard como ZIP de assets de Superset e importarlo (rechazado: el ZIP es un artefacto opaco, menos legible y editable que el script; y hardcodea IDs); un servicio `superset-init` en el compose (rechazado: no puede garantizar que el DAG ya haya poblado Gold antes de correr).
- **Impacto:** `src/dashboard/provision_superset.py`, README (paso de aprovisionamiento). El dashboard ahora se reconstruye desde el repo en cualquier ambiente.

---

## [2026-07-20] Fix: Airflow no migraba su base de datos (conflicto de versión SQLAlchemy)

- **Contexto:** al levantar el stack con `docker compose up`, `docker ps` mostraba `airflow-webserver` y `airflow-scheduler` como "Up", pero `http://localhost:8080` no respondía (timeout). El contenedor `airflow-init` terminaba con exit code 0 pese a que `airflow db migrate` fallaba realmente con `sqlalchemy.exc.ArgumentError: Invalid value for 'executemany_mode': 'values'`. El comando del contenedor era `airflow db migrate && airflow users create ... || true`: por precedencia de operadores en bash, `(A && B) || C` — si `A` (migrate) fallaba, la cadena caía en `|| true`, enmascarando el fallo real y dejando el contenedor en estado "exitoso" falso. Webserver y scheduler quedaban en loop infinito de reintento contra una base de datos nunca migrada.
- **Causa raíz:** `requirements.txt` fijaba `sqlalchemy==2.0.27`, pero Airflow 2.8.1 requiere SQLAlchemy `<2.0` (el propio [constraints file oficial](https://raw.githubusercontent.com/apache/airflow/constraints-2.8.1/constraints-3.11.txt) fija `SQLAlchemy==1.4.51`). Al instalarse 2.0.27 sobre la imagen `apache/airflow:2.8.1-python3.11`, el dialecto `psycopg2` de Airflow pasaba un argumento (`executemany_mode="values"`) que ya no es válido en SQLAlchemy 2.0.
- **Decisión:**
  1. Bajar `sqlalchemy` a `1.4.51` en `requirements.txt`, y alinear también `pandas` (`2.1.4`) y `pyarrow` (`14.0.2`) a las versiones exactas del constraints file de Airflow 2.8.1, para evitar el mismo tipo de conflicto con otras libs.
  2. Agregar `--constraint ".../constraints-2.8.1/constraints-3.11.txt"` al `pip install` de `docker/airflow.Dockerfile`, para que futuros cambios a `requirements.txt` fallen la build de forma explícita en vez de instalar silenciosamente una versión incompatible.
  3. Corregir `docker-compose.yml`: agregar `set -e` al script de `airflow-init` para que un fallo real en `airflow db migrate` aborte el contenedor con exit code distinto de 0 (en vez de quedar enmascarado por el `|| true` de la línea siguiente).
  4. Dejar de hardcodear `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN` y `AIRFLOW__CORE__FERNET_KEY` como valores literales duplicados en `docker-compose.yml`; ahora se interpolan desde `.env` (`${POSTGRES_USER}`, etc.), igual que ya se hacía con las variables de Postgres.
- **Alternativas descartadas:** fijar `sqlalchemy` sin versión en `requirements.txt` (rechazado: pierde reproducibilidad exacta del build); usar Airflow 2.9+ (soporta SQLAlchemy 2.0) en vez de bajar la versión (rechazado: cambia el stack pedido por la consigna sin necesidad, más riesgo que beneficio a esta altura del desafío).
- **Impacto:** `docker/airflow.Dockerfile`, `requirements.txt`, `docker-compose.yml`. Verificado post-fix: `airflow-init` migra y crea el usuario admin (exit code 0 real), `curl localhost:8080/health` responde `{"metadatabase":{"status":"healthy"},"scheduler":{"status":"healthy"}}`.
