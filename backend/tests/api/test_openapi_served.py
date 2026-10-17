"""The served /openapi.json documents every frozen route exactly as the committed snapshot does:
the same response statuses and the same query parameters (names, order, schemas). Real routes copy
their stub's metadata by hand (backend/app/openapi_meta.py), so this catches drift after a contract merge."""

from __future__ import annotations

import json
from pathlib import Path

from backend.app.main import app

SNAPSHOT = Path(__file__).resolve().parents[3] / "contracts" / "openapi.json"


def _params(op: dict) -> list:
    return [(p["name"], p["in"], p["schema"]) for p in op.get("parameters", [])]


def test_served_routes_match_the_snapshot():
    served = app.openapi()["paths"]
    frozen = json.loads(SNAPSHOT.read_text())["paths"]
    drift = []
    for path, ops in frozen.items():
        for method, op in ops.items():
            live = served.get(path, {}).get(method)
            if live is None:
                drift.append(f"{method.upper()} {path}: not served")
                continue
            if sorted(op["responses"]) != sorted(live["responses"]):
                drift.append(
                    f"{method.upper()} {path}: responses {sorted(op['responses'])} != {sorted(live['responses'])}"
                )
            if _params(op) != _params(live):
                drift.append(f"{method.upper()} {path}: parameters differ")
    assert drift == [], "\n".join(drift)
