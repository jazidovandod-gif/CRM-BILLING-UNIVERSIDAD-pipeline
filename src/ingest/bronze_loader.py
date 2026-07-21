"""Carga idempotente de los 18 CSV a PostgreSQL Bronze.

La identidad de cada archivo se obtiene con SHA-256. Si el mismo contenido ya fue
cargado correctamente, la reejecución se omite. Cada fila conserva su posición y
un hash de sus valores para permitir reconciliación posterior.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import get_database_config  # noqa: E402


DEFAULT_MANIFEST = PROJECT_ROOT / "manifest.json"
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_DDL = PROJECT_ROOT / "sql" / "bronze" / "ddl.sql"


@dataclass(frozen=True)
class SourceSpec:
    domain: str
    table: str
    columns: tuple[str, ...]
    expected_rows: int
    source_path: Path

    @property
    def target_table(self) -> str:
        return f"{self.domain}_{self.table}"

    @property
    def relative_source(self) -> str:
        try:
            return self.source_path.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            return self.source_path.as_posix()


@dataclass(frozen=True)
class LoadResult:
    source: str
    target: str
    status: str
    rows: int
    batch_id: str


def read_manifest(manifest_path: Path, raw_dir: Path) -> list[SourceSpec]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources: list[SourceSpec] = []
    for domain, tables in manifest["domains"].items():
        for table, definition in tables.items():
            sources.append(
                SourceSpec(
                    domain=domain,
                    table=table,
                    columns=tuple(definition["cols"]),
                    expected_rows=int(definition["rows"]),
                    source_path=raw_dir / domain / f"{table}.csv",
                )
            )
    return sources


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_row(values: Iterable[str]) -> str:
    canonical = json.dumps(
        list(values),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_source(spec: SourceSpec) -> None:
    if not spec.source_path.exists():
        raise FileNotFoundError(f"No existe el archivo: {spec.source_path}")

    with spec.source_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source)
        try:
            header = tuple(next(reader))
        except StopIteration as exc:
            raise ValueError(f"CSV vacío: {spec.source_path}") from exc
        if header != spec.columns:
            raise ValueError(
                f"Schema inesperado en {spec.relative_source}: "
                f"esperado={list(spec.columns)}, recibido={list(header)}"
            )
        row_count = sum(1 for _ in reader)

    if row_count != spec.expected_rows:
        raise ValueError(
            f"Conteo inesperado en {spec.relative_source}: "
            f"esperado={spec.expected_rows}, recibido={row_count}"
        )


def apply_ddl(conn: connection, ddl_path: Path) -> None:
    ddl = ddl_path.read_text(encoding="utf-8")
    with conn.cursor() as cursor:
        cursor.execute(ddl)
    conn.commit()


def _batch_lookup(
    conn: connection,
    spec: SourceSpec,
    checksum: str,
) -> tuple[str, str, int] | None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT batch_id::text, status, loaded_rows
            FROM bronze.ingestion_batches
            WHERE source_domain = %s
              AND source_table = %s
              AND source_checksum = %s
            """,
            (spec.domain, spec.table, checksum),
        )
        row = cursor.fetchone()
    return (str(row[0]), str(row[1]), int(row[2])) if row else None


def _rows_for_batch(conn: connection, spec: SourceSpec, batch_id: str) -> int:
    statement = sql.SQL(
        "SELECT COUNT(*) FROM bronze.{} WHERE _batch_id = %s"
    ).format(sql.Identifier(spec.target_table))
    with conn.cursor() as cursor:
        cursor.execute(statement, (batch_id,))
        return int(cursor.fetchone()[0])


def _prepare_batch(
    conn: connection,
    spec: SourceSpec,
    checksum: str,
) -> tuple[str, bool]:
    existing = _batch_lookup(conn, spec, checksum)
    if existing:
        batch_id, status, loaded_rows = existing
        actual_rows = _rows_for_batch(conn, spec, batch_id)
        if (
            status == "success"
            and loaded_rows == spec.expected_rows
            and actual_rows == spec.expected_rows
        ):
            return batch_id, True

        delete_rows = sql.SQL(
            "DELETE FROM bronze.{} WHERE _batch_id = %s"
        ).format(sql.Identifier(spec.target_table))
        with conn.cursor() as cursor:
            cursor.execute(delete_rows, (batch_id,))
            cursor.execute(
                """
                UPDATE bronze.ingestion_batches
                SET status = 'loading',
                    expected_rows = %s,
                    loaded_rows = 0,
                    started_at = CURRENT_TIMESTAMP,
                    completed_at = NULL,
                    error_message = NULL
                WHERE batch_id = %s
                """,
                (spec.expected_rows, batch_id),
            )
        conn.commit()
        return batch_id, False

    batch_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO bronze.ingestion_batches (
                batch_id,
                source_domain,
                source_table,
                target_table,
                source_file,
                source_checksum,
                expected_rows,
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'loading')
            """,
            (
                batch_id,
                spec.domain,
                spec.table,
                f"bronze.{spec.target_table}",
                spec.relative_source,
                checksum,
                spec.expected_rows,
            ),
        )
    conn.commit()
    return batch_id, False


def _copy_rows(conn: connection, spec: SourceSpec, batch_id: str) -> int:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    loaded_rows = 0

    with spec.source_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != spec.columns:
            raise ValueError(f"El encabezado cambió durante la carga: {spec.relative_source}")

        for row_number, row in enumerate(reader, start=1):
            source_values = [row[column] for column in spec.columns]
            writer.writerow(
                source_values
                + [
                    batch_id,
                    spec.relative_source,
                    spec.domain,
                    row_number,
                    sha256_row(source_values),
                ]
            )
            loaded_rows += 1

    if loaded_rows != spec.expected_rows:
        raise ValueError(
            f"El archivo cambió durante la carga de {spec.relative_source}: "
            f"esperado={spec.expected_rows}, leído={loaded_rows}"
        )

    target_columns = list(spec.columns) + [
        "_batch_id",
        "_source_file",
        "_source_domain",
        "_source_row_number",
        "_row_hash",
    ]
    copy_statement = sql.SQL(
        "COPY bronze.{} ({}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')"
    ).format(
        sql.Identifier(spec.target_table),
        sql.SQL(", ").join(map(sql.Identifier, target_columns)),
    )
    buffer.seek(0)
    with conn.cursor() as cursor:
        cursor.copy_expert(copy_statement.as_string(conn), buffer)
    return loaded_rows


def _mark_success(
    conn: connection,
    spec: SourceSpec,
    batch_id: str,
    loaded_rows: int,
) -> None:
    actual_rows = _rows_for_batch(conn, spec, batch_id)
    if actual_rows != loaded_rows:
        raise RuntimeError(
            f"Reconciliación fallida en bronze.{spec.target_table}: "
            f"COPY={loaded_rows}, PostgreSQL={actual_rows}"
        )
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE bronze.ingestion_batches
            SET status = 'success',
                loaded_rows = %s,
                completed_at = CURRENT_TIMESTAMP,
                error_message = NULL
            WHERE batch_id = %s
            """,
            (loaded_rows, batch_id),
        )


def _mark_failed(conn: connection, batch_id: str, error: Exception) -> None:
    conn.rollback()
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE bronze.ingestion_batches
            SET status = 'failed',
                loaded_rows = 0,
                completed_at = CURRENT_TIMESTAMP,
                error_message = %s
            WHERE batch_id = %s
            """,
            (str(error)[:4000], batch_id),
        )
    conn.commit()


def load_source(conn: connection, spec: SourceSpec) -> LoadResult:
    validate_source(spec)
    checksum = sha256_file(spec.source_path)
    batch_id, should_skip = _prepare_batch(conn, spec, checksum)
    if should_skip:
        return LoadResult(
            source=spec.relative_source,
            target=f"bronze.{spec.target_table}",
            status="skipped",
            rows=spec.expected_rows,
            batch_id=batch_id,
        )

    try:
        loaded_rows = _copy_rows(conn, spec, batch_id)
        _mark_success(conn, spec, batch_id, loaded_rows)
        conn.commit()
    except Exception as error:
        _mark_failed(conn, batch_id, error)
        raise

    return LoadResult(
        source=spec.relative_source,
        target=f"bronze.{spec.target_table}",
        status="loaded",
        rows=loaded_rows,
        batch_id=batch_id,
    )


def select_sources(
    sources: list[SourceSpec],
    domain: str | None,
    table: str | None,
) -> list[SourceSpec]:
    selected = [
        source
        for source in sources
        if (domain is None or source.domain == domain)
        and (table is None or source.table == table)
    ]
    if not selected:
        raise ValueError(
            f"No hay fuentes para domain={domain or 'all'}, table={table or 'all'}"
        )
    return selected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--domain",
        choices=["university", "billing", "crm"],
        help="Carga únicamente un dominio.",
    )
    parser.add_argument("--table", help="Carga únicamente una tabla.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--ddl", type=Path, default=DEFAULT_DDL)
    parser.add_argument(
        "--skip-ddl",
        action="store_true",
        help="No ejecuta el DDL idempotente antes de cargar.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sources = read_manifest(args.manifest, args.raw_dir)
    selected = select_sources(sources, args.domain, args.table)
    database = get_database_config()

    results: list[LoadResult] = []
    with psycopg2.connect(**database.as_psycopg_kwargs()) as conn:
        if not args.skip_ddl:
            apply_ddl(conn, args.ddl)
        for spec in selected:
            result = load_source(conn, spec)
            results.append(result)
            print(
                f"{result.status.upper():7} {result.source} -> "
                f"{result.target}: {result.rows:,} filas"
            )

    loaded = sum(result.rows for result in results if result.status == "loaded")
    skipped = sum(result.rows for result in results if result.status == "skipped")
    print(
        f"Fuentes procesadas: {len(results)} | "
        f"filas cargadas: {loaded:,} | filas omitidas por idempotencia: {skipped:,}"
    )


if __name__ == "__main__":
    main()
