"""Exporta las capas Silver y Gold a Parquet (formato columnar).

Silver y Gold se exportan completas: todas las tablas base de ambos schemas
y las vistas de KPI de Gold. Destino: data/parquet/{silver,gold}/<objeto>.parquet
con compresión snappy.

Idempotente: cada corrida sobrescribe los archivos (el estado final refleja
siempre la última versión de las tablas).

Uso (dentro del contenedor):
    python /opt/airflow/src/export/parquet_exporter.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
from sqlalchemy import create_engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import get_database_config  # noqa: E402

PARQUET_ROOT = PROJECT_ROOT / "data" / "parquet"

# (schema, incluir vistas)
LAYERS = [
    ("silver", False),
    ("gold", True),
]


def build_engine():
    db = get_database_config()
    url = (
        f"postgresql+psycopg2://{quote_plus(db.user)}:{quote_plus(db.password)}"
        f"@{db.host}:{db.port}/{db.database}"
    )
    return create_engine(url)


def relations_for(engine, schema: str, include_views: bool) -> list[str]:
    kinds = "('BASE TABLE', 'VIEW')" if include_views else "('BASE TABLE')"
    query = (
        "SELECT table_name FROM information_schema.tables "
        f"WHERE table_schema = %(schema)s AND table_type IN {kinds} "
        "ORDER BY table_name"
    )
    frame = pd.read_sql(query, engine, params={"schema": schema})
    return frame["table_name"].tolist()


def export_layer(engine, schema: str, include_views: bool) -> tuple[int, int]:
    target_dir = PARQUET_ROOT / schema
    target_dir.mkdir(parents=True, exist_ok=True)
    # El export puede ejecutarse desde contenedores con distinto UID (Airflow
    # uid 50000, Jupyter uid 1000) sobre el mismo bind mount. Directorio
    # permisivo + unlink previo evita PermissionError al sobrescribir archivos
    # creados por el otro usuario.
    try:
        target_dir.chmod(0o777)
    except PermissionError:
        pass

    exported = 0
    total_rows = 0
    for relation in relations_for(engine, schema, include_views):
        frame = pd.read_sql(f'SELECT * FROM {schema}."{relation}"', engine)
        target = target_dir / f"{relation}.parquet"
        try:
            target.unlink(missing_ok=True)
        except PermissionError:
            pass
        frame.to_parquet(target, engine="pyarrow", compression="snappy", index=False)
        size_kb = target.stat().st_size / 1024
        print(f"OK      {schema}/{relation}.parquet: {len(frame):,} filas ({size_kb:,.0f} KB)")
        exported += 1
        total_rows += len(frame)
    return exported, total_rows


def main() -> None:
    engine = build_engine()
    grand_files = 0
    grand_rows = 0
    for schema, include_views in LAYERS:
        files, rows = export_layer(engine, schema, include_views)
        grand_files += files
        grand_rows += rows
    print(f"\nExportados {grand_files} objetos, {grand_rows:,} filas -> {PARQUET_ROOT}")


if __name__ == "__main__":
    main()
