"""DAG del pipeline medallion: CSV -> Bronze -> Silver -> Gold -> Parquet.

Orquesta los scripts existentes del proyecto (no duplica lógica):
  * src/ingest/bronze_loader.py   — ingesta idempotente por checksum
  * src/run_sql.py                — DDL + transformaciones Silver/Gold
  * src/validate_{bronze,silver,gold,parquet}.py — gates de calidad

Diseño:
  * Cada capa está protegida por su validador: si una validación falla,
    el pipeline se detiene antes de propagar datos malos río abajo.
  * La ingesta Bronze se paraleliza por dominio (university/billing/crm)
    tras aplicar el DDL una sola vez.
  * Todo el pipeline es idempotente: reejecutar el DAG no duplica datos
    (Bronze omite por checksum; Silver/Gold son TRUNCATE + INSERT).
  * schedule=None: los CSV de origen son estáticos, la ejecución es bajo
    demanda. Con fuentes vivas bastaría cambiar el schedule a p. ej. "@daily".
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

PY = "python /opt/airflow/src"

default_args = {
    "owner": "data-engineering",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}

with DAG(
    dag_id="pipeline_medallion",
    description="CSV -> Bronze -> Silver -> Gold -> Parquet con validación por capa",
    start_date=datetime(2026, 7, 1),
    schedule=None,
    catchup=False,
    default_args=default_args,
    tags=["bootcamp", "medallion"],
) as dag:

    validar_fuentes = BashOperator(
        task_id="validar_fuentes",
        bash_command=(
            'test -f /opt/airflow/manifest.json && '
            'n=$(find /opt/airflow/data/raw -name "*.csv" | wc -l) && '
            'echo "CSVs encontrados: $n" && test "$n" -eq 18'
        ),
    )

    preparar_bronze_ddl = BashOperator(
        task_id="preparar_bronze_ddl",
        bash_command=f"{PY}/run_sql.py sql/bronze/ddl.sql",
    )

    ingesta_bronze = [
        BashOperator(
            task_id=f"ingesta_bronze_{domain}",
            bash_command=f"{PY}/ingest/bronze_loader.py --domain {domain} --skip-ddl",
        )
        for domain in ("university", "billing", "crm")
    ]

    validar_bronze = BashOperator(
        task_id="validar_bronze",
        bash_command=f"{PY}/validate_bronze.py",
    )

    transformar_silver = BashOperator(
        task_id="transformar_silver",
        bash_command=f"{PY}/run_sql.py sql/silver/ddl.sql sql/silver/transform.sql",
    )

    validar_silver = BashOperator(
        task_id="validar_silver",
        bash_command=f"{PY}/validate_silver.py",
    )

    cargar_gold = BashOperator(
        task_id="cargar_gold",
        bash_command=f"{PY}/run_sql.py sql/gold/ddl.sql sql/gold/load.sql",
    )

    validar_gold = BashOperator(
        task_id="validar_gold",
        bash_command=f"{PY}/validate_gold.py",
    )

    exportar_parquet = BashOperator(
        task_id="exportar_parquet",
        bash_command=f"{PY}/export/parquet_exporter.py",
    )

    validar_parquet = BashOperator(
        task_id="validar_parquet",
        bash_command=f"{PY}/validate_parquet.py",
    )

    validar_fuentes >> preparar_bronze_ddl >> ingesta_bronze >> validar_bronze
    validar_bronze >> transformar_silver >> validar_silver
    validar_silver >> cargar_gold >> validar_gold
    validar_gold >> exportar_parquet >> validar_parquet
