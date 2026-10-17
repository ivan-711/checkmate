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
        r = TestClient(main.app).post(
            f"/api/v1/candidate-pairs/{pair}/reviews",
            headers={"Idempotency-Key": str(uuid4())},
            json={"action": "APPROVE", "actor": "Registrar A"},
        )
        assert r.status_code == 409 and r.headers.get("X-Request-Id")
        error = r.json()["error"]
        assert error["code"] == "CANNOT_LINK_CONFLICT"
        assert str(clinic) not in error["message"] and str(er) not in error["message"], "no record ids in the message"
        with engine.connect() as c:
            version = c.execute(
                text("SELECT max(version) FROM match_decision WHERE pair_id = :p"), {"p": pair}
            ).scalar()
        assert version == 1, "the LINKED decision rolled back with the refusal"
    finally:
        purge(engine, [clinic, er])


def test_different_person_reject_of_already_linked_records_is_409_and_writes_nothing(engine, monkeypatch):
    """Lead decision on the second-layer review: A-B and B-C approved, A-C rejected DIFFERENT_PERSON
    through the real review route -> 409 CANNOT_LINK_CONFLICT; no decision, no not_a_match; entity and
    alert untouched. Undoing an approved link is a split (lane Q4)."""
    from datetime import timedelta

    from fastapi.testclient import TestClient

    from backend.app import main
    from backend.golden.service import read_alerts, read_entity
    from backend.link.service import apply_approve
    from backend.tests.link.seed import T0, insert_record, linked_pair, rows_touching
    from contracts.models.common import SourceKind

    monkeypatch.setattr(main.app.state, "engine", engine)
    with engine.begin() as c:
        a, cc = hero_records(c)
        b = insert_record(
            c,
            system="ER_FHIR",
            local_id="ER-MRN-B",
            kind=SourceKind.FHIR_PATIENT,
            raw_payload={"resourceType": "Patient", "id": "b"},
            ingested_at=T0 + timedelta(minutes=5),
        )
        apply_approve(c, *linked_pair(c, a, b))
        entity, alerts = apply_approve(c, *linked_pair(c, b, cc))
        shortcut = insert_pair(c, a, cc)
        insert_decision(c, shortcut, 1, DecisionStatus.PROPOSED, actor="system:scorer", actor_type="SYSTEM")
    try:
        r = TestClient(main.app).post(
            f"/api/v1/candidate-pairs/{shortcut}/reviews",
            headers={"Idempotency-Key": str(uuid4())},
            json={"action": "REJECT", "actor": "Registrar A", "reasonCode": "DIFFERENT_PERSON"},
        )
        assert r.status_code == 409, r.text
        error = r.json()["error"]
        assert (
            error["code"] == "CANNOT_LINK_CONFLICT"
            and "already linked through another approved link" in error["message"]
        )
        with engine.connect() as c:
            assert (
                c.execute(text("SELECT max(version) FROM match_decision WHERE pair_id = :p"), {"p": shortcut}).scalar()
                == 1
            )
            assert rows_touching(c, "not_a_match", [a, b, cc]) == 0
            after = read_entity(c, entity.id)
            assert (after.id, after.version, {m.source_record_id for m in after.members}) == (
                entity.id,
                entity.version,
                {m.source_record_id for m in entity.members},
            )
            assert [(x.id, x.status) for x in read_alerts(c, entity.id)] == [(x.id, x.status) for x in alerts]
    finally:
        purge(engine, [a, b, cc])
