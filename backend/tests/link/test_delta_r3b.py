"""R3b re-review of PR #3 after integration (159edfd): the W3b seam behind W3a's real review route.

Everything here goes through POST /candidate-pairs/{id}/reviews, GET /entities/{id} and GET /alerts
on the composed app, with committed rows that each test purges. Own seed; the builder's is not imported.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from backend.link.service import apply_approve, apply_split
from backend.tests.conftest import purge
from contracts.models.common import ReasonCode, SourceKind

T0 = datetime(2026, 10, 17, 18, 0, tzinfo=UTC)
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
SNOMED = "http://snomed.info/sct"
SNAPSHOT = json.dumps({"features": {}, "rawScore": 1.0, "cLow": 0.0, "cHigh": 2.0})

GIVEN, FAMILY_CSV, FAMILY_ER = "Zuleima", "Quintanilla Ortez", "Quintanilla-Ortez"
DOB_CSV, DOB_ER, PHONE, ADDRESS = "1979-04-11", "1979-11-04", "+15555550142", "77 Juniper Hollow Rd"
NOTE = "patient said her mother has the same name"
ALLERGY_ROW = {"START": "2024-03-02", "STOP": "", "PATIENT": "p", "ENCOUNTER": "e", "CODE": "7984", "SYSTEM": "Unknown",
               "DESCRIPTION": "Penicillin V", "TYPE": "allergy", "CATEGORY": "medication", "REACTION1": "39579001",
               "DESCRIPTION1": "Anaphylaxis (disorder)", "SEVERITY1": "SEVERE", "REACTION2": "", "DESCRIPTION2": "",
               "SEVERITY2": ""}
# Strings that belong to the records and must never reach event_log
RECORD_STRINGS = (GIVEN, FAMILY_CSV, FAMILY_ER, DOB_CSV, DOB_ER, PHONE, ADDRESS, "Juniper", "Anaphylaxis", "anaphylaxis",
                  "Penicillin", "penicillin V", "Amoxicillin", "amoxicillin", "REACTION1", "resourceType", "raw_payload",
                  "Flagged for clinician review", "contraindicated", NOTE, "mother")


def order(rid: str = "mr-1") -> dict:
    return {"resourceType": "MedicationRequest", "id": rid, "status": "active", "intent": "order",
            "medicationCodeableConcept": {"coding": [{"system": RXNORM, "code": "308192", "display": "Amoxicillin 500 MG Oral Tablet"}]},
            "authoredOn": "2026-10-17T15:00:00Z",
            "meta": {"tag": [{"system": "urn:chartguard:provenance", "code": "constructed-scenario"}]}}


def bundle(*resources: dict) -> dict:
    return {"resourceType": "Bundle", "type": "transaction",
            "entry": [{"resource": {"resourceType": "Patient", "id": "p", "name": [{"given": [GIVEN], "family": FAMILY_ER}]}},
                      *({"resource": r} for r in resources)]}


def record(c, *, system: str, local_id: str, kind: SourceKind, payload: dict, at: datetime, constructed=False,
           family=FAMILY_CSV, dob=DOB_CSV) -> UUID:
    rid = uuid4()
    c.execute(text(
        "INSERT INTO source_record (id, source_system, source_local_id, kind, raw_payload, payload_sha256, is_constructed, ingested_at) "
        "VALUES (:id, :s, :l, :k, CAST(:p AS jsonb), :sha, :c, :at)"),
        {"id": rid, "s": system, "l": local_id, "k": kind.value, "p": json.dumps(payload), "sha": "0" * 64, "c": constructed, "at": at})
    c.execute(text(
        "INSERT INTO normalized_record (record_id, given_name, family_name, birth_date, sex, phone_e164, address_line) "
        "VALUES (:id, :g, :f, :d, 'female', :ph, :ad)"), {"id": rid, "g": GIVEN, "f": family, "d": dob, "ph": PHONE, "ad": ADDRESS})
    return rid


def proposed_pair(c, a: UUID, b: UUID) -> UUID:
    a, b = sorted([a, b])
    pid = uuid4()
    c.execute(text("INSERT INTO candidate_pair (id, record_a_id, record_b_id, origin) VALUES (:id, :a, :b, 'MATCH_RUN')"),
              {"id": pid, "a": a, "b": b})
    c.execute(text(
        "INSERT INTO match_decision (id, pair_id, version, logit, p, raw_score, band, evidence_snapshot, status, actor, actor_type, "
        "scorer_version, threshold_set_id) VALUES (:id, :p, 1, 1.0, 0.7, 1.0, 'REVIEW', CAST(:snap AS jsonb), 'PROPOSED', "
        "'system:scorer', 'SYSTEM', 'test-scorer', 'provisional-0')"), {"id": uuid4(), "p": pid, "snap": SNAPSHOT})
    return pid


@pytest.fixture
def app_client(engine, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app import main
    monkeypatch.setattr(main.app.state, "engine", engine)
    return TestClient(main.app)


@pytest.fixture
def hero(engine):
    """Clinic CSV allergy (ingested first) and ER FHIR constructed order, one PROPOSED pair, committed."""
    with engine.begin() as c:
        clinic = record(c, system="CLINIC_CSV", local_id=f"C-{uuid4().hex[:8]}", kind=SourceKind.CSV_ROW,
                        payload={"Id": "p", "FIRST": GIVEN, "allergies": [ALLERGY_ROW], "medications": [], "encounters": []}, at=T0)
        er = record(c, system="ER_FHIR", local_id=f"ER-{uuid4().hex[:8]}", kind=SourceKind.FHIR_PATIENT, payload=bundle(order()),
                    at=T0 + timedelta(minutes=1), constructed=True, family=FAMILY_ER, dob=DOB_ER)
        pid = proposed_pair(c, clinic, er)
    try:
        yield clinic, er, pid
    finally:
        purge(engine, [clinic, er])


def review(client, pid: UUID, body: dict, key: str | None = None):
    return client.post(f"/api/v1/candidate-pairs/{pid}/reviews", headers={"Idempotency-Key": key or str(uuid4())}, json=body)


def count(engine, sql: str, **params) -> int:
    with engine.connect() as c:
        return c.execute(text(sql), params).scalar()


def events_for(engine, record_ids, entity_ids=()) -> list[dict]:
    with engine.connect() as c:
        pairs = [r[0] for r in c.execute(text(
            "SELECT id FROM candidate_pair WHERE record_a_id = ANY(:ids) OR record_b_id = ANY(:ids)"), {"ids": list(record_ids)})]
        rows = c.execute(text(
            "SELECT event_type, actor, outcome, reason_code, versions::text AS versions, payload::text AS payload, "
            "coalesce(evidence_snapshot::text, '') AS snapshot FROM event_log WHERE pair_id = ANY(:p) OR entity_id = ANY(:e)"),
            {"p": pairs, "e": list(entity_ids)}).mappings().all()
    return [dict(r) for r in rows]


# Reject keeps the rule silent; not_a_match only for DIFFERENT_PERSON ---------------------------

@pytest.mark.parametrize("reason, writes_not_a_match", [("DIFFERENT_PERSON", 1), ("INSUFFICIENT_EVIDENCE", 0)])
def test_reject_through_the_route_keeps_the_rule_silent(app_client, engine, hero, reason, writes_not_a_match):
    clinic, er, pid = hero
    r = review(app_client, pid, {"action": "REJECT", "actor": "Registrar A", "reasonCode": reason, "note": NOTE})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["entity"] is None and body["alerts"] == []
    assert body["decision"]["status"] == "REJECTED" and body["decision"]["reasonCode"] == reason
    assert count(engine, "SELECT count(*) FROM entity_member WHERE source_record_id IN (:a, :b)", a=clinic, b=er) == 0
    assert count(engine, "SELECT count(*) FROM safety_alert WHERE allergy_record_id IN (:a, :b) OR order_record_id IN (:a, :b)",
                 a=clinic, b=er) == 0
    assert count(engine, "SELECT count(*) FROM not_a_match WHERE (record_a_id, record_b_id) IN ((:a, :b), (:b, :a))",
                 a=clinic, b=er) == writes_not_a_match
    types = sorted(e["event_type"] for e in events_for(engine, [clinic, er]))
    assert types == ["LINK_REJECTED"], "a reject writes its own event and nothing from the link or the rule"
    # the alerts route agrees: nothing anywhere for these records
    all_alerts = app_client.get("/api/v1/alerts", params={"limit": 200}).json()["items"]
    assert not [a for a in all_alerts if a["allergyRef"]["sourceRecordId"] in (str(clinic), str(er))]


# Approve, reload, retry: same golden record and the same alert --------------------------------

def test_reload_after_approval_returns_the_same_golden_record_and_alert(app_client, engine, hero):
    _, _, pid = hero
    key = str(uuid4())
    r = review(app_client, pid, {"action": "APPROVE", "actor": "Registrar A"}, key=key)
    assert r.status_code == 201, r.text
    approved = r.json()
    entity_id = approved["entity"]["id"]
    (alert,) = approved["alerts"]
    assert alert["tier"] == "A" and alert["status"] == "PRELIMINARY" and alert["revealedByMerge"] is True

    first = app_client.get(f"/api/v1/entities/{entity_id}").json()
    second = app_client.get(f"/api/v1/entities/{entity_id}").json()
    assert first == second == approved["entity"], "a read-time golden record is a pure function of the members"
    alerts1 = app_client.get("/api/v1/alerts", params={"entityId": entity_id}).json()["items"]
    alerts2 = app_client.get("/api/v1/alerts", params={"entityId": entity_id}).json()["items"]
    assert alerts1 == alerts2 == [alert]

    # retry with the same key: the stored response, byte for byte
    again = review(app_client, pid, {"action": "APPROVE", "actor": "Registrar A"}, key=key)
    assert again.status_code == 201 and again.json() == approved
    # a second click with a fresh key: same state, no new alert, no new entity version
    fresh = review(app_client, pid, {"action": "APPROVE", "actor": "Registrar A"})
    assert fresh.status_code == 200, fresh.text
    assert app_client.get(f"/api/v1/entities/{entity_id}").json() == first
    assert app_client.get("/api/v1/alerts", params={"entityId": entity_id}).json()["items"] == [alert]
    assert count(engine, "SELECT count(*) FROM safety_alert WHERE entity_id = :e", e=entity_id) == 1


def test_swapped_dob_golden_is_conflict_unresolved_with_both_alternates(app_client, hero):
    _, _, pid = hero
    entity = review(app_client, pid, {"action": "APPROVE", "actor": "Registrar A"}).json()["entity"]
    golden = {g["field"]: g for g in entity["golden"] if g["rule"] != "UNION"}
    dob = golden["birthDate"]
    assert dob["rule"] == "CONFLICT_UNRESOLVED" and dob["value"] is None
    assert sorted(a["value"] for a in dob["alternates"]) == sorted([DOB_CSV, DOB_ER])
    assert {a["crosswalk"]["sourceSystem"] for a in dob["alternates"]} == {"CLINIC_CSV", "ER_FHIR"}
    for g in entity["golden"]:
        assert g["crosswalk"]["sourceSystem"] and g["crosswalk"]["sourceRecordId"], g


# Event payloads never carry whole records ----------------------------------------------------

def test_no_event_written_by_approve_reject_or_split_carries_record_content(app_client, engine, hero):
    clinic, er, pid = hero
    approved = review(app_client, pid, {"action": "APPROVE", "actor": "Registrar A", "note": NOTE}).json()
    entity_id = approved["entity"]["id"]
    with engine.begin() as c:
        result = apply_split(c, UUID(entity_id), [er], actor="registrar:Registrar B", reason_code=ReasonCode.DIFFERENT_PERSON,
                             note=NOTE)
    entity_ids = [entity_id, *(str(e.id) for e in result.entities)]
    rows = events_for(engine, [clinic, er], entity_ids)
    assert {"LINK_APPROVED", "ENTITY_MERGED", "ALERT_RAISED", "LINK_REVOKED", "ENTITY_SPLIT", "ALERT_RETRACTED"} <= {
        r["event_type"] for r in rows}
    for row in rows:
        blob = " ".join(str(v) for v in row.values())
        for s in RECORD_STRINGS:
            assert s not in blob, (row["event_type"], s, blob)
        payload = json.loads(row["payload"])
        assert all(not isinstance(v, str) or len(v) <= 64 for v in payload.values()), row


# Limits and the CSV order adapter ------------------------------------------------------------

def test_limit_over_the_max_is_a_validation_envelope(app_client, hero):
    _, _, pid = hero
    entity_id = review(app_client, pid, {"action": "APPROVE", "actor": "Registrar A"}).json()["entity"]["id"]
    for path, params in ((f"/api/v1/entities/{entity_id}/timeline", {}), ("/api/v1/alerts", {"entityId": entity_id})):
        assert app_client.get(path, params={**params, "limit": 200}).status_code == 200
        r = app_client.get(path, params={**params, "limit": 201})
        assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR", path


def test_long_fhir_resource_id_does_not_break_the_approve(conn):
    """FHIR allows ids up to 64 characters; the ALERT_RAISED payload carries "AllergyIntolerance/<id>".
    W3a's writer refuses payload strings over 64 characters, so a legal id must not make the approve fail."""
    long_id = "a" * 64
    allergy = {"resourceType": "AllergyIntolerance", "id": long_id, "type": "allergy", "criticality": "high",
               "clinicalStatus": {"coding": [{"code": "active"}]}, "verificationStatus": {"coding": [{"code": "confirmed"}]},
               "code": {"coding": [{"system": RXNORM, "code": "7984", "display": "Penicillin V"}]},
               "recordedDate": "2024-03-02T10:00:00Z", "reaction": [{"severity": "severe",
               "manifestation": [{"coding": [{"system": SNOMED, "code": "39579001", "display": "Anaphylaxis"}]}]}]}
    a = record(conn, system="ER_FHIR", local_id="ER-long-a", kind=SourceKind.FHIR_PATIENT, payload=bundle(allergy), at=T0)
    b = record(conn, system="CLINIC_CSV", local_id="C-long-b", kind=SourceKind.CSV_ROW, at=T0 + timedelta(minutes=1),
               payload={"Id": "p", "medications": [{"START": "2026-10-01", "STOP": "", "CODE": "308192",
                                                    "DESCRIPTION": "Amoxicillin 500 MG Oral Tablet", "DISPENSES": "1"}]})
    pid = proposed_pair(conn, a, b)
    did = uuid4()
    conn.execute(text(
        "INSERT INTO match_decision (id, pair_id, version, logit, p, raw_score, band, evidence_snapshot, status, actor, actor_type, "
        "scorer_version, threshold_set_id) VALUES (:id, :p, 2, 1.0, 0.7, 1.0, 'REVIEW', CAST(:snap AS jsonb), 'LINKED', "
        "'registrar:Registrar A', 'REGISTRAR', 'test-scorer', 'provisional-0')"), {"id": did, "p": pid, "snap": SNAPSHOT})
    _entity, alerts = apply_approve(conn, pid, did)
    assert [x.tier.value for x in alerts] == ["A"]
    assert alerts[0].allergy_ref.resource_id == f"AllergyIntolerance/{long_id}"
