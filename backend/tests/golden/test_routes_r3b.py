"""R3b reviewer tests for the W3b routes: failure modes and the error envelope (checklist 8, 11, 16)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from backend.app.db import make_engine


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app import main

    return TestClient(main.app, raise_server_exceptions=False), main, monkeypatch


def test_database_down_answers_upstream_unavailable_with_a_request_id(client):
    """W3a's composition root maps a database outage to 503 UPSTREAM_UNAVAILABLE (the brief's error table)."""
    tc, main, monkeypatch = client
    # port 1 on loopback: refused at once, no timeout wait
    monkeypatch.setattr(main.app.state, "engine", make_engine("postgresql://x:x@127.0.0.1:1/x"))
    for path in (
        f"/api/v1/entities/{uuid4()}",
        f"/api/v1/entities/{uuid4()}/timeline",
        f"/api/v1/alerts?entityId={uuid4()}",
    ):
        r = tc.get(path)
        assert r.status_code == 503, path
        assert r.headers.get("X-Request-Id"), path
        body = r.json()
        assert body["error"]["code"] == "UPSTREAM_UNAVAILABLE", body
        assert "127.0.0.1" not in body["error"]["message"] and "x:x@" not in body["error"]["message"], (
            "no connection detail leaks"
        )


def test_bad_status_filter_is_a_validation_error_envelope(client):
    tc, _, _ = client
    r = tc.get(f"/api/v1/alerts?entityId={uuid4()}&status=RED")
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    r = tc.get(f"/api/v1/entities/{uuid4()}/timeline?limit=0")
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
