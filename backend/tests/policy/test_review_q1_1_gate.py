"""Paired-reviewer gate probes for lane Q1.1 (review/q1-1): block cap, pair origin, fail-closed, writes."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.chart_store import writes
from backend.policy.decide import allow_token, handoff_token
from backend.policy.gate import GateUnavailable, evaluate
from backend.tests.link.seed import insert_decision, insert_pair
from backend.tests.policy.seed import ER_DEMOGRAPHICS, insert_record, insert_session, near_duplicates
from backend.tests.policy.test_gate_db import PROPOSE_ARGS, USER_TEXT, propose
from contracts.models.common import DecisionStatus, SourceKind
from contracts.models.policy import PolicyOutcome, PolicyReason, ProposeArgs, SessionFacts


def test_oversized_block_is_never_capped(conn):
    """> BLOCK_MAX_RECORDS records sharing the probe's block keys: every one is scored."""
    ids = set()
    for i in range(130):
        ids.add(
            insert_record(
                conn,
                system="ER_FHIR",
                local_id=f"ER-{i}",
                kind=SourceKind.FHIR_PATIENT,
                demographics={**ER_DEMOGRAPHICS, "given_name": f"Maria{i}"},
            )
        )
    sid = insert_session(conn)
    ev = propose(conn, sid)
    assert {c.record_id for c in ev.candidates} >= ids
    assert len(ev.evidence_snapshot["candidates"]) >= 130


def test_impossible_date_is_deny_not_exception(conn):
    sid = insert_session(conn)
    args = {
        **PROPOSE_ARGS,
        "birthDate": "1985-13-03",
        "evidence": {**PROPOSE_ARGS["evidence"], "birthDate": "3 de 13 de 1985"},
    }
    try:
        ev = propose(conn, sid, args, (USER_TEXT + " 3 de 13 de 1985",))
    except GateUnavailable:
        pytest.fail("a model-supplied bad date degrades the turn instead of DENY INVALID_ARGUMENTS")
    assert ev.decision.outcome == PolicyOutcome.DENY


def test_feb_31_is_deny_not_exception(conn):
    sid = insert_session(conn)
    args = {
        **PROPOSE_ARGS,
        "birthDate": "1985-02-31",
        "evidence": {**PROPOSE_ARGS["evidence"], "birthDate": "31 de febrero de 1985"},
    }
    try:
        ev = propose(conn, sid, args, (USER_TEXT + " 31 de febrero de 1985",))
    except GateUnavailable:
        pytest.fail("a model-supplied impossible date degrades the turn instead of DENY INVALID_ARGUMENTS")
    assert ev.decision.outcome == PolicyOutcome.DENY


def test_linked_on_a_match_run_pair_is_already_linked(conn):
    """ADR-016 §2 rule 1 does not restrict the pair's origin: a LINKED decision between the intake
    record and a candidate on any pair means the patient has a chart."""
    er, clinic = near_duplicates(conn)
    sid = insert_session(conn)
    intake = insert_record(
        conn,
        system="FRONTDESK_INTAKE",
        local_id=f"intake:{sid}",
        kind=SourceKind.FRONTDESK_INTAKE,
        demographics=ER_DEMOGRAPHICS,
    )
    conn.execute(
        text("UPDATE intake_session SET intake_record_id = :r, intake_args_sha256 = :s WHERE id = :id"),
        {"r": intake, "s": "x", "id": sid},
    )
    pid = insert_pair(conn, intake, er)  # origin MATCH_RUN
    insert_decision(conn, pid, 1, DecisionStatus.LINKED)
    facts = SessionFacts(
        tool_calls_this_turn=1, identical_call_count=0, intake_record_id=intake, intake_args_sha256="x"
    )
    args = {**PROPOSE_ARGS}
    ev = evaluate(
        conn, session_id=sid, tool_name="propose_new_chart", raw_args=args, user_texts=(USER_TEXT,), session=facts
    )
    # args sha differs from "x", so row 8 fires first; set the stored sha to the real one
    conn.execute(
        text("UPDATE intake_session SET intake_args_sha256 = :s WHERE id = :id"),
        {"s": ev.action.args_sha256, "id": sid},
    )
    facts = SessionFacts(
        tool_calls_this_turn=1,
        identical_call_count=0,
        intake_record_id=intake,
        intake_args_sha256=ev.action.args_sha256,
    )
    ev = evaluate(
        conn, session_id=sid, tool_name="propose_new_chart", raw_args=args, user_texts=(USER_TEXT,), session=facts
    )
    assert ev.decision.reason_code == PolicyReason.ALREADY_LINKED


def test_connection_failure_is_gate_unavailable(conn, monkeypatch):
    near_duplicates(conn)
    sid = insert_session(conn)

    class Broken:
        def execute(self, *a, **k):
            raise ConnectionError("db down")

    with pytest.raises(GateUnavailable):
        propose(Broken(), sid)


def test_matcher_failure_is_gate_unavailable(conn, monkeypatch):
    from backend.core import api as core_api

    near_duplicates(conn)
    sid = insert_session(conn)
    monkeypatch.setattr(core_api.CORE, "match", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(GateUnavailable):
        propose(conn, sid)


def test_search_allow_token_cannot_mint_a_new_chart(conn):
    """A PolicyAllow minted for search_patients is a capability for a read; it must not pass
    mark_new_chart / append_intake_history / create_intake_record."""
    near_duplicates(conn)
    sid = insert_session(conn)
    ev = evaluate(
        conn,
        session_id=sid,
        tool_name="search_patients",
        raw_args={k: v for k, v in PROPOSE_ARGS.items() if k != "preferredLanguage"},
        user_texts=(USER_TEXT,),
        session=SessionFacts(tool_calls_this_turn=1, identical_call_count=0),
    )
    assert ev.decision.outcome == PolicyOutcome.ALLOW and ev.decision.message_key == "gate.allow.search"
    tok = allow_token(ev.decision)
    with pytest.raises(Exception):
        writes.create_intake_record(
            conn,
            tok,
            session_id=sid,
            args=ProposeArgs.model_validate(PROPOSE_ARGS),
            args_sha256="a" * 64,
            scenario_context_id=None,
        )
