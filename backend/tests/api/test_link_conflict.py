"""Architecture §7 cross-cluster check (lead decision 14:28): an approve that would cross a
not_a_match row of ANOTHER pair is 409 CANNOT_LINK_CONFLICT; the pair's own superseded row is
not a conflict. Control characters in note or actor are refused at the boundary with 422."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from backend.api.sessions import insert_source_card
from backend.match.seam import resolve_core
from backend.tests.api.conftest import API, approve_body, engine, reject_body, review
from contracts.models.records import SourceCard


def _pair_between(pairs: list[dict], x: str, y: str) -> dict:
    a, b = sorted((x, y))
    return next(p for p in pairs if p["recordAId"] == a and p["recordBId"] == b)


def test_approve_crossing_another_pairs_not_a_match_is_409_cannot_link_conflict(client, session, db_conn):
    # Three records in one DOB block: ER (a), Clinic (b) and a Clinic variant (c).
    er, clinic = (SourceCard.model_validate(s) for s in session["sources"][:2])
    rid = uuid.uuid4()
    variant = SourceCard(
        record=clinic.record.model_copy(update={"id": rid, "source_local_id": f"VARIANT-{rid.hex[:6]}"}),
        normalized=clinic.normalized.model_copy(update={"record_id": rid, "given_name": "Variant"}),
        display_label=clinic.display_label,
    )
    with engine.begin() as conn:
        insert_source_card(conn, variant, resolve_core())
    assert client.post(f"{API}/match-runs").status_code == 201
    pairs = client.get(f"{API}/candidate-pairs", params={"limit": 200}).json()["items"]
    a, b, c = str(er.record.id), str(clinic.record.id), str(rid)
    ab, ac = _pair_between(pairs, a, b), _pair_between(pairs, a, c)

    # The registrar said a and c are different people.
    assert review(client, ac["id"], reject_body("DIFFERENT_PERSON")).status_code == 201
    # b and c already belong to one entity (what W3b's union-find produces after a link).
    entity_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO entity (id) VALUES (:e)"), {"e": entity_id})
        for r in (b, c):
            conn.execute(
                text("INSERT INTO entity_member (entity_id, source_record_id) VALUES (:e, :r)"),
                {"e": entity_id, "r": r},
            )

    # Linking a to b would put a and c in one entity, crossing the a-c decision.
    r = review(client, ab["id"], approve_body())
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "CANNOT_LINK_CONFLICT"
    versions = (
        db_conn.execute(text("SELECT status FROM match_decision WHERE pair_id = :p ORDER BY version"), {"p": ab["id"]})
        .scalars()
        .all()
    )
    assert versions == ["PROPOSED"], "a refused approve writes nothing"
    assert db_conn.execute(text("SELECT count(*) FROM not_a_match")).scalar_one() == 1, "the a-c row stays"


def test_control_characters_in_actor_or_note_are_422_at_the_boundary(client, pair_id, db_conn):
    for body in (
        reject_body("INSUFFICIENT_EVIDENCE", note="hello\x00world"),
        approve_body(actor="Registrar\x1bA"),
        approve_body(note="line\x07bell"),
    ):
        r = review(client, pair_id, body)
        assert r.status_code == 422, r.text
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert review(client, pair_id, approve_body(note="tabs\tand\nnewlines are fine")).status_code == 201
    assert (
        db_conn.execute(text("SELECT max(version) FROM match_decision WHERE pair_id = :p"), {"p": pair_id}).scalar_one()
        == 2
    )
