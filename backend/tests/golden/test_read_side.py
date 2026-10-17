"""read_entity, read_timeline and the routes, over the test database."""

from __future__ import annotations

from uuid import uuid4

import pytest

from backend.golden.service import read_entity, read_timeline
from backend.link.service import apply_approve
from backend.tests.conftest import purge
from backend.tests.link.seed import hero_records, linked_pair
from contracts.models.entities import TimelineVerification


def test_read_entity_golden_record_has_crosswalks_and_clinical_union(conn):
    clinic, er = hero_records(conn)
    entity, _ = apply_approve(conn, *linked_pair(conn, clinic, er))
    g = {f.field: f for f in entity.golden if f.rule != "UNION"}
    assert g["givenName"].value == "Ana" and g["givenName"].rule == "MOST_FREQUENT"
    assert g["familyName"].value == "Placeholder-Family" and g["familyName"].rule == "MOST_RECENT"
    assert (
        g["familyName"].crosswalk.source_record_id == "ER-MRN-1"
        and g["familyName"].alternates[0].value == "Placeholder Family"
    )
    assert g["birthDate"].rule == "MAJORITY" and g["phone"].rule == "MOST_RECENT"
    union = [f for f in entity.golden if f.rule == "UNION"]
    assert {(f.field, f.value["code"], f.crosswalk.source_system) for f in union} == {
        ("allergy", "7984", "CLINIC_CSV"),
        ("activeMedicationOrder", "308192", "ER_FHIR"),
    }
    assert read_entity(conn, uuid4()) is None


def test_timeline_keeps_source_verification_and_constructed_flag_and_pages(conn):
    clinic, er = hero_records(conn)
    entity, _ = apply_approve(conn, *linked_pair(conn, clinic, er))
    page = read_timeline(conn, entity.id, limit=50, cursor=None)
    kinds = [(e.type, e.source_system, e.verification, e.is_constructed) for e in page.items]
    assert kinds == [
        ("ALLERGY", "CLINIC_CSV", TimelineVerification.CSV_DERIVED, False),
        ("ENCOUNTER", "CLINIC_CSV", TimelineVerification.CSV_DERIVED, False),
        ("ENCOUNTER", "ER_FHIR", TimelineVerification.CODED, True),
        ("MEDICATION_ORDER", "ER_FHIR", TimelineVerification.CODED, True),
    ]
    assert page.items[0].codes == ["RxNorm:7984"] and "anaphylaxis, severe" in page.items[0].display
    assert (
        page.items[-1].display == "Amoxicillin 500 MG Oral Tablet (active order)"
        and page.items[-1].resource_id == "MedicationRequest/mr-1"
    )
    first = read_timeline(conn, entity.id, limit=3, cursor=None)
    assert len(first.items) == 3 and first.next_cursor
    rest = read_timeline(conn, entity.id, limit=3, cursor=first.next_cursor)
    assert [e.resource_id for e in rest.items] == ["MedicationRequest/mr-1"] and rest.next_cursor is None
    assert read_timeline(conn, uuid4(), limit=5, cursor=None) is None


@pytest.fixture
def commit_hero(engine):
    """The routes read committed rows through the app's own pool: commit an approved hero pair
    (options as ``hero_records``) and purge everything it created afterwards."""
    made: list = []

    def make(**hero_options):
        with engine.begin() as c:
            clinic, er = hero_records(c, **hero_options)
            made.extend([clinic, er])
            pair, decision = linked_pair(c, clinic, er)
            entity, alerts = apply_approve(c, pair, decision)
        return entity, alerts, pair

    yield make
    purge(engine, made)


@pytest.fixture
def committed_entity(commit_hero):
    return commit_hero()


@pytest.fixture
def client(engine, monkeypatch):
    """The routes read through the module-level engine; point it at the test database explicitly."""
    from fastapi.testclient import TestClient

    from backend.app import main

    monkeypatch.setattr(main.app.state, "engine", engine)
    return TestClient(main.app)


def test_routes_entity_timeline_alerts(client, committed_entity):
    entity, _alerts, _ = committed_entity
    r = client.get(f"/api/v1/entities/{entity.id}")
    assert r.status_code == 200 and r.headers["X-Request-Id"]
    body = r.json()
    assert body["id"] == str(entity.id) and body["allLinksReviewerApproved"] is True
    assert {m["sourceSystem"] for m in body["members"]} == {"CLINIC_CSV", "ER_FHIR"}
    assert all("crosswalk" in g and g["crosswalk"]["sourceRecordId"] for g in body["golden"])
    t = client.get(f"/api/v1/entities/{entity.id}/timeline", params={"limit": 2})
    assert t.status_code == 200 and len(t.json()["items"]) == 2 and t.json()["nextCursor"]
    t2 = client.get(f"/api/v1/entities/{entity.id}/timeline", params={"limit": 2, "cursor": t.json()["nextCursor"]})
    assert t2.status_code == 200 and t2.json()["nextCursor"] is None
    a = client.get("/api/v1/alerts", params={"entityId": str(entity.id)})
    assert a.status_code == 200
    (card,) = a.json()["items"]
    assert card["tier"] == "A" and card["severity"] == "moderate" and card["status"] == "PRELIMINARY"
    assert card["cardText"].startswith("Flagged for clinician review.") and card["cardFooter"].startswith(
        "Rule BL-AMOX-01 v1."
    )
    assert card["citation"]["setId"] and card["constructedScenario"] is True
    assert (
        client.get("/api/v1/alerts", params={"entityId": str(entity.id), "status": "RETRACTED"}).json()["items"] == []
    )


def test_routes_404_use_the_error_envelope(client):
    r = client.get(f"/api/v1/entities/{uuid4()}")
    assert r.status_code == 404 and r.json() == {
        "error": {"code": "NOT_FOUND", "message": "entity not found", "details": None}
    }
    t = client.get(f"/api/v1/entities/{uuid4()}/timeline")
    assert t.status_code == 404 and t.json()["error"]["code"] == "NOT_FOUND"
    assert client.get("/api/v1/entities/not-a-uuid").status_code == 422


def test_routes_bad_cursor_and_limit_over_max_are_422(client, committed_entity):
    entity, _, _ = committed_entity
    bad = client.get(f"/api/v1/entities/{entity.id}/timeline", params={"cursor": "not-a-cursor"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "VALIDATION_ERROR"
    bad_alert = client.get("/api/v1/alerts", params={"entityId": str(entity.id), "cursor": str(uuid4())})
    assert bad_alert.status_code == 422
    # the brief (9238cc7) and the frozen schema: limit above LIST_LIMIT_MAX is a 422 at the boundary
    big = client.get(f"/api/v1/entities/{entity.id}/timeline", params={"limit": 201})
    assert big.status_code == 422 and big.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.get(f"/api/v1/entities/{entity.id}/timeline", params={"limit": 200}).status_code == 200
    over = client.get("/api/v1/alerts", params={"entityId": str(entity.id), "limit": 201})
    assert over.status_code == 422 and over.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.get("/api/v1/alerts", params={"entityId": str(entity.id), "limit": 200}).status_code == 200
    assert client.get("/api/v1/alerts", params={"entityId": str(uuid4())}).status_code == 404


def test_alert_cursor_survives_a_retraction_and_naive_timeline_cursor_is_422(client, committed_entity, engine):
    import base64

    from backend.golden.service import alert_page, read_alerts

    entity, alerts, _ = committed_entity
    page = alert_page(alerts, 1, None)
    assert page.items == alerts[:1] and page.next_cursor is None
    naive = base64.urlsafe_b64encode(b"2025-01-01T00:00:00|x|y").decode()
    r = client.get(f"/api/v1/entities/{entity.id}/timeline", params={"cursor": naive})
    assert r.status_code == 422
    with engine.connect() as c:
        assert read_alerts(c, entity.id)[0].id == alerts[0].id


# Swapped DOBs (the hero's day/month transposition): ADR-014 majority, else CONFLICT_UNRESOLVED ---

SWAPPED = {("1985-07-03", "CLINIC_CSV", "CLINIC-7"), ("1985-03-07", "ER_FHIR", "ER-MRN-1")}


def test_swapped_dobs_give_conflict_unresolved_with_both_values_and_their_crosswalks(conn):
    clinic, er = hero_records(conn, er_birth_date="1985-03-07")
    entity, _ = apply_approve(conn, *linked_pair(conn, clinic, er))
    golden = {g.field: g for g in entity.golden if g.rule != "UNION"}
    dob = golden["birthDate"]
    assert dob.value is None and dob.rule == "CONFLICT_UNRESOLVED"
    assert {(a.value, a.crosswalk.source_system, a.crosswalk.source_record_id) for a in dob.alternates} == SWAPPED
    assert (dob.crosswalk.source_system, dob.crosswalk.source_record_id) in {(s, r) for _, s, r in SWAPPED}
    assert golden["sex"].rule == "MAJORITY" and golden["sex"].value == "FEMALE", "only the DOB is in conflict"


def test_route_serializes_the_unresolved_dob_as_null_with_both_alternates(client, commit_hero):
    entity, _, _ = commit_hero(er_birth_date="1985-03-07")
    body = client.get(f"/api/v1/entities/{entity.id}").json()
    (dob,) = [g for g in body["golden"] if g["field"] == "birthDate"]
    assert "value" in dob and dob["value"] is None, "the null is sent, not dropped, so the UI can say why"
    assert dob["rule"] == "CONFLICT_UNRESOLVED"
    assert {
        (a["value"], a["crosswalk"]["sourceSystem"], a["crosswalk"]["sourceRecordId"]) for a in dob["alternates"]
    } == SWAPPED
