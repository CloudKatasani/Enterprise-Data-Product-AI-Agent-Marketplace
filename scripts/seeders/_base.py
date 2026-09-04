"""Seeding helpers.

Seeding is idempotent: running it twice leaves the same database state. Every
seeder is a function taking an open connection and the tenant it is seeding, so
the ordering lives in one place (``scripts/seeders/__init__.py``) rather than in
each seeder's imagination.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import psycopg

from scripts._paths import MANIFESTS
from scripts.manifests.loader import load_manifest


def load_directory(name: str) -> list[Any]:
    """Every manifest in ``manifests/<name>/`` in filename order."""
    directory = MANIFESTS / name
    if not directory.exists():
        return []
    return [load_manifest(path).data for path in sorted(directory.glob("*.yaml"))]


def load_directory_with_paths(name: str) -> list[tuple[Path, Any]]:
    directory = MANIFESTS / name
    if not directory.exists():
        return []
    return [(path, load_manifest(path).data) for path in sorted(directory.glob("*.yaml"))]


def source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upsert(
    connection: psycopg.Connection[Any],
    table: str,
    keys: dict[str, Any],
    values: dict[str, Any],
) -> None:
    """Insert or update a row keyed on ``keys``. Used only for mutable tables."""
    columns = {**keys, **values}
    placeholders = ", ".join(["%s"] * len(columns))
    assignments = ", ".join(f"{name} = EXCLUDED.{name}" for name in values)
    conflict = ", ".join(keys)
    statement = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict}) DO UPDATE SET {assignments}"
        if values
        else f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict}) DO NOTHING"
    )
    with connection.cursor() as cursor:
        cursor.execute(statement, tuple(columns.values()))


def insert_ignore(
    connection: psycopg.Connection[Any], table: str, values: dict[str, Any], conflict: str
) -> None:
    placeholders = ", ".join(["%s"] * len(values))
    statement = (
        f"INSERT INTO {table} ({', '.join(values)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict}) DO NOTHING"
    )
    with connection.cursor() as cursor:
        cursor.execute(statement, tuple(values.values()))
