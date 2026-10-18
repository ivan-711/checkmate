"""R3b reviewer tests for the link lane (ADR-002, ADR-011, ADR-014, ADR-015), against the test database.

Own seed helpers; the builder's seed module is not imported.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from backend.golden.service import read_alerts, read_entity, read_timeline
from backend.link.service import CannotLinkConflict, LinkError, apply_approve, apply_reject, apply_split
from backend.tests.link.seed import rows_touching
from contracts.models.alerts import AlertStatus, AlertTier
from contracts.models.common import DecisionStatus, ReasonCode, SourceKind

T0 = datetime(2026, 10, 17, 18, 0, tzinfo=UTC)
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
SNOMED = "http://snomed.info/sct"
SNAPSHOT = json.dumps({"features": {}, "rawScore": 1.0, "cLow": 0.0, "cHigh": 2.0})

ALLERGY_ROW = {
    "START": "2024-03-02",
    "STOP": "",
    "PATIENT": "p",
    "ENCOUNTER": "e",
    "CODE": "7984",
    "SYSTEM": "Unknown",
    "DESCRIPTION": "Penicillin V",
    "TYPE": "allergy",
    "CATEGORY": "medication",
    "REACTION1": "39579001",
    "DESCRIPTION1": "Anaphylaxis (disorder)",
    "SEVERITY1": "SEVERE",
    "REACTION2": "",
    "DESCRIPTION2": "",
    "SEVERITY2": "",
}


def order(rid="mr-1", code="308192", display="Amoxicillin 500 MG Oral Tablet", status="active") -> dict:
    return {
        "resourceType": "MedicationRequest",
        "id": rid,
        "status": status,
        "intent": "order",
        "medicationCodeableConcept": {"coding": [{"system": RXNORM, "code": code, "display": display}]},
        "authoredOn": "2026-10-17T15:00:00Z",
        "meta": {"tag": [{"system": "urn:chartguard:provenance", "code": "constructed-scenario"}]},
    }


def bundle(*resources: dict) -> dict:
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [{"resource": {"resourceType": "Patient", "id": "p"}}, *({"resource": r} for r in resources)],
    }


def record(
    conn,
    *,
    system: str,
    local_id: str,
    kind: SourceKind,
    payload: dict,
    at: datetime,
    constructed=False,
    given="Ana",
    family="Placeholder",
    dob="1985-07-03",
    sex="FEMALE",
    phone="+15555550100",
) -> UUID:
    rid = uuid4()
    conn.execute(
        text(
            "INSERT INTO source_record (id, source_system, source_local_id, kind, raw_payload, payload_sha256, is_constructed, ingested_at) "
            "VALUES (:id, :s, :l, :k, CAST(:p AS jsonb), :sha, :c, :at)"
        ),
        {
            "id": rid,
            "s": system,
            "l": local_id,
            "k": kind.value,
            "p": json.dumps(payload),
            "sha": "0" * 64,
            "c": constructed,
            "at": at,
        },
    )
    conn.execute(
        text(
            "INSERT INTO normalized_record (record_id, given_name, family_name, birth_date, sex, phone_e164) "
            "VALUES (:id, :g, :f, :d, :x, :ph)"
        ),
        {"id": rid, "g": given, "f": family, "d": dob, "x": sex, "ph": phone},
    )
    return rid


def pair(conn, a: UUID, b: UUID) -> UUID:
    a, b = sorted([a, b])
    pid = uuid4()
    conn.execute(
        text("INSERT INTO candidate_pair (id, record_a_id, record_b_id, origin) VALUES (:id, :a, :b, 'MATCH_RUN')"),
        {"id": pid, "a": a, "b": b},
    )
    return pid


def decision(
    conn,
    pair_id: UUID,
    status: DecisionStatus,
    *,
    actor="registrar:Registrar A",
    actor_type="REGISTRAR",
    reason: str | None = None,
    band="REVIEW",
) -> UUID:
    version = conn.execute(
        text("SELECT coalesce(max(version), 0) + 1 FROM match_decision WHERE pair_id = :p"), {"p": pair_id}
    ).scalar()
    did = uuid4()
    conn.execute(
        text(
            "INSERT INTO match_decision (id, pair_id, version, logit, p, raw_score, band, evidence_snapshot, status, actor, actor_type, "
            "reason_code, scorer_version, threshold_set_id) VALUES (:id, :p, :v, 1.0, 0.7, 1.0, :band, CAST(:snap AS jsonb), :st, :actor, "
            ":at, :reason, 'test-scorer', 'provisional-0')"
        ),
        {
            "id": did,
            "p": pair_id,
            "v": version,
            "band": band,
            "snap": SNAPSHOT,
            "st": status.value,
            "actor": actor,
            "at": actor_type,
            "reason": reason,
        },
    )
    return did


def approved(conn, a: UUID, b: UUID, **kw):
    """PROPOSED then LINKED, as the review endpoint leaves them; returns (pair_id, linked decision id)."""
    pid = pair(conn, a, b)
    decision(conn, pid, DecisionStatus.PROPOSED, actor="system:scorer", actor_type="SYSTEM")
    return pid, decision(conn, pid, DecisionStatus.LINKED, **kw)


def hero(conn, *, minutes=0):
    clinic = record(
        conn,
        system="CLINIC_CSV",
        local_id="C-7",
        kind=SourceKind.CSV_ROW,
        payload={"Id": "p", "allergies": [ALLERGY_ROW], "medications": [], "encounters": []},
        at=T0 + timedelta(minutes=minutes),
    )
    er = record(
        conn,
        system="ER_FHIR",
        local_id="ER-1",
        kind=SourceKind.FHIR_PATIENT,
        payload=bundle(order()),
        at=T0 + timedelta(minutes=minutes + 1),
        constructed=True,
        family="Placeholder-Family",
    )
    return clinic, er


def plain(conn, i: int, minutes: int, **kw) -> UUID:
    return record(
        conn,
        system="ER_FHIR",
        local_id=f"R{i}",
        kind=SourceKind.FHIR_PATIENT,
        payload={"resourceType": "Patient", "id": f"p{i}"},
        at=T0 + timedelta(minutes=minutes),
        **kw,
    )


def event_types(conn, entity_id: UUID) -> list[str]:
    return [r[0] for r in conn.execute(text("SELECT event_type FROM event_log WHERE entity_id = :e"), {"e": entity_id})]


# Merge keeps the earliest-ingested member's entity id --------------------------------------


def test_merge_keeps_the_entity_of_the_earliest_ingested_member(conn):
    a, b, c, d = plain(conn, 1, 10), plain(conn, 2, 20), plain(conn, 3, 0), plain(conn, 4, 30)
    e_ab, _ = apply_approve(conn, *approved(conn, a, b))
    e_cd, _ = apply_approve(conn, *approved(conn, c, d))
    merged, _ = apply_approve(conn, *approved(conn, b, d))
    assert merged.id == e_cd.id, "c (ingested first) sits in e_cd, so e_cd keeps its id"
    assert {m.source_record_id for m in merged.members} == {a, b, c, d}
    assert conn.execute(text("SELECT count(*) FROM entity WHERE id = :e"), {"e": e_ab.id}).scalar() == 0
    assert rows_touching(conn, "entity_member", [a, b, c, d]) == 4


def test_merge_singleton_into_entity_keeps_entity_id_even_when_the_singleton_is_older(conn):
    a, b, c = plain(conn, 1, 10), plain(conn, 2, 20), plain(conn, 3, 0)
    e_ab, _ = apply_approve(conn, *approved(conn, a, b))
    merged, _ = apply_approve(conn, *approved(conn, b, c))
    assert merged.id == e_ab.id and merged.version == 2


# Approve on a pair already inside one entity --------------------------------------------


def test_approve_of_a_pair_already_in_the_same_entity_changes_nothing(conn):
    clinic, er = hero(conn)
    z = plain(conn, 9, -5)
    e1, _ = apply_approve(conn, *approved(conn, z, clinic))
    e2, alerts = apply_approve(conn, *approved(conn, clinic, er))
    assert e1.id == e2.id and [a.tier for a in alerts] == [AlertTier.A]
    version_before = e2.version
    e3, alerts3 = apply_approve(conn, *approved(conn, z, er))  # third edge inside the same component
    assert e3.id == e2.id and e3.version == version_before
    assert [a.id for a in alerts3] == [alerts[0].id], "the same alert is kept, no duplicate"
    assert event_types(conn, e3.id).count("ENTITY_MERGED") == 2 and event_types(conn, e3.id).count("ALERT_RAISED") == 1
    assert conn.execute(text("SELECT count(*) FROM safety_alert WHERE entity_id = :e"), {"e": e3.id}).scalar() == 1


# not_a_match conflict ------------------------------------------------------------------------


def test_approve_that_would_link_across_a_not_a_match_pair_raises_cannot_link_conflict(conn):
    a, b, c = plain(conn, 1, 0), plain(conn, 2, 1), plain(conn, 3, 2)
    p_ab = pair(conn, a, b)
    rejected = decision(conn, p_ab, DecisionStatus.REJECTED, reason=ReasonCode.DIFFERENT_PERSON.value)
    apply_reject(conn, p_ab, rejected)
    apply_approve(conn, *approved(conn, b, c))
    with pytest.raises(CannotLinkConflict):
        apply_approve(
            conn, *approved(conn, a, c)
        )  # transitive: a~c~b would put the not_a_match pair (a,b) in one entity
    assert conn.execute(text("SELECT count(*) FROM entity_member WHERE source_record_id = :a"), {"a": a}).scalar() == 0


# Split, retract, re-approve ---------------------------------------------------------------


def test_split_retracts_and_re_approve_raises_a_new_alert_id(conn):
    clinic, er = hero(conn)
    pid, _ = approved(conn, clinic, er)
    entity, alerts = apply_approve(
        conn,
        pid,
        conn.execute(
            text("SELECT id FROM match_decision WHERE pair_id = :p AND status = 'LINKED'"), {"p": pid}
        ).scalar(),
    )
    first = alerts[0]
    result = apply_split(
        conn, entity.id, [er], actor="registrar:Registrar B", reason_code=ReasonCode.INSUFFICIENT_EVIDENCE
    )
    assert result.retracted_alert_ids == [first.id]
    assert read_alerts(conn, entity.id, status=AlertStatus.PRELIMINARY) == []
    assert read_alerts(conn, entity.id)[0].status == AlertStatus.RETRACTED
    # registrar links the pair again: LINKED v(n+1) on the same pair
    relinked = decision(conn, pid, DecisionStatus.LINKED, actor="registrar:Registrar B")
    entity2, alerts2 = apply_approve(conn, pid, relinked)
    assert entity2.id == entity.id
    assert len(alerts2) == 1 and alerts2[0].id != first.id and alerts2[0].status == AlertStatus.PRELIMINARY
    statuses = conn.execute(
        text("SELECT status FROM safety_alert WHERE entity_id = :e ORDER BY identified_at, id"), {"e": entity.id}
    ).all()
    assert sorted(s[0] for s in statuses) == ["PRELIMINARY", "RETRACTED"]
    assert (
        event_types(conn, entity.id).count("ALERT_RETRACTED") == 1
        and event_types(conn, entity.id).count("ALERT_RAISED") == 2
    )


def test_split_with_different_person_blocks_the_re_approve(conn):
    clinic, er = hero(conn)
    pid, _ = approved(conn, clinic, er)
    entity, _ = apply_approve(
        conn,
        pid,
        conn.execute(
            text("SELECT id FROM match_decision WHERE pair_id = :p AND status = 'LINKED'"), {"p": pid}
        ).scalar(),
    )
    apply_split(conn, entity.id, [er], actor="registrar:Registrar B", reason_code=ReasonCode.DIFFERENT_PERSON)
    relinked = decision(conn, pid, DecisionStatus.LINKED)
    with pytest.raises(CannotLinkConflict):
        apply_approve(conn, pid, relinked)


# Identity gate: only human-approved edges count ------------------------------------------------


def test_linked_edge_without_a_human_actor_does_not_fire_the_rule(conn):
    """Spec section 5 row 13: an auto-link edge without human approval does not count. ADR-015 says only
    humans create LINKED; the service should still refuse to treat a SYSTEM-actor LINKED row as approval."""
    clinic, er = hero(conn)
    pid = pair(conn, clinic, er)
    auto = decision(conn, pid, DecisionStatus.LINKED, actor="system:scorer", actor_type="SYSTEM", band="AUTO_LINK")
    try:
        _entity, alerts = apply_approve(conn, pid, auto)
    except (LinkError, CannotLinkConflict):
        return  # refusing the auto-link outright is also correct
    assert alerts == [], "an unapproved auto-link edge must not raise a flag"


# Golden record -------------------------------------------------------------------------------


def test_golden_three_members_conflicting_dobs_is_conflict_unresolved_and_every_value_has_a_crosswalk(conn):
    a = plain(conn, 1, 0, dob="1985-07-03", sex="FEMALE")
    b = plain(conn, 2, 1, dob="1985-03-07", sex="FEMALE")
    c = plain(conn, 3, 2, dob="1958-07-03", sex="MALE")
    apply_approve(conn, *approved(conn, a, b))
    entity, _ = apply_approve(conn, *approved(conn, b, c))
    golden = {g.field: g for g in entity.golden}
    assert golden["birthDate"].rule == "CONFLICT_UNRESOLVED" and golden["birthDate"].value is None
    assert sorted(alt.value for alt in golden["birthDate"].alternates) == ["1958-07-03", "1985-03-07", "1985-07-03"]
    assert golden["sex"].rule == "MAJORITY" and golden["sex"].value == "FEMALE"
    for g in entity.golden:
        assert g.crosswalk.source_system and g.crosswalk.source_record_id, g
        assert g.crosswalk.source_record_id in {"R1", "R2", "R3"}
        for alt in g.alternates:
            assert alt.crosswalk.source_system and alt.crosswalk.source_record_id
    assert len(entity.members) == 3 and entity.all_links_reviewer_approved is True


# Timeline -------------------------------------------------------------------------------------


def test_timeline_keeps_each_events_source_and_constructed_flag(conn):
    clinic, er = hero(conn)
    entity, _ = apply_approve(conn, *approved(conn, clinic, er))
    page = read_timeline(conn, entity.id, limit=50, cursor=None)
    by_type = {e.type: e for e in page.items}
    assert by_type["ALLERGY"].source_system == "CLINIC_CSV" and by_type["ALLERGY"].source_record_id == clinic
    assert by_type["ALLERGY"].verification.value == "CSV_DERIVED" and by_type["ALLERGY"].is_constructed is False
    assert by_type["MEDICATION_ORDER"].source_system == "ER_FHIR" and by_type["MEDICATION_ORDER"].source_record_id == er
    assert (
        by_type["MEDICATION_ORDER"].verification.value == "CODED" and by_type["MEDICATION_ORDER"].is_constructed is True
    )
    assert by_type["MEDICATION_ORDER"].resource_id == "MedicationRequest/mr-1"
    assert [e.occurred_at for e in page.items] == sorted(e.occurred_at for e in page.items)


# Two eligible orders --------------------------------------------------------------------------


def test_two_eligible_orders_raise_two_alerts(conn):
    clinic = record(
        conn,
        system="CLINIC_CSV",
        local_id="C-7",
        kind=SourceKind.CSV_ROW,
        payload={"Id": "p", "allergies": [ALLERGY_ROW], "medications": []},
        at=T0,
    )
    er = record(
        conn,
        system="ER_FHIR",
        local_id="ER-1",
        kind=SourceKind.FHIR_PATIENT,
        payload=bundle(order("mr-1"), order("mr-2", code="562251", display="Amoxicillin / Clavulanate")),
        at=T0 + timedelta(minutes=1),
    )
    _entity, alerts = apply_approve(conn, *approved(conn, clinic, er))
    assert len(alerts) == 2 and len({a.id for a in alerts}) == 2
    assert {a.order_ref.resource_id for a in alerts} == {"MedicationRequest/mr-1", "MedicationRequest/mr-2"}
    assert {a.citation.set_id for a in alerts} == {
        "d5eba477-e255-4d97-9e16-30543c298680",
        "f10634cb-6505-43f1-9b70-314c58673016",
    }


# Events never carry whole records --------------------------------------------------------------


def test_alert_events_carry_refs_not_records(conn):
    clinic, er = hero(conn)
    entity, _ = apply_approve(conn, *approved(conn, clinic, er))
    rows = conn.execute(
        text("SELECT event_type, payload::text, versions::text FROM event_log WHERE entity_id = :e"), {"e": entity.id}
    ).all()
    for event_type, payload, versions in rows:
        assert "Anaphylaxis" not in payload and "raw_payload" not in payload and "1985" not in payload, (
            event_type,
            payload,
        )
        assert "Placeholder" not in payload and "Placeholder" not in versions
    raised = [p for t, p, _ in rows if t == "ALERT_RAISED"]
    assert raised and '"alertId"' in raised[0] and '"revealedByMerge": true' in raised[0]


def test_rejected_pair_never_builds_an_entity_or_an_alert(conn):
    clinic, er = hero(conn)
    pid = pair(conn, clinic, er)
    rejected = decision(conn, pid, DecisionStatus.REJECTED, reason=ReasonCode.INSUFFICIENT_EVIDENCE.value)
    apply_reject(conn, pid, rejected)
    assert (
        conn.execute(
            text("SELECT count(*) FROM entity_member WHERE source_record_id IN (:a, :b)"), {"a": clinic, "b": er}
        ).scalar()
        == 0
    )
    assert rows_touching(conn, "safety_alert", [clinic, er]) == 0
    assert read_entity(conn, uuid4()) is None
