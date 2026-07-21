"""Configuración compartida del pipeline, basada en variables de entorno."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read_env_file(path: Path) -> dict[str, str]:
    """Lee un .env sencillo sin incorporar otra dependencia."""
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    database: str
    user: str
    password: str

    def as_psycopg_kwargs(self) -> dict[str, str | int]:
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.database,
            "user": self.user,
            "password": self.password,
        }


def get_database_config() -> DatabaseConfig:
    """Resuelve Postgres desde el entorno y, en host local, desde .env."""
    file_values = _read_env_file(PROJECT_ROOT / ".env")

    def value(name: str, default: str | None = None) -> str | None:
        return os.getenv(name) or file_values.get(name) or default

    default_host = "postgres" if Path("/.dockerenv").exists() else "localhost"
    required = {
        "POSTGRES_USER": value("POSTGRES_USER"),
        "POSTGRES_PASSWORD": value("POSTGRES_PASSWORD"),
        "POSTGRES_DB": value("POSTGRES_DB"),
    }
    missing = [name for name, resolved in required.items() if not resolved]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            f"Faltan variables de conexión: {joined}. "
            "Configúralas en el entorno o en .env."
        )

    return DatabaseConfig(
        host=str(value("POSTGRES_HOST", default_host)),
        port=int(str(value("POSTGRES_PORT", "5432"))),
        database=str(required["POSTGRES_DB"]),
        user=str(required["POSTGRES_USER"]),
        password=str(required["POSTGRES_PASSWORD"]),
    )
