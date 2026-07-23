"""Ejecutor de scripts SQL contra PostgreSQL.

Reutilizable por el pipeline (Silver, Gold) y por el DAG de Airflow. Cada
archivo se ejecuta dentro de una única transacción: si algo falla, se revierte
completo (atomicidad). Los scripts son idempotentes (DROP/TRUNCATE + recrear).

Uso:
    python src/run_sql.py sql/silver/ddl.sql sql/silver/transform.sql
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import get_database_config  # noqa: E402


def run_sql_file(conn, path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"No existe el script SQL: {path}")
    statements = path.read_text(encoding="utf-8")
    with conn.cursor() as cursor:
        cursor.execute(statements)
    conn.commit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scripts", nargs="+", type=Path, help="Rutas a archivos .sql")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database = get_database_config()
    with psycopg2.connect(**database.as_psycopg_kwargs()) as conn:
        for raw_path in args.scripts:
            path = raw_path if raw_path.is_absolute() else PROJECT_ROOT / raw_path
            try:
                run_sql_file(conn, path)
                print(f"OK      {raw_path}")
            except Exception as error:  # noqa: BLE001
                conn.rollback()
                print(f"ERROR   {raw_path}: {error}", file=sys.stderr)
                raise


if __name__ == "__main__":
    main()
