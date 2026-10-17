"""apply_approve / apply_reject / apply_revoke / apply_split against the test database."""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from backend.golden.service import load_members, read_alerts
from backend.link.service import CannotLinkConflict, LinkError, apply_approve, apply_reject, apply_revoke, apply_split
from backend.rule.bl_amox_01 import evaluate
from backend.tests.link.seed import T0, hero_records, insert_decision, insert_pair, insert_record, linked_pair
from contracts.models.alerts import AlertStatus, AlertTier
from contracts.models.common import DecisionStatus, ReasonCode, SourceKind


def events(conn, pair_id=None, entity_id=None):
    sql = "SELECT event_type FROM event_log WHERE (CAST(:pair_id AS uuid) IS NULL OR pair_id = :pair_id) AND (CAST(:entity_id AS uuid) IS NULL OR entity_id = :entity_id) ORDER BY ts, event_id"
    return [r[0] for r in conn.execute(text(sql), {"pair_id": pair_id, "entity_id": entity_id})]


def alert_rows(conn, entity_id):
    return conn.execute(text("SELECT status, tier, retracted_at FROM safety_alert WHERE entity_id = :e ORDER BY identified_at"),
                        {"e": entity_id}).all()


def test_approve_builds_entity_keeps_earliest_member_and_raises_tier_a(conn):
    clinic, er = hero_records(conn)
    pair, decision = linked_pair(conn, clinic, er)
    entity, alerts = apply_approve(conn, pair, decision)
    assert {m.source_record_id for m in entity.members} == {clinic, er}
    assert entity.version == 1 and entity.all_links_reviewer_approved is True
    assert [a.tier for a in alerts] == [AlertTier.A]
    alert = alerts[0]
    assert alert.status == AlertStatus.PRELIMINARY and alert.revealed_by_merge is True and alert.severity == "moderate"
    assert alert.allergy_ref.source_record_id == clinic and alert.order_ref.source_record_id == er
    assert alert.constructed_scenario is True and alert.citation is not None
    assert alert_rows(conn, entity.id) == [("PRELIMINARY", "A", None)]
    assert sorted(events(conn, entity_id=entity.id)) == ["ALERT_RAISED", "ENTITY_MERGED"]
    assert all(g.crosswalk.source_record_id in {"CLINIC-7", "ER-MRN-1"} for g in entity.golden)


def test_approve_is_idempotent_on_re_run(conn):
    clinic, er = hero_records(conn)
    pair, decision = linked_pair(conn, clinic, er)
    e1, a1 = apply_approve(conn, pair, decision)
    e2, a2 = apply_approve(conn, pair, decision)
    assert e1.id == e2.id and [a.id for a in a1] == [a.id for a in a2]
    assert len(alert_rows(conn, e1.id)) == 1


def test_merge_of_two_entities_keeps_the_one_with_the_earliest_member(conn):
    mk = lambda i, minutes: insert_record(conn, system="ER_FHIR", local_id=f"R{i}", kind=SourceKind.FHIR_PATIENT,
                                          raw_payload={"resourceType": "Patient", "id": f"p{i}"}, ingested_at=T0 + timedelta(minutes=minutes))
    a, b, c, d = mk(1, 0), mk(2, 5), mk(3, 2), mk(4, 7)
    e_ab, _ = apply_approve(conn, *linked_pair(conn, a, b))
    e_cd, _ = apply_approve(conn, *linked_pair(conn, c, d))
    assert e_ab.id != e_cd.id
    merged, _ = apply_approve(conn, *linked_pair(conn, b, c))
    assert merged.id == e_ab.id, "entity holding the earliest-ingested member (a) keeps its id"
    assert {m.source_record_id for m in merged.members} == {a, b, c, d}
    assert merged.version == 2
    assert conn.execute(text("SELECT count(*) FROM entity WHERE id = :id"), {"id": e_cd.id}).scalar() == 0


def test_rejected_link_leaves_the_rule_silent_and_no_alert_row(conn):
    clinic, er = hero_records(conn)
    pair = insert_pair(conn, clinic, er)
    insert_decision(conn, pair, 1, DecisionStatus.PROPOSED, actor="system:scorer", actor_type="SYSTEM")
    decision = insert_decision(conn, pair, 2, DecisionStatus.REJECTED, reason_code=ReasonCode.DIFFERENT_PERSON.value)
    assert apply_reject(conn, pair, decision) is None
    apply_reject(conn, pair, decision)  # a retry is harmless
    assert conn.execute(text("SELECT count(*) FROM safety_alert")).scalar() == 0
    assert conn.execute(text("SELECT count(*) FROM entity_member WHERE source_record_id IN (:a, :b)"), {"a": clinic, "b": er}).scalar() == 0
    assert conn.execute(text("SELECT count(*) FROM not_a_match WHERE decision_id = :d"), {"d": decision}).scalar() == 1
    assert events(conn, pair_id=pair) == []


def test_insufficient_evidence_reject_writes_no_not_a_match(conn):
    clinic, er = hero_records(conn)
    pair = insert_pair(conn, clinic, er)
    decision = insert_decision(conn, pair, 1, DecisionStatus.REJECTED, reason_code=ReasonCode.INSUFFICIENT_EVIDENCE.value)
    apply_reject(conn, pair, decision)
    assert conn.execute(text("SELECT count(*) FROM not_a_match")).scalar() == 0


def test_unapproved_auto_link_proposal_never_merges(conn):
    clinic, er = hero_records(conn)
    pair = insert_pair(conn, clinic, er)
    proposed = insert_decision(conn, pair, 1, DecisionStatus.PROPOSED, actor="system:scorer", actor_type="SYSTEM", band="AUTO_LINK")
    with pytest.raises(LinkError):
        apply_approve(conn, pair, proposed)
    assert conn.execute(text("SELECT count(*) FROM entity_member")).scalar() == 0
    assert conn.execute(text("SELECT count(*) FROM safety_alert")).scalar() == 0


def test_approve_refuses_when_not_a_match_sits_inside_the_component(conn):
    clinic, er = hero_records(conn)
    pair, decision = linked_pair(conn, clinic, er)
    a, b = sorted([clinic, er])
    conn.execute(text("INSERT INTO not_a_match (record_a_id, record_b_id, decision_id, actor) VALUES (:a, :b, :d, 'registrar:Registrar B')"),
                 {"a": a, "b": b, "d": decision})
    with pytest.raises(CannotLinkConflict):
        apply_approve(conn, pair, decision)


def test_approve_then_split_retracts_the_flag(conn):
    clinic, er = hero_records(conn)
    pair, decision = linked_pair(conn, clinic, er)
    entity, alerts = apply_approve(conn, pair, decision)
    result = apply_split(conn, entity.id, [er], actor="registrar:Registrar A", reason_code=ReasonCode.INSUFFICIENT_EVIDENCE)
    assert next(e.id for e in result.entities) == entity.id, "the side with the earliest member keeps the id"
    assert len(result.entities) == 2 and {m.source_record_id for m in result.entities[1].members} == {er}
    assert result.retracted_alert_ids == [alerts[0].id]
    assert alert_rows(conn, entity.id)[0][0] == "RETRACTED" and alert_rows(conn, entity.id)[0][2] is not None
    status = conn.execute(text("SELECT status FROM match_decision WHERE pair_id = :p ORDER BY version DESC LIMIT 1"), {"p": pair}).scalar()
    assert status == "REVOKED" and result.revoked_decision_ids
    # events in one transaction share ts = now(), so compare the multiset, not the order
    assert sorted(events(conn, entity_id=entity.id)) == sorted(["ENTITY_MERGED", "ALERT_RAISED", "LINK_REVOKED", "ENTITY_SPLIT", "ALERT_RETRACTED"])
    assert conn.execute(text("SELECT count(*) FROM not_a_match")).scalar() == 0
    for e in result.entities:
        assert evaluate(load_members(conn, e.id)) == [], "each side alone is silent"
        assert read_alerts(conn, e.id, status=AlertStatus.PRELIMINARY) == []


def test_split_with_different_person_writes_not_a_match(conn):
    clinic, er = hero_records(conn)
    entity, _ = apply_approve(conn, *linked_pair(conn, clinic, er))
    apply_split(conn, entity.id, [clinic], actor="registrar:Registrar C", reason_code=ReasonCode.DIFFERENT_PERSON)
    assert conn.execute(text("SELECT count(*) FROM not_a_match")).scalar() == 1


def test_direct_revocation_retracts_the_flag(conn):
    clinic, er = hero_records(conn)
    pair, decision = linked_pair(conn, clinic, er)
    entity, alerts = apply_approve(conn, pair, decision)
    revoked = insert_decision(conn, pair, 3, DecisionStatus.REVOKED, reason_code=ReasonCode.INSUFFICIENT_EVIDENCE.value)
    result = apply_revoke(conn, pair, revoked)
    assert result is not None and result.retracted_alert_ids == [alerts[0].id]
    assert alert_rows(conn, entity.id)[0][0] == "RETRACTED"


def test_split_rejects_a_bad_partition(conn):
    clinic, er = hero_records(conn)
    entity, _ = apply_approve(conn, *linked_pair(conn, clinic, er))
    with pytest.raises(LinkError):
        apply_split(conn, entity.id, [clinic, er], actor="registrar:Registrar A", reason_code=ReasonCode.INSUFFICIENT_EVIDENCE)
    with pytest.raises(LinkError):
        apply_split(conn, entity.id, [], actor="registrar:Registrar A", reason_code=ReasonCode.INSUFFICIENT_EVIDENCE)


def test_completed_order_means_no_alert_after_approve(conn):
    clinic, er = hero_records(conn, order_status="completed")
    entity, alerts = apply_approve(conn, *linked_pair(conn, clinic, er))
    assert alerts == [] and alert_rows(conn, entity.id) == []
