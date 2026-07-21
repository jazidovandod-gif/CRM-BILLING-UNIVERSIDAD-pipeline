"""Reconciliación de los CSV actuales contra sus batches en Bronze."""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import get_database_config  # noqa: E402
from src.ingest.bronze_loader import (  # noqa: E402
    DEFAULT_MANIFEST,
    DEFAULT_RAW_DIR,
    SourceSpec,
    read_manifest,
    sha256_file,
    sha256_row,
)


@dataclass(frozen=True)
class ValidationResult:
    source: str
    target: str
    expected_rows: int
    bronze_rows: int
    metadata_nulls: int
    content_matches: bool
    status: str


def source_content_digest(spec: SourceSpec) -> str:
    digest = hashlib.sha256()
    with spec.source_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        for row in reader:
            values = [row[column] for column in spec.columns]
            digest.update(bytes.fromhex(sha256_row(values)))
    return digest.hexdigest()


def bronze_content_digest(
    conn: connection,
    spec: SourceSpec,
    batch_id: str,
) -> str:
    digest = hashlib.sha256()
    statement = sql.SQL(
        """
        SELECT _row_hash
        FROM bronze.{}
        WHERE _batch_id = %s
        ORDER BY _source_row_number
        """
    ).format(sql.Identifier(spec.target_table))
    cursor_name = f"validate_{spec.domain}_{spec.table}"
    with conn.cursor(name=cursor_name) as cursor:
        cursor.itersize = 10_000
        cursor.execute(statement, (batch_id,))
        for (row_hash,) in cursor:
            digest.update(bytes.fromhex(str(row_hash)))
    return digest.hexdigest()


def validate_source(
    conn: connection,
    spec: SourceSpec,
) -> ValidationResult:
    checksum = sha256_file(spec.source_path)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT batch_id::text, status, expected_rows, loaded_rows
            FROM bronze.ingestion_batches
            WHERE source_domain = %s
              AND source_table = %s
              AND source_checksum = %s
            """,
            (spec.domain, spec.table, checksum),
        )
        batch = cursor.fetchone()

    if not batch:
        return ValidationResult(
            source=spec.relative_source,
            target=f"bronze.{spec.target_table}",
            expected_rows=spec.expected_rows,
            bronze_rows=0,
            metadata_nulls=0,
            content_matches=False,
            status="missing_batch",
        )

    batch_id, batch_status, expected_rows, loaded_rows = batch
    count_statement = sql.SQL(
        """
        SELECT
            COUNT(*) AS bronze_rows,
            COUNT(*) FILTER (
                WHERE _batch_id IS NULL
                   OR _source_file IS NULL
                   OR _source_domain IS NULL
                   OR _source_row_number IS NULL
                   OR _row_hash IS NULL
                   OR _ingested_at IS NULL
            ) AS metadata_nulls,
            COUNT(DISTINCT _source_row_number) AS distinct_row_numbers
        FROM bronze.{}
        WHERE _batch_id = %s
        """
    ).format(sql.Identifier(spec.target_table))
    with conn.cursor() as cursor:
        cursor.execute(count_statement, (batch_id,))
        bronze_rows, metadata_nulls, distinct_row_numbers = cursor.fetchone()

    content_matches = (
        source_content_digest(spec)
        == bronze_content_digest(conn, spec, str(batch_id))
    )
    checks_pass = (
        batch_status == "success"
        and int(expected_rows) == spec.expected_rows
        and int(loaded_rows) == spec.expected_rows
        and int(bronze_rows) == spec.expected_rows
        and int(distinct_row_numbers) == spec.expected_rows
        and int(metadata_nulls) == 0
        and content_matches
    )
    return ValidationResult(
        source=spec.relative_source,
        target=f"bronze.{spec.target_table}",
        expected_rows=spec.expected_rows,
        bronze_rows=int(bronze_rows),
        metadata_nulls=int(metadata_nulls),
        content_matches=content_matches,
        status="ok" if checks_pass else "failed",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sources = read_manifest(args.manifest, args.raw_dir)
    database = get_database_config()
    results: list[ValidationResult] = []

    with psycopg2.connect(**database.as_psycopg_kwargs()) as conn:
        for spec in sources:
            result = validate_source(conn, spec)
            results.append(result)
            print(
                f"{result.status.upper():13} {result.target}: "
                f"{result.bronze_rows:,}/{result.expected_rows:,} filas | "
                f"metadata_nulls={result.metadata_nulls} | "
                f"contenido={'OK' if result.content_matches else 'DIFF'}"
            )

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status = 'success'),
                    COUNT(*) FILTER (WHERE status = 'failed')
                FROM bronze.ingestion_batches
                """
            )
            successful_batches, failed_batches = map(int, cursor.fetchone())

    failed = [result for result in results if result.status != "ok"]
    expected_total = sum(result.expected_rows for result in results)
    bronze_total = sum(result.bronze_rows for result in results)
    print(
        f"Tablas validadas: {len(results) - len(failed)}/{len(results)} | "
        f"filas: {bronze_total:,}/{expected_total:,} | "
        f"batches success={successful_batches}, failed={failed_batches}"
    )
    if failed or failed_batches:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
