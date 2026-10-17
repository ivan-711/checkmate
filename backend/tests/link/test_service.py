"""apply_approve / apply_reject / apply_revoke / apply_split against the test database."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from backend.golden.service import load_members, read_alerts, read_entity
from backend.link.service import (
    AlreadyLinked,
    CannotLinkConflict,
    LinkError,
    apply_approve,
    apply_reject,
    apply_revoke,
    apply_split,
)
from backend.rule.bl_amox_01 import evaluate
from backend.tests.link.seed import (
    T0,
    hero_records,
    insert_decision,
    insert_pair,
    insert_record,
    linked_pair,
    rows_touching,
)
from contracts.models.alerts import AlertStatus, AlertTier
from contracts.models.common import DecisionStatus, ReasonCode, SourceKind


def events(conn, pair_id=None, entity_id=None):
    sql = "SELECT event_type FROM event_log WHERE (CAST(:pair_id AS uuid) IS NULL OR pair_id = :pair_id) AND (CAST(:entity_id AS uuid) IS NULL OR entity_id = :entity_id) ORDER BY ts, event_id"
    return [r[0] for r in conn.execute(text(sql), {"pair_id": pair_id, "entity_id": entity_id})]


def alert_rows(conn, entity_id):
    return conn.execute(
        text("SELECT status, tier, retracted_at FROM safety_alert WHERE entity_id = :e ORDER BY identified_at"),
        {"e": entity_id},
    ).all()


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
    mk = lambda i, minutes: insert_record(
        conn,
        system="ER_FHIR",
        local_id=f"R{i}",
        kind=SourceKind.FHIR_PATIENT,
        raw_payload={"resourceType": "Patient", "id": f"p{i}"},
        ingested_at=T0 + timedelta(minutes=minutes),
    )
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
    assert rows_touching(conn, "safety_alert", [clinic, er]) == 0
    assert (
        conn.execute(
            text("SELECT count(*) FROM entity_member WHERE source_record_id IN (:a, :b)"), {"a": clinic, "b": er}
        ).scalar()
        == 0
    )
    assert conn.execute(text("SELECT count(*) FROM not_a_match WHERE decision_id = :d"), {"d": decision}).scalar() == 1
    assert events(conn, pair_id=pair) == []


def test_insufficient_evidence_reject_writes_no_not_a_match(conn):
    clinic, er = hero_records(conn)
    pair = insert_pair(conn, clinic, er)
    decision = insert_decision(
        conn, pair, 1, DecisionStatus.REJECTED, reason_code=ReasonCode.INSUFFICIENT_EVIDENCE.value
    )
    apply_reject(conn, pair, decision)
    assert rows_touching(conn, "not_a_match", [clinic, er]) == 0


def test_unapproved_auto_link_proposal_never_merges(conn):
    clinic, er = hero_records(conn)
    pair = insert_pair(conn, clinic, er)
    proposed = insert_decision(
        conn, pair, 1, DecisionStatus.PROPOSED, actor="system:scorer", actor_type="SYSTEM", band="AUTO_LINK"
    )
    with pytest.raises(LinkError):
        apply_approve(conn, pair, proposed)
    assert rows_touching(conn, "entity_member", [clinic, er]) == 0
    assert rows_touching(conn, "safety_alert", [clinic, er]) == 0


def test_approve_refuses_when_not_a_match_sits_inside_the_component(conn):
    clinic, er = hero_records(conn)
    pair, decision = linked_pair(conn, clinic, er)
    a, b = sorted([clinic, er])
    conn.execute(
        text(
            "INSERT INTO not_a_match (record_a_id, record_b_id, decision_id, actor) VALUES (:a, :b, :d, 'registrar:Registrar B')"
        ),
        {"a": a, "b": b, "d": decision},
    )
    with pytest.raises(CannotLinkConflict):
        apply_approve(conn, pair, decision)


def test_approve_then_split_retracts_the_flag(conn):
    clinic, er = hero_records(conn)
    pair, decision = linked_pair(conn, clinic, er)
    entity, alerts = apply_approve(conn, pair, decision)
    result = apply_split(
        conn, entity.id, [er], actor="registrar:Registrar A", reason_code=ReasonCode.INSUFFICIENT_EVIDENCE
    )
    assert next(e.id for e in result.entities) == entity.id, "the side with the earliest member keeps the id"
    assert len(result.entities) == 2 and {m.source_record_id for m in result.entities[1].members} == {er}
    assert result.retracted_alert_ids == [alerts[0].id]
    assert alert_rows(conn, entity.id)[0][0] == "RETRACTED" and alert_rows(conn, entity.id)[0][2] is not None
    status = conn.execute(
        text("SELECT status FROM match_decision WHERE pair_id = :p ORDER BY version DESC LIMIT 1"), {"p": pair}
    ).scalar()
    assert status == "REVOKED" and result.revoked_decision_ids
    # events in one transaction share ts = now(), so compare the multiset, not the order
    assert sorted(events(conn, entity_id=entity.id)) == sorted(
        ["ENTITY_MERGED", "ALERT_RAISED", "LINK_REVOKED", "ENTITY_SPLIT", "ALERT_RETRACTED"]
    )
    assert rows_touching(conn, "not_a_match", [clinic, er]) == 0
    for e in result.entities:
        assert evaluate(load_members(conn, e.id)) == [], "each side alone is silent"
        assert read_alerts(conn, e.id, status=AlertStatus.PRELIMINARY) == []


def test_split_with_different_person_writes_not_a_match(conn):
    clinic, er = hero_records(conn)
    entity, _ = apply_approve(conn, *linked_pair(conn, clinic, er))
    apply_split(conn, entity.id, [clinic], actor="registrar:Registrar C", reason_code=ReasonCode.DIFFERENT_PERSON)
    assert rows_touching(conn, "not_a_match", [clinic, er]) == 1


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
        apply_split(
            conn, entity.id, [clinic, er], actor="registrar:Registrar A", reason_code=ReasonCode.INSUFFICIENT_EVIDENCE
        )
    with pytest.raises(LinkError):
        apply_split(conn, entity.id, [], actor="registrar:Registrar A", reason_code=ReasonCode.INSUFFICIENT_EVIDENCE)


def test_completed_order_means_no_alert_after_approve(conn):
    clinic, er = hero_records(conn, order_status="completed")
    entity, alerts = apply_approve(conn, *linked_pair(conn, clinic, er))
    assert alerts == [] and alert_rows(conn, entity.id) == []


def test_retry_of_approve_logs_one_entity_merged(conn):
    clinic, er = hero_records(conn)
    pair, decision = linked_pair(conn, clinic, er)
    apply_approve(conn, pair, decision)
    entity, _ = apply_approve(conn, pair, decision)
    assert events(conn, entity_id=entity.id).count("ENTITY_MERGED") == 1


def test_split_moves_an_alert_whose_records_move_together(conn):
    clinic, er = hero_records(conn)
    z = insert_record(
        conn,
        system="ER_FHIR",
        local_id="ER-MRN-0",
        kind=SourceKind.FHIR_PATIENT,
        raw_payload={"resourceType": "Patient", "id": "z"},
        ingested_at=T0 - timedelta(days=1),
    )
    entity, _ = apply_approve(conn, *linked_pair(conn, z, clinic))
    entity, alerts = apply_approve(conn, *linked_pair(conn, clinic, er))
    assert [a.tier for a in alerts] == [AlertTier.A]
    result = apply_split(
        conn, entity.id, [clinic, er], actor="registrar:Registrar A", reason_code=ReasonCode.INSUFFICIENT_EVIDENCE
    )
    assert result.retracted_alert_ids == [], "the clinic-er edge was never revoked, so the flag keeps its id"
    assert result.entities[0].id == entity.id and {m.source_record_id for m in result.entities[0].members} == {z}
    moved = read_alerts(conn, result.entities[1].id, status=AlertStatus.PRELIMINARY)
    assert [a.id for a in moved] == [alerts[0].id]
    assert "ALERT_RETRACTED" not in events(conn, entity_id=entity.id) + events(conn, entity_id=result.entities[1].id)


def test_revoke_that_does_not_disconnect_writes_no_split_event(conn):
    mk = lambda i: insert_record(
        conn,
        system="ER_FHIR",
        local_id=f"T{i}",
        kind=SourceKind.FHIR_PATIENT,
        raw_payload={"resourceType": "Patient", "id": f"t{i}"},
        ingested_at=T0 + timedelta(minutes=i),
    )
    a, b, c = mk(1), mk(2), mk(3)
    pair_ab, _ = linked_pair(conn, a, b)
    apply_approve(
        conn,
        pair_ab,
        conn.execute(text("SELECT id FROM match_decision WHERE pair_id = :p AND version = 2"), {"p": pair_ab}).scalar(),
    )
    apply_approve(conn, *linked_pair(conn, b, c))
    entity, _ = apply_approve(conn, *linked_pair(conn, a, c))
    revoked = insert_decision(
        conn, pair_ab, 3, DecisionStatus.REVOKED, reason_code=ReasonCode.INSUFFICIENT_EVIDENCE.value
    )
    result = apply_revoke(conn, pair_ab, revoked)
    assert len(result.entities) == 1 and result.entities[0].id == entity.id
    assert "ENTITY_SPLIT" not in events(conn, entity_id=entity.id)


def test_concurrent_approvals_serialize_on_the_link_graph_lock(engine):
    """Codex finding 1: AB and CD exist; T1 approves B-C and pauses before commit; T2 approves D-E.
    Without the advisory lock T2 reads edges without B-C and leaves E in a stale CD entity."""
    import threading

    with engine.begin() as c:
        mk = lambda i: insert_record(
            c,
            system="ER_FHIR",
            local_id=f"CC{i}",
            kind=SourceKind.FHIR_PATIENT,
            raw_payload={"resourceType": "Patient", "id": f"cc{i}"},
            ingested_at=T0 + timedelta(minutes=i),
        )
        a, b, c_, d, e = records = [mk(i) for i in range(5)]
        apply_approve(c, *linked_pair(c, a, b))
        apply_approve(c, *linked_pair(c, c_, d))
        pair_bc, pair_de = insert_pair(c, b, c_), insert_pair(c, d, e)
        for p in (pair_bc, pair_de):
            insert_decision(c, p, 1, DecisionStatus.PROPOSED, actor="system:scorer", actor_type="SYSTEM")
    outcome: dict = {}
    try:
        conn1 = engine.connect()
        tx1 = conn1.begin()
        apply_approve(conn1, pair_bc, insert_decision(conn1, pair_bc, 2, DecisionStatus.LINKED))  # holds the lock

        def second_approval():
            with engine.begin() as c2:
                outcome["entity"] = apply_approve(c2, pair_de, insert_decision(c2, pair_de, 2, DecisionStatus.LINKED))[
                    0
                ]

        t2 = threading.Thread(target=second_approval)
        t2.start()
        t2.join(0.5)
        assert t2.is_alive(), "the second approval must wait for the first to commit"
        tx1.commit()
        conn1.close()
        t2.join(5)
        assert not t2.is_alive() and "entity" in outcome
        with engine.connect() as c:
            rows = c.execute(
                text("SELECT DISTINCT entity_id FROM entity_member WHERE source_record_id = ANY(:ids)"),
                {"ids": records},
            ).all()
            assert len(rows) == 1, "all five records end in one entity"
            assert {m.source_record_id for m in outcome["entity"].members} == set(records)
    finally:
        with engine.begin() as c:
            ents = [
                r[0]
                for r in c.execute(
                    text("SELECT DISTINCT entity_id FROM entity_member WHERE source_record_id = ANY(:ids)"),
                    {"ids": records},
                )
            ]
            pairs = [
                r[0]
                for r in c.execute(
                    text("SELECT id FROM candidate_pair WHERE record_a_id = ANY(:ids) OR record_b_id = ANY(:ids)"),
                    {"ids": records},
                )
            ]
            c.execute(
                text("DELETE FROM event_log WHERE entity_id = ANY(:e) OR pair_id = ANY(:p)"), {"e": ents, "p": pairs}
            )
            c.execute(text("DELETE FROM entity WHERE id = ANY(:e)"), {"e": ents})
            c.execute(text("DELETE FROM match_decision WHERE pair_id = ANY(:p)"), {"p": pairs})
            c.execute(text("DELETE FROM candidate_pair WHERE id = ANY(:p)"), {"p": pairs})
            c.execute(text("DELETE FROM source_record WHERE id = ANY(:ids)"), {"ids": records})


def test_system_written_linked_row_never_links_or_fires(conn):
    """R3b finding 1: an approved edge is a LINKED decision with actor_type REGISTRAR."""
    clinic, er = hero_records(conn)
    pair = insert_pair(conn, clinic, er)
    auto = insert_decision(
        conn, pair, 1, DecisionStatus.LINKED, actor="system:scorer", actor_type="SYSTEM", band="AUTO_LINK"
    )
    with pytest.raises(LinkError):
        apply_approve(conn, pair, auto)
    assert rows_touching(conn, "entity_member", [clinic, er]) == 0
    assert rows_touching(conn, "safety_alert", [clinic, er]) == 0
    # a system LINKED row on another pair is not an edge either: the human approval below links two records, not three
    third = insert_record(
        conn,
        system="ER_FHIR",
        local_id="ER-MRN-3",
        kind=SourceKind.FHIR_PATIENT,
        raw_payload={"resourceType": "Patient", "id": "p3"},
        ingested_at=T0 + timedelta(minutes=9),
    )
    insert_decision(
        conn, insert_pair(conn, er, third), 1, DecisionStatus.LINKED, actor="system:scorer", actor_type="SYSTEM"
    )
    human = insert_decision(conn, pair, 2, DecisionStatus.LINKED)
    entity, _ = apply_approve(conn, pair, human)
    assert {m.source_record_id for m in entity.members} == {clinic, er}


def _chain_with_unreviewed_shortcut(conn):
    """A-B and B-C approved (A clinic allergy, C ER order), A-C still PROPOSED: A and C already share an entity."""
    a, c = hero_records(conn)
    b = insert_record(
        conn,
        system="ER_FHIR",
        local_id="ER-MRN-B",
        kind=SourceKind.FHIR_PATIENT,
        raw_payload={"resourceType": "Patient", "id": "b"},
        ingested_at=T0 + timedelta(minutes=5),
    )
    apply_approve(conn, *linked_pair(conn, a, b))
    entity, alerts = apply_approve(conn, *linked_pair(conn, b, c))
    shortcut = insert_pair(conn, a, c)
    insert_decision(conn, shortcut, 1, DecisionStatus.PROPOSED, actor="system:scorer", actor_type="SYSTEM")
    return a, b, c, shortcut, entity, alerts


def test_different_person_reject_of_already_linked_records_is_refused(conn):
    a, b, c, shortcut, entity, alerts = _chain_with_unreviewed_shortcut(conn)
    assert [x.tier for x in alerts] == [AlertTier.A]
    rejected = insert_decision(
        conn, shortcut, 2, DecisionStatus.REJECTED, reason_code=ReasonCode.DIFFERENT_PERSON.value
    )
    with pytest.raises(AlreadyLinked) as refused:
        apply_reject(conn, shortcut, rejected)
    assert "already linked" in refused.value.public_message and str(a) not in refused.value.public_message
    assert rows_touching(conn, "not_a_match", [a, b, c]) == 0
    after = read_entity(conn, entity.id)
    assert (after.version, len(after.members)) == (entity.version, 3)


def test_insufficient_evidence_reject_of_already_linked_records_is_not_refused(conn):
    a, b, c, shortcut, entity, _ = _chain_with_unreviewed_shortcut(conn)
    rejected = insert_decision(
        conn, shortcut, 2, DecisionStatus.REJECTED, reason_code=ReasonCode.INSUFFICIENT_EVIDENCE.value
    )
    apply_reject(conn, shortcut, rejected)  # no suppression is written, so nothing can poison the entity
    assert rows_touching(conn, "not_a_match", [a, b, c]) == 0
    assert read_entity(conn, entity.id).version == entity.version
