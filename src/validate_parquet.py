"""Validación final del pipeline: exportación Parquet vs. base de datos.

Comprueba que cada archivo Parquet exportado coincide con su relación de
origen en PostgreSQL:
  1. Cobertura: existe un .parquet por cada tabla/vista esperada.
  2. Conteo de filas: parquet == relación en la base.
  3. Spot-checks de contenido: sumas de medidas clave coinciden.

Es la última tarea del DAG: si esto pasa, el ciclo completo
CSV -> Bronze -> Silver -> Gold -> Parquet quedó reconciliado.

Uso (dentro del contenedor):
    python /opt/airflow/src/validate_parquet.py
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import psycopg2
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import get_database_config  # noqa: E402

PARQUET_ROOT = PROJECT_ROOT / "data" / "parquet"


def db_relations(cur, schema: str, include_views: bool) -> list[str]:
    kinds = ("BASE TABLE", "VIEW") if include_views else ("BASE TABLE",)
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = %s AND table_type = ANY(%s) ORDER BY table_name",
        (schema, list(kinds)),
    )
    return [row[0] for row in cur.fetchall()]


def check_layer(cur, schema: str, include_views: bool) -> int:
    failures = 0
    expected = db_relations(cur, schema, include_views)
    layer_dir = PARQUET_ROOT / schema

    print(f"\n== Capa {schema}: {len(expected)} relaciones esperadas ==")
    for relation in expected:
        target = layer_dir / f"{relation}.parquet"
        if not target.exists():
            print(f"  FALLA  {schema}/{relation}: falta el archivo parquet")
            failures += 1
            continue
        parquet_rows = pq.read_metadata(target).num_rows
        cur.execute(f'SELECT count(*) FROM {schema}."{relation}"')
        db_rows = cur.fetchone()[0]
        ok = parquet_rows == db_rows
        failures += not ok
        print(
            f"  {'OK ' if ok else 'FALLA'}  {schema}/{relation}: "
            f"parquet={parquet_rows:,} db={db_rows:,}"
        )
    return failures


# (etiqueta, archivo parquet, columna a sumar, SQL con la misma suma en la base)
SPOT_CHECKS = [
    ("Σ invoiced_amount (gold.fact_invoice)",
     "gold/fact_invoice.parquet", "invoiced_amount",
     "SELECT sum(invoiced_amount) FROM gold.fact_invoice"),
    ("Σ line_total (silver.billing_invoice_items)",
     "silver/billing_invoice_items.parquet", "line_total",
     "SELECT sum(line_total) FROM silver.billing_invoice_items"),
    ("Σ final_score (gold.fact_enrollment)",
     "gold/fact_enrollment.parquet", "final_score",
     "SELECT sum(final_score) FROM gold.fact_enrollment"),
]


def spot_checks(cur) -> int:
    failures = 0
    print("\n== Spot-checks de contenido (sumas) ==")
    for label, parquet_rel, column, query in SPOT_CHECKS:
        table = pq.read_table(PARQUET_ROOT / parquet_rel, columns=[column])
        values = [v for v in table.column(column).to_pylist() if v is not None]
        parquet_sum = sum(Decimal(str(v)) for v in values)
        cur.execute(query)
        db_sum = Decimal(str(cur.fetchone()[0]))
        ok = abs(parquet_sum - db_sum) < Decimal("0.01")
        failures += not ok
        print(f"  {'OK ' if ok else 'FALLA'}  {label}: parquet={parquet_sum} db={db_sum}")
    return failures


def main() -> None:
    database = get_database_config()
    failures = 0
    with psycopg2.connect(**database.as_psycopg_kwargs()) as conn:
        with conn.cursor() as cur:
            failures += check_layer(cur, "silver", include_views=False)
            failures += check_layer(cur, "gold", include_views=True)
            failures += spot_checks(cur)

    if failures:
        print(f"\nFALLARON {failures} comprobaciones.")
        sys.exit(1)
    print("\nExportación Parquet validada correctamente.")


if __name__ == "__main__":
    main()
