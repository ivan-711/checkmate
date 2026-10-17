"""Shared fixtures: tiny synthetic bundles and CSVs, and the W1 test database connection.

Database tests use CHECKMATE_TEST_DATABASE_URL (default: checkmate_test_w1 on the compose
stack). They skip, with the reason printed, when that database is unreachable; they never
touch the `checkmate` database.
"""
from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from backend.ingest.csvio import read_csv_dir
from backend.ingest.fhir import load_bundle

FIXTURES = Path(__file__).parent / "fixtures"
TEST_DATABASE_URL = os.environ.get(
    "CHECKMATE_TEST_DATABASE_URL", "postgresql://checkmate:checkmate@127.0.0.1:5432/checkmate_test_w1"
)
PATIENT_A = "aaaaaaaa-0000-4000-8000-000000000001"
PATIENT_B = "bbbbbbbb-0000-4000-8000-000000000001"


@pytest.fixture(scope="session")
def bundles():
    loaded = [load_bundle(FIXTURES / name) for name in ("bundle_a.json", "bundle_b.json")]
    return {b.patient_id: b for b in loaded}


@pytest.fixture(scope="session")
def csv_patients(bundles):
    return read_csv_dir(FIXTURES / "csv", patient_ids=set(bundles))


# source_record and every table that references it, directly or through another table, deepest
# first so each DELETE runs after its dependents are gone. Read from the catalog, so a table a later
# migration adds is covered without editing this list.
_DEPENDENT_TABLES = """
WITH RECURSIVE deps(rel, depth) AS (
    SELECT 'source_record'::regclass::oid, 0
    UNION ALL
    SELECT con.conrelid, deps.depth + 1
    FROM pg_constraint con JOIN deps ON con.confrelid = deps.rel
    WHERE con.contype = 'f' AND con.conrelid <> con.confrelid AND deps.depth < 10
)
SELECT ns.nspname, cls.relname
FROM deps JOIN pg_class cls ON cls.oid = deps.rel JOIN pg_namespace ns ON ns.oid = cls.relnamespace
GROUP BY ns.nspname, cls.relname
ORDER BY max(deps.depth) DESC, cls.relname
"""


def clear_test_state(conn: psycopg.Connection) -> None:
    """Empty source_record and everything that references it, in this connection's transaction.

    Another lane's suite can share the database (one CHECKMATE_TEST_DATABASE_URL for the whole run)
    and leave committed rows, e.g. candidate_pair, that reference source records; deleting only
    the three ingest tables would then fail on a foreign key.
    """
    for schema, table in conn.execute(_DEPENDENT_TABLES).fetchall():
        conn.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(schema, table)))


@pytest.fixture
def db():
    """One REPEATABLE READ transaction per test, always rolled back.

    Every worktree on main runs these tests against the same default database, so nothing a test
    does may be committed. What that buys: its DELETE and inserts stay invisible to other sessions;
    two concurrent runs of these tests (which never commit) wait on each other's row locks instead
    of wiping each other's rows; a corpus a CLI load committed survives; and a suite run before
    this one in the same process (CI's single URL) cannot break the clear. What it does not: if
    another process *commits* a row these tests also write while a test is open, Postgres raises a
    serialization error, so the test fails loudly rather than passing on a count it did not make.
    ``clear_test_state`` and ``ingest`` open nested ``transaction()`` blocks, which become savepoints.
    """
    if "checkmate_test" not in TEST_DATABASE_URL:
        pytest.skip("refusing to run destructive fixtures against a non-test database")
    try:
        conn = psycopg.connect(TEST_DATABASE_URL, connect_timeout=3, autocommit=True)
    except psycopg.OperationalError as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"test database unreachable: {exc}")
    # A stable snapshot, so a CLI load committing to the same database cannot move a test's counts.
    conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
    try:
        with conn.transaction(force_rollback=True):
            clear_test_state(conn)  # only this transaction's view of the tables is emptied
            yield conn
    finally:
        conn.close()
