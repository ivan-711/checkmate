"""Codex finding 3: an unhandled exception logs its class and the request id, never the
exception body (SQLAlchemy puts the statement and the bound parameters in it)."""

from __future__ import annotations

import logging

from sqlalchemy.exc import DataError

from backend.api import sessions
from backend.tests.api.conftest import API

RECORD_FIELDS = {"birth_date": "1985-07-03", "phone_e164": "+15555550100", "address_line": "100 Placeholder St"}


def test_unhandled_exception_logs_class_and_request_id_only(client, monkeypatch, caplog):
    def explode(scenario_id: str):
        raise DataError("INSERT INTO normalized_record (...) VALUES (...)", RECORD_FIELDS, Exception("boom"))

    monkeypatch.setattr(sessions, "load_scenario", explode)
    with caplog.at_level(logging.DEBUG):
        r = client.post(f"{API}/sessions", json={"scenarioId": "hero"}, headers={"X-Request-Id": "req-log-test"})
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL"
    text = caplog.text
    assert "DataError" in text
    assert "req-log-test" in text
    for value in RECORD_FIELDS.values():
        assert value not in text, f"bound parameter {value!r} reached the log"
    assert "INSERT INTO" not in text
    assert "Traceback" not in text
