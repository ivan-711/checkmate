"""Chart-store writes: tokens required, intake record idempotent, handoff pairs with their
PROPOSED decision and event, and the import boundary around ``backend.chart_store.writes``."""

from __future__ import annotations

import ast
import pathlib

import pytest
from sqlalchemy import text

from backend.chart_store import writes
from backend.policy.decide import allow_token, decide, handoff_token
from backend.policy.gate import evaluate
from backend.policy.tokens import TokenMismatch
from backend.tests.policy.factories import action, attach_args, candidate, propose_args, session
from backend.tests.policy.seed import insert_session, near_duplicates
from backend.tests.policy.test_gate_db import FACTS, PROPOSE_ARGS, USER_TEXT
from contracts.models.common import Band, DecisionStatus, EventType, PairOrigin, SourceKind
from contracts.models.intake import EffectStatus
from contracts.models.policy import HistoryItem, HistoryKind, ToolName

ALLOW = allow_token(decide(action(), []))  # propose_new_chart ALLOW
INTAKE_ID = candidate().record_id
ATTACH = allow_token(
    decide(
        action(ToolName.ATTACH_HISTORY.value, session=session(intake_record_id=INTAKE_ID, intake_args_sha256="a")), []
    )
)
SEARCH = allow_token(decide(action(ToolName.SEARCH_PATIENTS.value), []))
HANDOFF = handoff_token(decide(action(), [candidate(Band.REVIEW)]))
BARE = decide(action(), [])


def intake(conn, sid, token=HANDOFF):
    return writes.create_intake_record(
        conn, token, session_id=sid, args=propose_args(), args_sha256="a" * 64, scenario_context_id="hero"
    )


def test_intake_record_written_like_ingest_and_idempotent(conn):
    sid = insert_session(conn)
    rid = intake(conn, sid)
    assert intake(conn, sid, ALLOW) == rid
    sr = conn.execute(text("SELECT * FROM source_record WHERE id = :id"), {"id": rid}).one()
    assert sr.kind == SourceKind.FRONTDESK_INTAKE.value
    assert sr.source_system == writes.INTAKE_SOURCE_SYSTEM
    assert sr.source_local_id == f"intake:{sid}"
    assert sr.is_constructed is False
    assert sr.raw_payload["evidence"]["givenName"] == "María José"
    nr = conn.execute(text("SELECT * FROM normalized_record WHERE record_id = :id"), {"id": rid}).one()
    assert (nr.given_name_folded, nr.family_name_folded, str(nr.birth_date)) == (
        "maria jose",
        "gonzalez rivera",
        "1985-07-03",
    )
    keys = conn.execute(text("SELECT count(*) FROM block_key WHERE record_id = :id"), {"id": rid}).scalar_one()
    assert keys >= 3
    assert (
        conn.execute(
            text("SELECT count(*) FROM source_record WHERE source_local_id = :l"), {"l": f"intake:{sid}"}
        ).scalar_one()
        == 1
    )
    session = conn.execute(
        text("SELECT intake_record_id, intake_args_sha256 FROM intake_session WHERE id = :id"), {"id": sid}
    ).one()
    assert (session.intake_record_id, session.intake_args_sha256) == (rid, "a" * 64)


def test_handoff_pairs_with_proposed_decision_and_event(conn):
    er, clinic = near_duplicates(conn)
    sid = insert_session(conn)
    ev = evaluate(
        conn,
        session_id=sid,
        tool_name="propose_new_chart",
        raw_args=PROPOSE_ARGS,
        user_texts=(USER_TEXT,),
        session=FACTS,
    )
    token = handoff_token(ev.decision)
    rid = writes.create_intake_record(
        conn, token, session_id=sid, args=ev.action.args, args_sha256=ev.action.args_sha256, scenario_context_id=None
    )
    pair_ids = writes.create_handoff_pairs(
        conn,
        token,
        session_id=sid,
        intake_record_id=rid,
        candidates=ev.candidates,
        evidence_snapshot=ev.evidence_snapshot,
        thresholds_id=ev.thresholds_id,
        scorer_version=ev.scorer_version,
    )
    n = len(ev.decision.evidence_ids)  # the seeded pair, plus hero records other tests committed
    assert n >= 2 and len(pair_ids) == n
    pairs = conn.execute(text("SELECT * FROM candidate_pair WHERE id = ANY(:ids)"), {"ids": pair_ids}).all()
    assert all(p.origin == PairOrigin.FRONTDESK_HANDOFF.value and p.intake_session_id == sid for p in pairs)
    assert all(p.record_a_id < p.record_b_id and rid in (p.record_a_id, p.record_b_id) for p in pairs)
    assert {p.record_a_id for p in pairs} | {p.record_b_id for p in pairs} >= {rid, er, clinic}
    decisions = conn.execute(text("SELECT * FROM match_decision WHERE pair_id = ANY(:ids)"), {"ids": pair_ids}).all()
    assert len(decisions) == n
    for d in decisions:
        assert (d.version, d.status, d.actor, d.actor_type) == (
            1,
            DecisionStatus.PROPOSED.value,
            writes.GATE_ACTOR,
            "SYSTEM",
        )
        assert d.band in (Band.REVIEW.value, Band.AUTO_LINK.value)
        assert d.evidence_snapshot["rawScore"] == d.raw_score
        assert d.threshold_set_id == ev.thresholds_id
    events = conn.execute(
        text("SELECT pair_id, decision_id FROM event_log WHERE event_type = :t AND pair_id = ANY(:ids)"),
        {"t": EventType.INTAKE_HANDOFF_CREATED.value, "ids": pair_ids},
    ).all()
    assert {e.pair_id for e in events} == set(pair_ids)
    assert {e.decision_id for e in events} == {d.id for d in decisions}
    # a second handoff on the same pairs keeps the PROPOSED decision: no duplicate rows
    again = writes.create_handoff_pairs(
        conn,
        token,
        session_id=sid,
        intake_record_id=rid,
        candidates=ev.candidates,
        evidence_snapshot=ev.evidence_snapshot,
        thresholds_id=ev.thresholds_id,
        scorer_version=ev.scorer_version,
    )
    assert sorted(again) == sorted(pair_ids)
    assert (
        conn.execute(
            text("SELECT count(*) FROM match_decision WHERE pair_id = ANY(:ids)"), {"ids": pair_ids}
        ).scalar_one()
        == 2
    )


def test_mark_new_chart_and_history(conn):
    sid = insert_session(conn)
    rid = intake(conn, sid, ALLOW)
    effect = writes.mark_new_chart(conn, ALLOW, session_id=sid, intake_record_id=rid)
    assert (effect.status, effect.ref) == (EffectStatus.APPLIED, str(rid))
    items = [HistoryItem(kind=HistoryKind.ALLERGY, text="Amoxicillin", evidence_quote="alergia a la amoxicilina")]
    first = writes.append_intake_history(conn, ATTACH, intake_record_id=rid, items=items)
    assert [e.status for e in first] == [EffectStatus.APPLIED]
    replay = writes.append_intake_history(
        conn, ATTACH, intake_record_id=rid, items=[items[0].model_copy(update={"text": "  AMOXICILLIN "})]
    )
    assert [e.status for e in replay] == [EffectStatus.REPLAYED] and replay[0].ref == first[0].ref
    rows = conn.execute(
        text("SELECT verification FROM intake_history_item WHERE intake_record_id = :id"), {"id": rid}
    ).all()
    assert [r.verification for r in rows] == ["AGENT_INTAKE_UNVERIFIED"]


def test_mark_new_chart_refuses_a_foreign_intake_record(conn):
    sid, other = insert_session(conn), insert_session(conn)
    rid = intake(conn, other, ALLOW)
    with pytest.raises(ValueError):
        writes.mark_new_chart(conn, ALLOW, session_id=sid, intake_record_id=rid)


@pytest.mark.parametrize("bad", [BARE, None, "ALLOW", object()])
def test_every_write_refuses_anything_but_a_token(conn, bad):
    sid = insert_session(conn)
    with pytest.raises(TokenMismatch):
        writes.create_intake_record(
            conn, bad, session_id=sid, args=propose_args(), args_sha256="a", scenario_context_id=None
        )
    with pytest.raises(TokenMismatch):
        writes.create_handoff_pairs(
            conn,
            bad,
            session_id=sid,
            intake_record_id=sid,
            candidates=[],
            evidence_snapshot={},
            thresholds_id="t",
            scorer_version="s",
        )
    with pytest.raises(TokenMismatch):
        writes.mark_new_chart(conn, bad, session_id=sid, intake_record_id=sid)
    with pytest.raises(TokenMismatch):
        writes.append_intake_history(conn, bad, intake_record_id=sid, items=attach_args().items)


def test_tokens_for_the_wrong_tool_are_refused(conn):
    sid = insert_session(conn)
    for wrong in (SEARCH, ATTACH):
        with pytest.raises(TokenMismatch):
            writes.create_intake_record(
                conn, wrong, session_id=sid, args=propose_args(), args_sha256="a", scenario_context_id=None
            )
        with pytest.raises(TokenMismatch):
            writes.mark_new_chart(conn, wrong, session_id=sid, intake_record_id=sid)
    for wrong in (SEARCH, ALLOW):
        with pytest.raises(TokenMismatch):
            writes.append_intake_history(conn, wrong, intake_record_id=sid, items=attach_args().items)


def test_handoff_writes_refuse_an_allow_token(conn):
    sid = insert_session(conn)
    with pytest.raises(TokenMismatch):
        writes.create_handoff_pairs(
            conn,
            ALLOW,
            session_id=sid,
            intake_record_id=sid,
            candidates=[],
            evidence_snapshot={},
            thresholds_id="t",
            scorer_version="s",
        )
    with pytest.raises(TokenMismatch):
        writes.mark_new_chart(conn, HANDOFF, session_id=sid, intake_record_id=sid)


def test_only_the_executor_imports_chart_store_writes():
    root = pathlib.Path(__file__).resolve().parents[2]
    offenders = []
    for path in root.rglob("*.py"):
        if "tests" in path.parts or path == root / "frontdesk" / "executor.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
            if any(n.startswith("backend.chart_store.writes") or n == "backend.chart_store" for n in names):
                offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_handoff_reuses_a_match_run_pair_and_attaches_it_to_the_session(conn):
    """A match run may already hold the (intake, candidate) pair: the unique index forbids a second
    one, so the handoff reuses it, sets intake_session_id and appends PROPOSED v1 only when it has
    no decision yet."""
    from backend.tests.link.seed import insert_decision, insert_pair

    er, clinic = near_duplicates(conn)
    sid = insert_session(conn)
    ev = evaluate(
        conn,
        session_id=sid,
        tool_name="propose_new_chart",
        raw_args=PROPOSE_ARGS,
        user_texts=(USER_TEXT,),
        session=FACTS,
    )
    token = handoff_token(ev.decision)
    rid = writes.create_intake_record(
        conn, token, session_id=sid, args=ev.action.args, args_sha256=ev.action.args_sha256, scenario_context_id=None
    )
    bare_pair = insert_pair(conn, rid, er)  # MATCH_RUN, no decision yet
    decided_pair = insert_pair(conn, rid, clinic)
    insert_decision(conn, decided_pair, 1, DecisionStatus.PROPOSED, actor="system:scorer", actor_type="SYSTEM")
    pair_ids = writes.create_handoff_pairs(
        conn,
        token,
        session_id=sid,
        intake_record_id=rid,
        candidates=ev.candidates,
        evidence_snapshot=ev.evidence_snapshot,
        thresholds_id=ev.thresholds_id,
        scorer_version=ev.scorer_version,
    )
    assert {bare_pair, decided_pair} <= set(pair_ids)
    rows = {
        r.id: r
        for r in conn.execute(
            text("SELECT * FROM candidate_pair WHERE id IN (:a, :b)"), {"a": bare_pair, "b": decided_pair}
        )
    }
    assert all(r.origin == PairOrigin.MATCH_RUN.value and r.intake_session_id == sid for r in rows.values())
    versions = conn.execute(
        text(
            "SELECT pair_id, count(*) AS n, max(version) AS v FROM match_decision WHERE pair_id IN (:a, :b) GROUP BY pair_id"
        ),
        {"a": bare_pair, "b": decided_pair},
    ).all()
    by_pair = {r.pair_id: (r.n, r.v) for r in versions}
    assert by_pair[bare_pair] == (1, 1)  # PROPOSED v1 appended by the gate
    assert by_pair[decided_pair] == (1, 1)  # the scorer's PROPOSED kept, nothing duplicated
