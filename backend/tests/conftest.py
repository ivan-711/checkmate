"""Database fixtures for the backend tests: a throwaway database, one rolled-back transaction per test."""
from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.db import make_engine

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://checkmate:checkmate@127.0.0.1:5432/checkmate_test_w3b")
SKIP_DB_TESTS = os.environ.get("CHECKMATE_SKIP_DB_TESTS") == "1"  # explicit opt-out only; never a silent skip


@pytest.fixture(scope="session")
def engine():
    if TEST_DATABASE_URL.rstrip("/").endswith("/checkmate"):
        pytest.fail("tests never run against the dev database; point TEST_DATABASE_URL at a test database")
    eng = make_engine(TEST_DATABASE_URL)
    try:
        with eng.connect() as c:
            c.execute(text("SELECT 1 FROM entity LIMIT 1"))
    except SQLAlchemyError as exc:  # pragma: no cover - environment, not code
        if SKIP_DB_TESTS:
            pytest.skip(f"test database unavailable or unmigrated: {exc}")
        pytest.fail(f"test database unavailable or unmigrated (set CHECKMATE_SKIP_DB_TESTS=1 to skip): {exc}")
    return eng


@pytest.fixture
def conn(engine):
    """One transaction per test, rolled back at the end: nothing persists, nothing to clean."""
    with engine.connect() as c:
        tx = c.begin()
        try:
            yield c
        finally:
            tx.rollback()
