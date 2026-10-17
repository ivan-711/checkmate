"""Apply unapplied numbered SQL migrations in order, in autocommit mode.

Usage: ``python -m contracts.migrations.apply`` (reads DATABASE_URL). Each file runs as
one script; its version is recorded in ``schema_migration`` only after it succeeds.
Autocommit is required because TimescaleDB continuous aggregates cannot be created
inside a transaction block.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).parent
FILE_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def migration_files() -> list[Path]:
    files = sorted(p for p in MIGRATIONS_DIR.iterdir() if FILE_RE.match(p.name))
    versions = [p.name[:4] for p in files]
    if len(versions) != len(set(versions)):
        raise SystemExit(f"duplicate migration version among {versions}")
    return files


def applied_versions(conn: psycopg.Connection) -> set[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migration (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    return {row[0] for row in conn.execute("SELECT version FROM schema_migration")}


def apply_all(database_url: str) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(database_url, autocommit=True) as conn:
        done = applied_versions(conn)
        for path in migration_files():
            version = path.stem
            if version in done:
                continue
            conn.execute(path.read_text())
            conn.execute("INSERT INTO schema_migration (version) VALUES (%s)", (version,))
            applied.append(version)
    return applied


def main() -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set")
    applied = apply_all(url)
    print("applied: " + (", ".join(applied) if applied else "nothing (up to date)"))


if __name__ == "__main__":
    sys.exit(main())
