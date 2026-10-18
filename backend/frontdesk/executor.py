"""Tool executor (ADR-016 §1 step 4, §3 effect table, §5 effect keys, §6 audit row).

The ONLY module that imports ``backend.chart_store.writes``. For one model tool call it asks the
gate for a decision, then in one short transaction applies the effect the decision allows, writes
the ``agent_tool_call`` row and the ``AGENT_TOOL_CALLED`` event, and returns two views: the minimal
``ToolResult`` the model sees and the full ``ToolCallRecord`` the UI sees. No connection is held
across a model call: the loop calls ``execute`` between model steps.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from backend.api.common import display_label
from backend.frontdesk import store
from backend.frontdesk.audit import event_mode, write_agent_event
from backend.frontdesk.model import ToolCallStep
from backend.frontdesk.templates import fold, message_for
from contracts.models.common import Band, EventType
from contracts.models.events import Versions
from contracts.models.intake import Effect, EffectStatus, GateResult, ToolCallCandidate, ToolCallRecord
from contracts.models.policy import (
    AttachArgs,
    InvalidArgs,
    PolicyOutcome,
    PolicyReason,
    ScoredCandidate,
    SessionFacts,
    ToolName,
)
from contracts.version import MAX_CANDIDATES_IN_TOOL_CALL_RECORD, POLICY_VERSION, TOOL_SCHEMA_VERSION

log = logging.getLogger("checkmate.frontdesk.executor")

MAX_CANDIDATES_FOR_MODEL = 5  # tools/tool_result.schema.json maxItems
OUTCOME_LABEL = {PolicyOutcome.ALLOW: "ALLOWED", PolicyOutcome.DENY: "DENIED"}
BAND_RANK = {Band.AUTO_LINK: 0, Band.REVIEW: 1, Band.KEEP_SEPARATE: 2}

_BIRTH_YEARS = text("SELECT record_id, birth_year FROM normalized_record WHERE record_id = ANY(:ids)")
_EXISTING_HISTORY = text("SELECT kind, text FROM intake_history_item WHERE intake_record_id = :intake_record_id")


@dataclass(frozen=True)
class Seams:
    """Lane Q1.1's gate and the chart-store writes, bound on first use so the API process imports
    (and every other route runs) before Q1.1 lands; a turn before then degrades, it never 500s."""

    policy_args: object
    policy_decide: object
    policy_gate: object
    chart_writes: object


@cache
def seams() -> Seams:
    from backend.chart_store import writes as chart_writes  # the one permitted import of chart_store.writes
    from backend.policy import args as policy_args
    from backend.policy import decide as policy_decide
    from backend.policy import gate as policy_gate

    return Seams(policy_args, policy_decide, policy_gate, chart_writes)


class Notice:
    NONE = "NONE"
    NEW_CHART_CREATED = "NEW_CHART_CREATED"
    HANDED_TO_REGISTRAR = "HANDED_TO_REGISTRAR"
    ALREADY_LINKED = "ALREADY_LINKED"


@dataclass(frozen=True)
class Execution:
    record: ToolCallRecord
    tool_result: dict
    tool_result_sha256: str
    notice: str
    handoff_required: bool


@dataclass(frozen=True)
class Degraded:
    """The gate could not decide (matcher or database failure): no effect, no tool-call row."""

    latency_ms: int


def chart_effect_key(session_id: UUID) -> str:
    return f"chart:v1:{session_id}"


def attach_effect_key(session_id: UUID, kind: str, item_text: str) -> str:
    return f"attach:v1:{session_id}:{_digest(f'{kind}|{fold(item_text)}')}"


def tool_result_sha256(tool_result: dict) -> str:
    canonical = json.dumps(tool_result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def execute(
    engine: Engine,
    *,
    session: store.SessionRow,
    turn_index: int,
    step_index: int,
    step: ToolCallStep,
    user_texts: Sequence[str],
    tool_calls_this_turn: int,
    client_request_id: str,
    transcript_sha256: str | None = None,
) -> Execution | Degraded:
    started = time.perf_counter()
    try:
        deps = seams()
    except ImportError as exc:
        log.error("gate or chart store not importable exception_class=%s", type(exc).__name__)
        return Degraded(latency_ms=_elapsed_ms(started))
    try:
        with engine.begin() as conn:
            return _execute(
                conn,
                session=session,
                turn_index=turn_index,
                step_index=step_index,
                step=step,
                user_texts=user_texts,
                tool_calls_this_turn=tool_calls_this_turn,
                client_request_id=client_request_id,
                transcript_sha256=transcript_sha256,
                started=started,
            )
    except deps.policy_gate.GateUnavailable as exc:
        # Fail closed: the transaction above rolled back, so no effect and no tool-call row exist.
        log.warning("gate unavailable exception_class=%s session=%s", type(exc).__name__, session.id)
        return Degraded(latency_ms=_elapsed_ms(started))


def _execute(
    conn: Connection,
    *,
    session: store.SessionRow,
    turn_index: int,
    step_index: int,
    step: ToolCallStep,
    user_texts: Sequence[str],
    tool_calls_this_turn: int,
    client_request_id: str,
    transcript_sha256: str | None,
    started: float,
) -> Execution:
    # The session row lock serializes the steps of a session, so an effect-key check and its
    # insert cannot interleave with a concurrent re-run of the same turn.
    deps = seams()
    current = store.read_session(conn, session.id, for_update=True) or session
    probe = deps.policy_args.parse_action(
        step.tool_name,
        step.args,
        user_texts=user_texts,
        session=SessionFacts(tool_calls_this_turn=tool_calls_this_turn, identical_call_count=0),
    )
    facts = SessionFacts(
        intake_record_id=current.intake_record_id,
        intake_args_sha256=current.intake_args_sha256,
        session_closed=current.closed,
        tool_calls_this_turn=tool_calls_this_turn,
        identical_call_count=store.identical_call_count(conn, session.id, step.tool_name, probe.args_sha256),
    )
    evaluation = deps.policy_gate.evaluate(
        conn, session_id=session.id, tool_name=step.tool_name, raw_args=step.args, user_texts=user_texts, session=facts
    )
    decision = evaluation.decision
    action = evaluation.action
    candidates = sorted(evaluation.candidates, key=lambda c: (BAND_RANK[Band(c.band)], -c.s))
    notice, effect, effect_key, pair_ids, _intake_record_id = _apply_effect(
        conn, session_id=session.id, current=current, action=action, decision=decision, evaluation=evaluation
    )
    tool_call_id = uuid.uuid4()
    validated_args = (
        None if isinstance(action.args, InvalidArgs) else action.args.model_dump(by_alias=True, mode="json")
    )
    evidence_uuids = [ref.id for ref in decision.evidence_ids]
    latency_ms = _elapsed_ms(started)
    row = {
        "id": tool_call_id,
        "session_id": session.id,
        "turn_index": turn_index,
        "step_index": step_index,
        "tool_name": step.tool_name,
        "args": validated_args,
        "args_sha256": action.args_sha256,
        "grounding_ok": action.grounding_ok,
        "gate_outcome": decision.outcome.value,
        "reason_code": decision.reason_code.value if decision.reason_code else None,
        "evidence_ids": evidence_uuids,
        "evidence_snapshot": evaluation.evidence_snapshot,
        "effect_key": effect_key if effect.status == EffectStatus.APPLIED else None,
        "effect_status": effect.status.value,
        "effect_ref": effect.ref,
        "policy_version": decision.policy_version,
        "latency_ms": latency_ms,
    }
    try:
        with conn.begin_nested():
            store.insert_tool_call(conn, row)
    except IntegrityError:
        # The effect key was claimed by an earlier run (the row's (session, turn, step) is fresh: a
        # re-claimed turn continues its step numbering): the effect already happened.
        effect = Effect(status=EffectStatus.REPLAYED, ref=effect.ref)
        row.update({"effect_key": None, "effect_status": effect.status.value})
        store.insert_tool_call(conn, row)
    versions = Versions(
        scorer_version=evaluation.scorer_version,
        threshold_set_id=evaluation.thresholds_id,
        policy_version=decision.policy_version or POLICY_VERSION,
        prompt_version=session.prompt_version,
        tool_schema_version=session.tool_schema_version or TOOL_SCHEMA_VERSION,
        model_id=session.model_id,
        transcript_sha256=transcript_sha256,
    )
    write_agent_event(
        conn,
        event_type=EventType.AGENT_TOOL_CALLED,
        intake_session_id=session.id,
        mode=event_mode(step.mode),
        band=evaluation.highest_band,
        outcome=OUTCOME_LABEL[decision.outcome],
        latency_ms=latency_ms,
        versions=versions,
        payload=validated_args or {},
        tool_call_id=tool_call_id,
        tool_name=step.tool_name,
        gate_outcome=decision.outcome.value,
        reason_code=decision.reason_code.value if decision.reason_code else None,
        evidence_ids=evidence_uuids,
        evidence_snapshot=evaluation.evidence_snapshot,
        client_request_id=client_request_id,
        effect_status=effect.status.value,
        pair_id=pair_ids[0] if pair_ids else None,
    )
    aliases = _candidate_aliases(conn, session.id, candidates)
    message = message_for(decision.message_key, decision.outcome, decision.reason_code, session.language)
    tool_result = _tool_result(conn, decision, notice, candidates, aliases, message)
    record = ToolCallRecord(
        id=tool_call_id,
        step_index=step_index,
        tool_name=step.tool_name,
        args=validated_args,
        gate=GateResult(
            outcome=decision.outcome,
            reason_code=decision.reason_code,
            handoff_required=decision.handoff_required,
            evidence_ids=list(decision.evidence_ids),
            policy_version=decision.policy_version,
        ),
        effect=effect,
        candidates=_record_candidates(candidates, evaluation.evidence_snapshot),
        latency_ms=latency_ms,
    )
    return Execution(
        record=record,
        tool_result=tool_result,
        tool_result_sha256=tool_result_sha256(tool_result),
        notice=notice,
        handoff_required=decision.handoff_required,
    )


def _apply_effect(
    conn: Connection, *, session_id: UUID, current: store.SessionRow, action, decision, evaluation
) -> tuple[str, Effect, str | None, list[UUID], UUID | None]:
    """ADR-016 §3 effect table. Returns (notice, effect, effect_key, handoff pair ids, intake record id)."""
    deps = seams()
    policy_decide, chart_writes = deps.policy_decide, deps.chart_writes
    none = Effect(status=EffectStatus.NONE)
    tool, outcome, reason = action.tool, decision.outcome, decision.reason_code
    if tool == ToolName.PROPOSE_NEW_CHART and outcome == PolicyOutcome.ALLOW:
        token = policy_decide.allow_token(decision, tool)
        intake_record_id = current.intake_record_id or chart_writes.create_intake_record(
            conn,
            token,
            session_id=session_id,
            args=action.args,
            args_sha256=action.args_sha256,
            scenario_context_id=current.scenario_context_id,
        )
        applied = chart_writes.mark_new_chart(conn, token, session_id=session_id, intake_record_id=intake_record_id)
        return Notice.NEW_CHART_CREATED, applied, chart_effect_key(session_id), [], intake_record_id
    if tool == ToolName.PROPOSE_NEW_CHART and reason == PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER:
        token = policy_decide.handoff_token(decision, tool)
        intake_record_id = current.intake_record_id or chart_writes.create_intake_record(
            conn,
            token,
            session_id=session_id,
            args=action.args,
            args_sha256=action.args_sha256,
            scenario_context_id=current.scenario_context_id,
        )
        pair_ids = chart_writes.create_handoff_pairs(
            conn,
            token,
            session_id=session_id,
            intake_record_id=intake_record_id,
            candidates=list(evaluation.candidates),
            evidence_snapshot=evaluation.evidence_snapshot,
            thresholds_id=evaluation.thresholds_id,
            scorer_version=evaluation.scorer_version,
        )
        return Notice.HANDED_TO_REGISTRAR, none, None, list(pair_ids), intake_record_id
    if tool == ToolName.ATTACH_HISTORY and outcome == PolicyOutcome.ALLOW and isinstance(action.args, AttachArgs):
        token = policy_decide.allow_token(decision, tool)
        intake_record_id = current.intake_record_id
        effects = chart_writes.append_intake_history(
            conn, token, intake_record_id=intake_record_id, items=list(action.args.items)
        )
        keys = [attach_effect_key(session_id, i.kind.value, i.text) for i in action.args.items]
        # One effect_key column per row: the item key for one item, a digest of the sorted keys for a set.
        key = keys[0] if len(keys) == 1 else f"attach:v1:{session_id}:{_digest('|'.join(sorted(keys)))}"
        status = (
            EffectStatus.APPLIED if any(e.status == EffectStatus.APPLIED for e in effects) else EffectStatus.REPLAYED
        )
        if store.has_effect_key(conn, key):
            status = EffectStatus.REPLAYED
        ref = ",".join(e.ref for e in effects if e.ref) or str(intake_record_id)
        return Notice.NONE, Effect(status=status, ref=ref), key, [], intake_record_id
    if reason == PolicyReason.ALREADY_LINKED:
        return Notice.ALREADY_LINKED, none, None, [], current.intake_record_id
    if decision.handoff_required:
        return Notice.HANDED_TO_REGISTRAR, none, None, [], current.intake_record_id
    return Notice.NONE, none, None, [], current.intake_record_id


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _candidate_aliases(conn: Connection, session_id: UUID, candidates: Sequence[ScoredCandidate]) -> dict[UUID, str]:
    """Session-scoped C1..Cn in order of first appearance across the session's audited calls, then this call."""
    order: list[UUID] = []
    for row in store.read_tool_calls(conn, session_id):
        for rid in row.evidence_ids or []:
            if rid not in order:
                order.append(rid)
    for c in candidates:
        if c.record_id not in order:
            order.append(c.record_id)
    return {rid: f"C{i + 1}" for i, rid in enumerate(order)}


def _tool_result(
    conn: Connection,
    decision,
    notice: str,
    candidates: Sequence[ScoredCandidate],
    aliases: dict[UUID, str],
    message: str,
) -> dict:
    shown = list(candidates[:MAX_CANDIDATES_FOR_MODEL])
    years = {}
    if shown:
        years = {r.record_id: r.birth_year for r in conn.execute(_BIRTH_YEARS, {"ids": [c.record_id for c in shown]})}
    items = []
    for c in shown:
        item = {
            "candidateRef": aliases[c.record_id],
            "band": Band(c.band).value,
            "sourceLabel": display_label(c.source_system),
        }
        if years.get(c.record_id) is not None:
            item["birthYear"] = int(years[c.record_id])
        items.append(item)
    return {
        "status": OUTCOME_LABEL[decision.outcome],
        "reasonCode": decision.reason_code.value if decision.reason_code else None,
        "notice": notice,
        "candidates": items,
        "message": message,
    }


def _record_candidates(candidates: Sequence[ScoredCandidate], snapshot: dict) -> list[ToolCallCandidate]:
    contributions = {}
    for entry in (snapshot or {}).get("candidates", []) or []:
        if isinstance(entry, dict) and entry.get("recordId") is not None:
            contributions[str(entry["recordId"])] = entry.get("topContributions") or []
    out = []
    for c in candidates[:MAX_CANDIDATES_IN_TOOL_CALL_RECORD]:
        out.append(
            ToolCallCandidate(
                record_id=c.record_id,
                source_system=c.source_system,
                p=c.p,
                band=c.band,
                negative_rules_fired=list(c.negative_rules_fired),
                top_contributions=contributions.get(str(c.record_id), []),
                pair_id=c.pair_id,
            )
        )
    return out
