"""R3b re-review of PR #3 at f8f12b2: the AlreadyLinked refusal (52cafb9) through W3a's real review route,
and the served OpenAPI of the three W3b routes against the frozen contract.

A-B and B-C approved puts A and C in one entity through other approvals. A DIFFERENT_PERSON reject of A-C
must be refused with 409 CANNOT_LINK_CONFLICT and write nothing; INSUFFICIENT_EVIDENCE must still work.
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from backend.tests.conftest import purge
from backend.tests.link.test_delta_r3b import ALLERGY_ROW, T0, bundle, order, proposed_pair, record, review
from contracts.models.common import SourceKind


@pytest.fixture
def app_client(engine, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app import main
    monkeypatch.setattr(main.app.state, "engine", engine)
    return TestClient(main.app)


@pytest.fixture
def chain(engine):
    """A (clinic allergy, earliest), B (ER order), C (ER plain); pairs A-B, B-C, A-C all PROPOSED; committed."""
    with engine.begin() as c:
        a = record(c, system="CLINIC_CSV", local_id=f"C-{uuid4().hex[:8]}", kind=SourceKind.CSV_ROW,
                   payload={"Id": "p", "allergies": [ALLERGY_ROW], "medications": [], "encounters": []}, at=T0)
        b = record(c, system="ER_FHIR", local_id=f"ER-{uuid4().hex[:8]}", kind=SourceKind.FHIR_PATIENT, payload=bundle(order()),
                   at=T0 + timedelta(minutes=1), constructed=True)
        cc = record(c, system="ER_FHIR", local_id=f"ER-{uuid4().hex[:8]}", kind=SourceKind.FHIR_PATIENT, payload=bundle(),
                    at=T0 + timedelta(minutes=2))
        pairs = {"ab": proposed_pair(c, a, b), "bc": proposed_pair(c, b, cc), "ac": proposed_pair(c, a, cc)}
    try:
        yield a, b, cc, pairs
    finally:
        purge(engine, [a, b, cc])


def scalar(engine, sql: str, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).scalar()


def snapshot(client, engine, entity_id: str, pair_id: UUID) -> dict:
    return {
        "entity": client.get(f"/api/v1/entities/{entity_id}").json(),
        "alerts": client.get("/api/v1/alerts", params={"entityId": entity_id}).json()["items"],
        "timeline": client.get(f"/api/v1/entities/{entity_id}/timeline").json()["items"],
        "alert_rows": scalar(engine, "SELECT count(*) FROM safety_alert WHERE entity_id = :e", e=entity_id),
        "decision": scalar(engine, "SELECT max(version) || ':' || (SELECT status FROM match_decision WHERE pair_id = :p "
                                   "ORDER BY version DESC LIMIT 1) FROM match_decision WHERE pair_id = :p", p=pair_id),
    }


def test_different_person_reject_of_already_linked_records_is_refused_and_writes_nothing(app_client, engine, chain):
    a, _b, cc, pairs = chain
    entity_id = review(app_client, pairs["ab"], {"action": "APPROVE", "actor": "Registrar A"}).json()["entity"]["id"]
    after_bc = review(app_client, pairs["bc"], {"action": "APPROVE", "actor": "Registrar A"}).json()
    assert after_bc["entity"]["id"] == entity_id and len(after_bc["entity"]["members"]) == 3
    before = snapshot(app_client, engine, entity_id, pairs["ac"])
    assert before["decision"] == "1:PROPOSED" and before["alert_rows"] == 1 and len(before["alerts"]) == 1
    events_before = scalar(engine, "SELECT count(*) FROM event_log WHERE pair_id = :p OR entity_id = :e", p=pairs["ac"], e=entity_id)

    key = str(uuid4())
    r = review(app_client, pairs["ac"], {"action": "REJECT", "actor": "Registrar B", "reasonCode": "DIFFERENT_PERSON",
                                         "note": "different people"}, key=key)
    assert r.status_code == 409, r.text
    assert r.headers.get("X-Request-Id")
    error = r.json()["error"]
    assert error["code"] == "CANNOT_LINK_CONFLICT"
    for rid in (a, cc, entity_id, pairs["ac"]):
        assert str(rid) not in error["message"], "no record, entity or pair ids in the client message"

    # nothing written: no not_a_match, decision still v1 PROPOSED, no event, no stored idempotent response
    assert scalar(engine, "SELECT count(*) FROM not_a_match WHERE record_a_id = ANY(:ids) OR record_b_id = ANY(:ids)",
                  ids=[a, cc]) == 0
    assert snapshot(app_client, engine, entity_id, pairs["ac"]) == before, "entity, alert, timeline and decision unchanged"
    assert scalar(engine, "SELECT count(*) FROM event_log WHERE pair_id = :p OR entity_id = :e",
                  p=pairs["ac"], e=entity_id) == events_before
    assert scalar(engine, "SELECT count(*) FROM idempotency_record WHERE key = :k", k=key) == 0
    # a retry with the same key is refused the same way (no half-stored claim)
    again = review(app_client, pairs["ac"], {"action": "REJECT", "actor": "Registrar B", "reasonCode": "DIFFERENT_PERSON",
                                             "note": "different people"}, key=key)
    assert again.status_code == 409 and again.json()["error"]["code"] == "CANNOT_LINK_CONFLICT"
    # a later approve inside the entity is not poisoned by a stray not_a_match row
    ok = review(app_client, pairs["ac"], {"action": "APPROVE", "actor": "Registrar A"})
    assert ok.status_code == 201, ok.text
    assert ok.json()["entity"]["id"] == entity_id and [x["id"] for x in ok.json()["alerts"]] == [x["id"] for x in before["alerts"]]


def test_insufficient_evidence_reject_of_already_linked_records_is_unaffected(app_client, engine, chain):
    a, _b, cc, pairs = chain
    entity_id = review(app_client, pairs["ab"], {"action": "APPROVE", "actor": "Registrar A"}).json()["entity"]["id"]
    review(app_client, pairs["bc"], {"action": "APPROVE", "actor": "Registrar A"})
    before = snapshot(app_client, engine, entity_id, pairs["ac"])
    r = review(app_client, pairs["ac"], {"action": "REJECT", "actor": "Registrar B", "reasonCode": "INSUFFICIENT_EVIDENCE"})
    assert r.status_code == 201, r.text
    assert r.json()["decision"]["status"] == "REJECTED" and r.json()["decision"]["version"] == 2
    assert r.json()["entity"] is None and r.json()["alerts"] == []
    assert scalar(engine, "SELECT count(*) FROM not_a_match WHERE record_a_id = ANY(:ids) OR record_b_id = ANY(:ids)",
                  ids=[a, cc]) == 0
    after = snapshot(app_client, engine, entity_id, pairs["ac"])
    assert after["decision"] == "2:REJECTED"
    assert {k: v for k, v in after.items() if k != "decision"} == {k: v for k, v in before.items() if k != "decision"}
    assert scalar(engine, "SELECT count(*) FROM event_log WHERE pair_id = :p AND event_type = 'LINK_REJECTED'", p=pairs["ac"]) == 1


def test_different_person_reject_across_separate_entities_still_writes_not_a_match(app_client, engine, chain):
    """The refusal is only for records that already share an entity: one linked record against an unlinked one
    is the ordinary reject and must keep writing not_a_match."""
    a, b, cc, pairs = chain
    review(app_client, pairs["ab"], {"action": "APPROVE", "actor": "Registrar A"})
    r = review(app_client, pairs["bc"], {"action": "REJECT", "actor": "Registrar B", "reasonCode": "DIFFERENT_PERSON"})
    assert r.status_code == 201, r.text
    lo, hi = sorted([b, cc])
    assert scalar(engine, "SELECT count(*) FROM not_a_match WHERE record_a_id = :lo AND record_b_id = :hi", lo=lo, hi=hi) == 1
    assert scalar(engine, "SELECT count(*) FROM entity_member WHERE source_record_id = :c", c=cc) == 0
    assert a  # A stays linked to B; nothing else to assert about it here


def test_same_state_approve_returns_the_entitys_alerts(app_client, chain):
    """W3a seam (not in the W3b diff): a second Approve click with a fresh key answers 200 SAME_STATE with the
    entity. The flag card reads ``alerts`` from the same response, so it should carry the entity's alerts too."""
    _a, _b, _cc, pairs = chain
    first = review(app_client, pairs["ab"], {"action": "APPROVE", "actor": "Registrar A"}).json()
    second = review(app_client, pairs["ab"], {"action": "APPROVE", "actor": "Registrar A"})
    assert second.status_code == 200
    assert second.json()["entity"]["id"] == first["entity"]["id"]
    assert [x["id"] for x in second.json()["alerts"]] == [x["id"] for x in first["alerts"]]


# Served OpenAPI against the frozen contract ------------------------------------------------------

def _refs(node, out: set[str]) -> set[str]:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            out.add(ref.rsplit("/", 1)[-1])
        for v in node.values():
            _refs(v, out)
    elif isinstance(node, list):
        for v in node:
            _refs(v, out)
    return out


def _without_prose(node):
    """Descriptions and summaries are free text; everything else (params, responses, schemas) must match."""
    if isinstance(node, dict):
        return {k: _without_prose(v) for k, v in node.items() if k not in ("description", "summary")}
    if isinstance(node, list):
        return [_without_prose(v) for v in node]
    return node


def test_served_openapi_matches_the_frozen_contract_on_the_three_w3b_routes(app_client):
    served = app_client.get("/openapi.json").json()
    frozen = json.loads((Path(__file__).resolve().parents[3] / "contracts" / "openapi.json").read_text())
    for path in ("/api/v1/entities/{entity_id}", "/api/v1/entities/{entity_id}/timeline", "/api/v1/alerts"):
        assert _without_prose(served["paths"][path]) == _without_prose(frozen["paths"][path]), path
        # every schema those routes reach is the same too (closure over $ref)
        seen: set[str] = set()
        todo = _refs(served["paths"][path], set())
        while todo:
            name = todo.pop()
            if name in seen:
                continue
            seen.add(name)
            assert _without_prose(served["components"]["schemas"][name]) == _without_prose(
                frozen["components"]["schemas"][name]), (path, name)
            todo |= _refs(served["components"]["schemas"][name], set()) - seen
        assert "503" in served["paths"][path]["get"]["responses"], path
