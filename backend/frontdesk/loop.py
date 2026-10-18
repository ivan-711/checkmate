"""One typed turn (ADR-016 §1, §5 turn idempotency and lease, §8 failure modes).

Claim the turn in one short transaction, release the connection, then alternate model steps and
executor transactions until the model answers with text, the budget runs out, or the loop guard
fires. Degraded turns answer with the EN/ES template; two degraded turns in a row switch the
session to the template without calling the model. The response is stored on the turn row.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.engine import Engine, Row
from sqlalchemy.exc import IntegrityError

from backend.app.errors import ApiError
from backend.frontdesk import registration, store
from backend.frontdesk.audit import event_mode, write_agent_event
from backend.frontdesk.executor import Degraded, Notice, execute
from backend.frontdesk.model import AgentModel, ErrorStep, Message, ModelRequest, TextStep
from backend.frontdesk.prompts import system_instruction
from backend.frontdesk.templates import TEMPLATE_LINE, banned_phrase, fold
from backend.frontdesk.tools import tool_declarations
from contracts.models.common import ErrorCode, EventType
from contracts.models.events import Versions
from contracts.models.intake import (
    AssistantTextSource,
    DegradedKind,
    IntakeTurn,
    ToolCallRecord,
    TurnRequest,
    TurnStatus,
)
from contracts.version import (
    MAX_DEGRADED_TURNS_BEFORE_TEMPLATE,
    MAX_TOOL_CALLS_PER_TURN,
    MAX_TURNS_PER_SESSION,
    TURN_BUDGET_S,
    TURN_LEASE_S,
)

log = logging.getLogger("checkmate.frontdesk.loop")

RETRY_DELAY_S = 1.0
_DEGRADED_FOR_ERROR: dict[str, DegradedKind] = {
    "TIMEOUT": DegradedKind.TIMEOUT,
    "UNAVAILABLE": DegradedKind.UNAVAILABLE,
    "MALFORMED": DegradedKind.UNAVAILABLE,
    "SAFETY_BLOCKED": DegradedKind.UNAVAILABLE,
    "REPLAY_DIVERGED": DegradedKind.REPLAY_DIVERGED,
    "REPLAY_INPUT_MISMATCH": DegradedKind.REPLAY_INPUT_MISMATCH,
}
Sleep = Callable[[float], None]


def request_sha256(body: TurnRequest) -> str:
    canonical = json.dumps(body.model_dump(by_alias=True, mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class Claim:
    session: store.SessionRow
    turn_index: int
    prior_turns: tuple[Row, ...]


@dataclass(frozen=True)
class Stored:
    """A completed turn replayed from its stored response."""

    response: dict


def claim(engine: Engine, session_id: UUID, key: str, body: TurnRequest) -> Claim | Stored:
    sha = request_sha256(body)
    with engine.begin() as conn:
        session = store.read_session(conn, session_id, for_update=True)
        if session is None:
            raise ApiError(ErrorCode.NOT_FOUND, "intake session not found")
        expired = store.expire_leases(conn, session_id, TURN_LEASE_S)
        if expired:
            log.warning("expired %s stale turn lease(s) session=%s", expired, session_id)
        existing = store.turn_by_key(conn, session_id, key)
        if existing is not None:
            if existing.request_sha256 != sha:
                raise ApiError(ErrorCode.IDEMPOTENCY_MISMATCH, "Idempotency-Key was used with a different request body")
            status = TurnStatus(existing.status)
            if status == TurnStatus.COMPLETED:
                return Stored(response=existing.response)
            if status == TurnStatus.IN_PROGRESS:
                raise ApiError(ErrorCode.TURN_IN_PROGRESS, "this turn is still running")
            store.reclaim_failed(conn, session_id, key)
            turn_index = existing.turn_index
        else:
            if session.closed:
                raise ApiError(ErrorCode.SESSION_CLOSED, "this intake session is closed")
            turn_index = store.next_turn_index(conn, session_id)
            if turn_index >= MAX_TURNS_PER_SESSION:
                store.close_session(conn, session_id)
                raise ApiError(ErrorCode.SESSION_CLOSED, "this intake session reached its turn limit")
            try:
                store.claim_turn(conn, session_id, turn_index, key, sha, body.text)
            except IntegrityError:
                raise ApiError(ErrorCode.TURN_IN_PROGRESS, "this turn is still running") from None
        prior = tuple(t for t in store.read_turns(conn, session_id) if t.turn_index != turn_index)
    return Claim(session=session, turn_index=turn_index, prior_turns=prior)


def _history_messages(prior_turns: tuple[Row, ...]) -> list[Message]:
    messages: list[Message] = []
    for t in prior_turns:
        if t.status != TurnStatus.COMPLETED.value or not t.response:
            continue
        messages.append(Message(role="user", text=t.user_text))
        messages.append(Message(role="model", text=t.response.get("assistantText", "")))
    return messages


def _consecutive_degraded(prior_turns: tuple[Row, ...]) -> int:
    count = 0
    for t in reversed(prior_turns):
        if t.status != TurnStatus.COMPLETED.value:
            continue
        if not t.degraded:
            break
        count += 1
    return count


def run_turn(
    engine: Engine,
    model: AgentModel,
    *,
    session_id: UUID,
    key: str,
    body: TurnRequest,
    sleep: Sleep = time.sleep,
    transcript_sha256: str | None = None,
) -> tuple[int, dict]:
    """Returns (status code, IntakeTurn as a dict). 201 for a fresh turn, 201 again for a stored replay."""
    claimed = claim(engine, session_id, key, body)
    if isinstance(claimed, Stored):
        return 201, claimed.response
    session, turn_index = claimed.session, claimed.turn_index
    started = time.perf_counter()
    language = session.language
    template = TEMPLATE_LINE[language]
    user_texts = [t.user_text for t in claimed.prior_turns] + [body.text]
    tool_calls: list[ToolCallRecord] = []
    degraded: DegradedKind | None = None
    text: str | None = None
    source = AssistantTextSource.TEMPLATE
    new_chart_created = False

    if _consecutive_degraded(claimed.prior_turns) >= MAX_DEGRADED_TURNS_BEFORE_TEMPLATE:
        # Fail fast: a dead network costs the patient one degraded turn, not every turn.
        degraded = DegradedKind.UNAVAILABLE
    else:
        messages = _history_messages(claimed.prior_turns) + [Message(role="user", text=body.text)]
        last_sha: str | None = None
        retried = False
        step_index = 0
        calls_this_turn = 0
        while True:
            if time.perf_counter() - started > TURN_BUDGET_S:
                degraded = DegradedKind.TIMEOUT
                break
            req = ModelRequest(
                session_id=session.id,
                turn_index=turn_index,
                step_index=step_index,
                language=language,
                prompt_version=session.prompt_version,
                tool_schema_version=session.tool_schema_version,
                system_instruction=system_instruction(),
                messages=tuple(messages),
                tools=tool_declarations(),
                user_text_folded=fold(body.text),
                last_tool_result_sha256=last_sha,
            )
            step = model.next_step(req)
            if isinstance(step, ErrorStep):
                remaining = TURN_BUDGET_S - (time.perf_counter() - started)
                if step.retryable and not retried and remaining > RETRY_DELAY_S:
                    retried = True
                    sleep(RETRY_DELAY_S)
                    continue
                degraded = _DEGRADED_FOR_ERROR[step.kind]
                break
            if isinstance(step, TextStep):
                hit = banned_phrase(step.text, new_chart_created=new_chart_created)
                if hit is None:
                    text, source = step.text, AssistantTextSource.MODEL
                else:
                    log.info("banned phrase swapped for the template session=%s turn=%s", session.id, turn_index)
                break
            calls_this_turn += 1
            outcome = execute(
                engine,
                session=session,
                turn_index=turn_index,
                step_index=step_index,
                step=step,
                user_texts=user_texts,
                tool_calls_this_turn=calls_this_turn,
                client_request_id=key,
                transcript_sha256=transcript_sha256,
            )
            if isinstance(outcome, Degraded):
                degraded = DegradedKind.UNAVAILABLE
                break
            tool_calls.append(outcome.record)
            new_chart_created = new_chart_created or outcome.notice == Notice.NEW_CHART_CREATED
            last_sha = outcome.tool_result_sha256
            if calls_this_turn > MAX_TOOL_CALLS_PER_TURN:
                degraded = DegradedKind.LOOP_GUARD
                break
            messages.append(Message(role="model", tool_call=step))
            messages.append(Message(role="function", tool_call=step, tool_result=outcome.tool_result))
            step_index += 1
            # The session row may have gained an intake record; re-read it for the next step's facts.
            with engine.connect() as conn:
                session = store.read_session(conn, session.id) or session

    with engine.begin() as conn:
        if degraded is not None:
            write_agent_event(
                conn,
                event_type=EventType.AGENT_TURN_DEGRADED,
                intake_session_id=session.id,
                mode=event_mode(model.mode),
                outcome=degraded.value,
                latency_ms=int((time.perf_counter() - started) * 1000),
                versions=Versions(
                    prompt_version=session.prompt_version, tool_schema_version=session.tool_schema_version
                ),
                payload={"turnIndex": turn_index, "kind": degraded.value, "toolCalls": len(tool_calls)},
                client_request_id=key,
            )
        turn = IntakeTurn(
            turn_index=turn_index,
            user_text=body.text,
            assistant_text=text if text is not None else template,
            assistant_text_source=source,
            agent_mode=session.agent_mode,
            tool_calls=tool_calls,
            registration=registration.derive(conn, session.id),
            degraded=degraded,
        )
        response = turn.model_dump(by_alias=True, mode="json")
        store.complete_turn(
            conn, session.id, turn_index, TurnStatus.COMPLETED, response, degraded.value if degraded else None
        )
        if turn_index + 1 >= MAX_TURNS_PER_SESSION:
            store.close_session(conn, session.id)
    return 201, response
