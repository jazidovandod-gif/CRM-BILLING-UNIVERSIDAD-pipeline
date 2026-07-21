# Registro de decisiones

Bitácora de decisiones técnicas no obvias tomadas durante el proyecto: qué se decidió, por qué, y qué alternativas se descartaron. Exigido en las reglas de trabajo del `README.md`.

## [Fecha] Título de la decisión

- **Contexto:** qué problema o disyuntiva motivó la decisión.
- **Decisión:** qué se hizo.
- **Alternativas descartadas:** qué otras opciones se consideraron y por qué no se eligieron.
- **Impacto:** qué partes del pipeline afecta.

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
