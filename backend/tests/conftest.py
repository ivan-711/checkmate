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


def purge(engine, record_ids) -> None:
    """Delete everything committed for these source records: route tests commit through the app's
    own pool, so they clean up after themselves (test database only; the guard above refuses the dev one)."""
    ids = list(record_ids)
    if not ids:
        return
    with engine.begin() as c:
        pairs = [r[0] for r in c.execute(text(
            "SELECT id FROM candidate_pair WHERE record_a_id = ANY(:ids) OR record_b_id = ANY(:ids)"), {"ids": ids})]
        entities = [r[0] for r in c.execute(text(
            "SELECT DISTINCT entity_id FROM entity_member WHERE source_record_id = ANY(:ids)"), {"ids": ids})]
        c.execute(text("DELETE FROM event_log WHERE entity_id = ANY(:e) OR pair_id = ANY(:p)"), {"e": entities, "p": pairs})
        c.execute(text("DELETE FROM entity WHERE id = ANY(:e)"), {"e": entities})  # cascades members and alerts
        c.execute(text("DELETE FROM not_a_match WHERE record_a_id = ANY(:ids) OR record_b_id = ANY(:ids)"), {"ids": ids})
        c.execute(text("DELETE FROM match_decision WHERE pair_id = ANY(:p)"), {"p": pairs})
        c.execute(text("DELETE FROM candidate_pair WHERE id = ANY(:p)"), {"p": pairs})
        c.execute(text("DELETE FROM source_record WHERE id = ANY(:ids)"), {"ids": ids})
