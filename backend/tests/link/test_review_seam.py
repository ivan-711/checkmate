"""The link seam behind W3a's real review route: what the registrar's client sees when the
service refuses a link."""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text

from backend.link.service import CannotLinkConflict
from backend.tests.conftest import purge
from backend.tests.link.seed import hero_records, insert_decision, insert_pair
from contracts.models.common import DecisionStatus


def test_cannot_link_conflict_from_the_service_is_a_409_envelope_and_rolls_back(engine, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.api import reviews
    from backend.app import main

    monkeypatch.setattr(main.app.state, "engine", engine)
    with engine.begin() as c:
        clinic, er = hero_records(c)
        pair = insert_pair(c, clinic, er)
        insert_decision(c, pair, 1, DecisionStatus.PROPOSED, actor="system:scorer", actor_type="SYSTEM")

    def refuse(conn, pair_id, decision_id):  # the service's own not_a_match check firing inside the route
        raise CannotLinkConflict(f"not_a_match inside the would-be entity: {clinic} {er}")

    monkeypatch.setattr(reviews.link, "apply_approve", refuse)
    try:
        r = TestClient(main.app).post(f"/api/v1/candidate-pairs/{pair}/reviews",
                                      headers={"Idempotency-Key": str(uuid4())},
                                      json={"action": "APPROVE", "actor": "Registrar A"})
        assert r.status_code == 409 and r.headers.get("X-Request-Id")
        error = r.json()["error"]
        assert error["code"] == "CANNOT_LINK_CONFLICT"
        assert str(clinic) not in error["message"] and str(er) not in error["message"], "no record ids in the message"
        with engine.connect() as c:
            version = c.execute(text("SELECT max(version) FROM match_decision WHERE pair_id = :p"), {"p": pair}).scalar()
        assert version == 1, "the LINKED decision rolled back with the refusal"
    finally:
        purge(engine, [clinic, er])
