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

from backend.ingest.csvio import read_csv_dir
from backend.ingest.fhir import load_bundle
from backend.ingest.store import clear_records

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


@pytest.fixture
def db():
    try:
        # autocommit: otherwise a test's last SELECT leaves an implicit transaction open, the
        # teardown's transaction() becomes a savepoint inside it and close() rolls the cleanup back.
        conn = psycopg.connect(TEST_DATABASE_URL, connect_timeout=3, autocommit=True)
    except psycopg.OperationalError as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"test database unreachable: {exc}")
    if "checkmate_test" not in TEST_DATABASE_URL:
        pytest.skip("refusing to run destructive fixtures against a non-test database")
    clear_records(conn)
    try:
        yield conn
    finally:
        clear_records(conn)
        conn.close()
