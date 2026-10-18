"""The gate against the chart store: candidates recomputed from block keys, sticky set, human
decisions, and fail-closed on matcher or database errors."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.core import api as core_api
from backend.policy import gate
from backend.policy.gate import GateUnavailable, evaluate
from backend.tests.link.seed import insert_decision, insert_pair
from backend.tests.policy.seed import (
    UNRELATED_DEMOGRAPHICS,
    insert_record,
    insert_session,
    insert_tool_call,
    near_duplicates,
)
from contracts.models.common import Band, DecisionStatus, SourceKind
from contracts.models.policy import PolicyOutcome, PolicyReason, SessionFacts

USER_TEXT = (
    "Soy María José González Rivera, nací el 3 de julio de 1985, mujer, mi teléfono es 555 010 0100, "
    "vivo en 100 Main St, código postal 54311"
)
PROPOSE_ARGS = {
    "givenName": "Maria Jose",
    "familyName": "Gonzalez Rivera",
    "birthDate": "1985-07-03",
    "sex": "FEMALE",
    "phone": "5550100100",
    "addressLine": "100 Main St",
    "postalCode": "54311",
    "preferredLanguage": "ES",
    "evidence": {
        "givenName": "María José",
        "familyName": "González Rivera",
        "birthDate": "3 de julio de 1985",
        "sex": "mujer",
        "phone": "555 010 0100",
        "addressLine": "100 Main St",
        "postalCode": "54311",
    },
}
UNRELATED_TEXT = "I am Theodore Blackwood, born January 15 1950, male, phone 555 999 0000"
UNRELATED_ARGS = {
    "givenName": "Theodore",
    "familyName": "Blackwood",
    "birthDate": "1950-01-15",
    "sex": "MALE",
    "phone": "5559990000",
    "preferredLanguage": "EN",
    "evidence": {
        "givenName": "Theodore",
        "familyName": "Blackwood",
        "birthDate": "January 15 1950",
        "sex": "male",
        "phone": "555 999 0000",
    },
}
FACTS = SessionFacts(tool_calls_this_turn=1, identical_call_count=0)


def propose(conn, session_id, args=PROPOSE_ARGS, texts=(USER_TEXT,), facts=FACTS):
    return evaluate(
        conn, session_id=session_id, tool_name="propose_new_chart", raw_args=args, user_texts=texts, session=facts
    )


def test_matching_demographics_are_held_with_the_candidates_as_evidence(conn):
    er, clinic = near_duplicates(conn)
    sid = insert_session(conn)
    ev = propose(conn, sid)
    assert ev.decision.outcome == PolicyOutcome.DENY
    assert ev.decision.reason_code == PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER
    assert ev.decision.handoff_required
    assert {e.id for e in ev.decision.evidence_ids} == {er, clinic}
    assert ev.highest_band in (Band.REVIEW, Band.AUTO_LINK)
    assert [c.band for c in ev.candidates] == sorted(
        (c.band for c in ev.candidates), key=gate.BAND_RANK.get, reverse=True
    )
    snapshot = ev.evidence_snapshot
    assert {c["recordId"] for c in snapshot["candidates"]} == {str(er), str(clinic)}
    assert set(snapshot) >= {"cLow", "cHigh", "thresholdsId", "scorerVersion"}
    for entry, cand in zip(snapshot["candidates"], ev.candidates, strict=True):
        assert entry["sha256"] == cand.evidence_snapshot_sha256
        assert set(entry) >= {"s", "p", "band", "negativeRulesFired", "topContributions"}
        assert len(entry["topContributions"]) <= 10
    assert ev.thresholds_id == snapshot["thresholdsId"]


def test_unrelated_demographics_are_allowed(conn):
    near_duplicates(conn)
    sid = insert_session(conn)
    ev = propose(conn, sid, UNRELATED_ARGS, (UNRELATED_TEXT,))
    assert ev.decision.outcome == PolicyOutcome.ALLOW
    assert ev.candidates == ()
    assert ev.highest_band is None


def test_sticky_candidate_stays_when_new_args_no_longer_block(conn):
    er, _clinic = near_duplicates(conn)
    sid = insert_session(conn)
    insert_tool_call(conn, sid, [er])
    ev = propose(conn, sid, UNRELATED_ARGS, (UNRELATED_TEXT,))
    assert {c.record_id for c in ev.candidates} == {er}
    assert ev.decision.outcome == PolicyOutcome.ALLOW  # unrelated person: KEEP_SEPARATE, so it does not block


def test_rejected_handoff_pair_releases_the_gate(conn):
    er, clinic = near_duplicates(conn)
    sid = insert_session(conn)
    unrelated = insert_record(
        conn,
        system="FRONTDESK_INTAKE",
        local_id=f"intake:{sid}",
        kind=SourceKind.FRONTDESK_INTAKE,
        demographics=UNRELATED_DEMOGRAPHICS,
    )
    conn.execute(
        text("UPDATE intake_session SET intake_record_id = :r, intake_args_sha256 = :s WHERE id = :id"),
        {"r": unrelated, "s": "placeholder", "id": sid},
    )
    for record in (er, clinic):
        pid = insert_pair(conn, unrelated, record)
        conn.execute(
            text("UPDATE candidate_pair SET origin = 'FRONTDESK_HANDOFF', intake_session_id = :sid WHERE id = :id"),
            {"sid": sid, "id": pid},
        )
        insert_decision(conn, pid, 1, DecisionStatus.PROPOSED, actor="system:frontdesk-gate", actor_type="SYSTEM")
    first = propose(conn, sid)
    # the intake record's own sha is what the session froze; use it so row 8 does not fire
    facts = SessionFacts(
        intake_record_id=unrelated,
        intake_args_sha256=first.action.args_sha256,
        tool_calls_this_turn=1,
        identical_call_count=0,
    )
    held = propose(conn, sid, facts=facts)
    assert held.decision.reason_code == PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER
    assert all(c.human_status == DecisionStatus.PROPOSED and c.pair_id and c.decision_id for c in held.candidates)
    for c in held.candidates:
        insert_decision(conn, c.pair_id, 2, DecisionStatus.REJECTED, reason_code="DIFFERENT_PERSON")
    released = propose(conn, sid, facts=facts)
    assert released.decision.outcome == PolicyOutcome.ALLOW
    assert all(c.human_status == DecisionStatus.REJECTED for c in released.candidates)


def test_linked_handoff_pair_denies_already_linked(conn):
    er, _clinic = near_duplicates(conn)
    sid = insert_session(conn)
    intake = insert_record(
        conn,
        system="FRONTDESK_INTAKE",
        local_id=f"intake:{sid}",
        kind=SourceKind.FRONTDESK_INTAKE,
        demographics=UNRELATED_DEMOGRAPHICS,
    )
    conn.execute(text("UPDATE intake_session SET intake_record_id = :r WHERE id = :id"), {"r": intake, "id": sid})
    pid = insert_pair(conn, intake, er)
    conn.execute(
        text("UPDATE candidate_pair SET origin = 'FRONTDESK_HANDOFF', intake_session_id = :sid WHERE id = :id"),
        {"sid": sid, "id": pid},
    )
    insert_decision(conn, pid, 1, DecisionStatus.LINKED)
    first = propose(conn, sid)
    facts = SessionFacts(
        intake_record_id=intake,
        intake_args_sha256=first.action.args_sha256,
        tool_calls_this_turn=1,
        identical_call_count=0,
    )
    assert propose(conn, sid, facts=facts).decision.reason_code == PolicyReason.ALREADY_LINKED


def test_search_allows_with_candidates(conn):
    er, clinic = near_duplicates(conn)
    sid = insert_session(conn)
    ev = evaluate(
        conn,
        session_id=sid,
        tool_name="search_patients",
        raw_args={"familyName": "Gonzalez Rivera", "birthDate": "1985-07-03", "evidence": PROPOSE_ARGS["evidence"]},
        user_texts=(USER_TEXT,),
        session=FACTS,
    )
    assert ev.decision.outcome == PolicyOutcome.ALLOW
    assert {e.id for e in ev.decision.evidence_ids} == {er, clinic}


def test_invalid_arguments_still_evaluate_without_candidates(conn):
    sid = insert_session(conn)
    ev = propose(conn, sid, {"givenName": "x"})
    assert ev.decision.reason_code == PolicyReason.INVALID_ARGUMENTS
    assert ev.candidates == ()


def test_matcher_failure_fails_closed(conn, monkeypatch):
    near_duplicates(conn)
    sid = insert_session(conn)

    def boom(*args, **kwargs):
        raise RuntimeError("scorer down")

    monkeypatch.setattr(core_api.CORE, "match", boom)
    with pytest.raises(GateUnavailable):
        propose(conn, sid)


def test_database_failure_fails_closed():
    class BrokenConnection:
        def execute(self, *args, **kwargs):
            raise RuntimeError("connection lost")

    with pytest.raises(GateUnavailable):
        propose(BrokenConnection(), uuid4())
