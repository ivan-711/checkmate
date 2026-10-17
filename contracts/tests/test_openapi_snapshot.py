"""The committed openapi.json is current and carries the 12 frozen routes with their rules."""
import json

from fastapi.testclient import TestClient

from contracts.api_spec import build_app
from contracts.build_openapi import FROZEN_PATHS, SNAPSHOT, render

LIST_ROUTES = {"/api/v1/candidate-pairs"}
IDEMPOTENT_POSTS = {"/api/v1/candidate-pairs/{pair_id}/reviews", "/api/v1/intake-sessions/{session_id}/turns"}


def test_snapshot_is_current():
    assert SNAPSHOT.exists(), "run python -m contracts.build_openapi"
    assert SNAPSHOT.read_text() == render()


def test_frozen_paths_and_rules():
    spec = json.loads(SNAPSHOT.read_text())
    assert set(FROZEN_PATHS) <= set(spec["paths"])
    for path in LIST_ROUTES:
        names = {p["name"] for p in spec["paths"][path]["get"]["parameters"]}
        assert {"limit", "cursor"} <= names, path
    for path in IDEMPOTENT_POSTS:
        names = {p["name"] for p in spec["paths"][path]["post"]["parameters"]}
        assert "Idempotency-Key" in names, path
    for path, item in spec["paths"].items():
        for op in item.values():
            assert "description" in op and "Lane" in op["description"], (path, "every endpoint names its lane")


def test_stub_returns_envelope_501_and_request_validation_422():
    client = TestClient(build_app())
    r = client.get("/api/v1/candidate-pairs")
    assert r.status_code == 501 and r.json()["error"]["code"] == "NOT_IMPLEMENTED"
    r = client.post("/api/v1/candidate-pairs/00000000-0000-4000-8000-000000000001/reviews",
                    json={"action": "APPROVE", "actor": "registrar:Registrar A"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"  # missing Idempotency-Key
    r = client.get("/api/v1/candidate-pairs?limit=1000")
    assert r.status_code == 422
    # a model_validator ValueError (REJECT without reasonCode) must be a 422 envelope, never a 500
    r = client.post("/api/v1/candidate-pairs/00000000-0000-4000-8000-000000000001/reviews",
                    headers={"Idempotency-Key": "11111111-1111-4111-8111-111111111111"},
                    json={"action": "REJECT", "actor": "registrar:Registrar A", "reasonCode": None})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    r = client.post("/api/v1/sessions", content=b"\xff", headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"  # malformed body
    r = client.get("/api/v1/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    r = client.delete("/api/v1/candidate-pairs")
    assert r.status_code == 405 and r.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
