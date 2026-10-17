"""POST /candidate-pairs/{id}/reviews: the human decision (architecture §5 Idempotency, §7).

One transaction: claim the Idempotency-Key, lock the pair row FOR UPDATE, apply the explicit
state machine, append decision v(n+1), not_a_match for DIFFERENT_PERSON, the link seam,
the event, then store the response behind the key.

State machine (``transition``):
  PROPOSED  + APPROVE / REJECT            -> effect (LINKED / REJECTED)
  LINKED    + APPROVE                     -> 200, current decision, no new version, no event
  REJECTED  + REJECT with the same reason -> 200, same
  REJECTED  + APPROVE                     -> effect: a later approve supersedes a rejection
                                             (reject then approve is on the demo path)
  anything else                           -> 409 DECISION_NOT_PENDING
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from enum import StrEnum
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.engine import Connection, Row
from sqlalchemy.exc import IntegrityError

from backend.api.common import current_decision_row, decision_from_row
from backend.app.deps import EngineDep
from backend.app.errors import ApiError
from backend.app.openapi_meta import common_error_responses, error_responses
from backend.events.writer import write_event
from backend.link import service as link
from contracts.api_spec import IdempotencyKey
from contracts.models.common import ActorType, Band, DecisionStatus, ErrorCode, EventType, ReasonCode, ReviewAction
from contracts.models.events import Versions
from contracts.models.reviews import ReviewRequest, ReviewResponse
from contracts.version import API_PREFIX

router = APIRouter(prefix=API_PREFIX, tags=["core"])

ROUTE_TEMPLATE = f"POST {API_PREFIX}/candidate-pairs/{{pair_id}}/reviews"
REGISTRAR_PREFIX = "registrar:"
OUTCOME = {ReviewAction.APPROVE: "APPROVED", ReviewAction.REJECT: "REJECTED"}
EVENT = {ReviewAction.APPROVE: EventType.LINK_APPROVED, ReviewAction.REJECT: EventType.LINK_REJECTED}
NEW_STATUS = {ReviewAction.APPROVE: DecisionStatus.LINKED, ReviewAction.REJECT: DecisionStatus.REJECTED}

_STORED = text(
    "SELECT request_sha256, status_code, response FROM idempotency_record WHERE scope = :scope AND key = :key"
)
_CLAIM = text(
    "INSERT INTO idempotency_record (scope, key, request_sha256, status_code, response) "
    "VALUES (:scope, :key, :sha, 0, CAST('{}' AS jsonb))"
)
_STORE = text(
    "UPDATE idempotency_record SET status_code = :status_code, response = CAST(:response AS jsonb) "
    "WHERE scope = :scope AND key = :key"
)
_LOCK_PAIR = text("SELECT id, record_a_id, record_b_id FROM candidate_pair WHERE id = :pair_id FOR UPDATE")
_INSERT_DECISION = text(
    "INSERT INTO match_decision (id, pair_id, version, logit, p, raw_score, band, negative_rules_fired, "
    "evidence_snapshot, status, actor, actor_type, reason_code, note, scorer_version, threshold_set_id) "
    "SELECT :id, pair_id, :version, logit, p, raw_score, band, negative_rules_fired, evidence_snapshot, :status, "
    ":actor, :actor_type, :reason_code, :note, scorer_version, threshold_set_id FROM match_decision WHERE id = :from_id"
)
_INSERT_NOT_A_MATCH = text(
    "INSERT INTO not_a_match (record_a_id, record_b_id, decision_id, actor) VALUES (:a, :b, :decision_id, :actor) "
    "ON CONFLICT (record_a_id, record_b_id) DO UPDATE SET decision_id = EXCLUDED.decision_id, actor = EXCLUDED.actor"
)
_DELETE_NOT_A_MATCH = text("DELETE FROM not_a_match WHERE record_a_id = :a AND record_b_id = :b")
# Members of a record's entity, or the record alone while it is unlinked.
_MEMBERS = (
    "SELECT em2.source_record_id FROM entity_member em1 JOIN entity_member em2 ON em2.entity_id = em1.entity_id "
    "WHERE em1.source_record_id = :{r} UNION SELECT CAST(:{r} AS uuid)"
)
_CROSSING_NOT_A_MATCH = text(
    f"WITH side_a AS ({_MEMBERS.format(r='a')}), side_b AS ({_MEMBERS.format(r='b')}) "
    "SELECT count(*) FROM not_a_match n WHERE NOT (n.record_a_id = :a AND n.record_b_id = :b) AND ("
    "(n.record_a_id IN (SELECT source_record_id FROM side_a) AND n.record_b_id IN (SELECT source_record_id FROM side_b)) OR "
    "(n.record_a_id IN (SELECT source_record_id FROM side_b) AND n.record_b_id IN (SELECT source_record_id FROM side_a)))"
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  # NUL and C0 controls except tab, LF, CR


class Transition(StrEnum):
    EFFECT = "EFFECT"
    SAME_STATE = "SAME_STATE"
    NOT_PENDING = "NOT_PENDING"


def transition(
    current_status: DecisionStatus, current_reason: ReasonCode | None, action: ReviewAction, reason: ReasonCode | None
) -> Transition:
    if current_status == DecisionStatus.PROPOSED:
        return Transition.EFFECT
    if current_status == DecisionStatus.LINKED:
        return Transition.SAME_STATE if action == ReviewAction.APPROVE else Transition.NOT_PENDING
    if current_status == DecisionStatus.REJECTED:
        if action == ReviewAction.APPROVE:
            return Transition.EFFECT
        return Transition.SAME_STATE if reason == current_reason else Transition.NOT_PENDING
    return Transition.NOT_PENDING


def registrar_actor(label: str) -> str:
    """The recorded label ``registrar:<label>``; the client may send either form."""
    return label if label.startswith(REGISTRAR_PREFIX) else REGISTRAR_PREFIX + label


def request_sha256(body) -> str:
    canonical = json.dumps(body.model_dump(by_alias=True, mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class _ConcurrentDuplicate(Exception):
    """The key was claimed by a concurrent request that committed first."""


def _replay(stored: Row, sha: str) -> JSONResponse:
    """The claim and the stored response are written in one transaction, so a visible row is complete."""
    if stored.request_sha256 != sha:
        raise ApiError(ErrorCode.IDEMPOTENCY_MISMATCH, "Idempotency-Key was used with a different request body")
    return JSONResponse(status_code=stored.status_code, content=stored.response)


def reject_control_characters(body) -> None:
    """Checklist 13: validate at the boundary. JSON allows NUL and other control characters;
    Postgres text does not, and a note is never allowed to reach a log through a DB error."""
    for field in ("actor", "note"):
        value = getattr(body, field, None)
        if value and _CONTROL_RE.search(value):
            raise ApiError(ErrorCode.VALIDATION_ERROR, f"{field} contains control characters", {"field": field})


def crossing_not_a_match(conn: Connection, pair: Row) -> int:
    """Architecture §7: APPROVE checks the link against not_a_match rows of OTHER pairs that it would
    cross: any member of A's entity against any member of B's entity, in either order. The pair's
    own row (a superseded DIFFERENT_PERSON rejection) is not a conflict; the approve lifts it."""
    return conn.execute(_CROSSING_NOT_A_MATCH, {"a": pair.record_a_id, "b": pair.record_b_id}).scalar_one()


def apply_effect(conn: Connection, pair: Row, current: Row, body, action: ReviewAction) -> ReviewResponse:
    decision_id = uuid.uuid4()
    reason = body.reason_code if action == ReviewAction.REJECT else None
    actor = registrar_actor(body.actor)
    conn.execute(
        _INSERT_DECISION,
        {
            "id": decision_id,
            "version": current.version + 1,
            "status": NEW_STATUS[action].value,
            "actor": actor,
            "actor_type": ActorType.REGISTRAR.value,
            "reason_code": reason.value if reason else None,
            "note": body.note,
            "from_id": current.id,
        },
    )
    records = {"a": pair.record_a_id, "b": pair.record_b_id}
    entity, alerts = None, []
    if action == ReviewAction.APPROVE:
        if crossing_not_a_match(conn, pair):
            raise ApiError(
                ErrorCode.CANNOT_LINK_CONFLICT, "the link would cross a not_a_match decision of another pair"
            )
        # The pair's own suppression, written by the rejection this approve supersedes, is lifted;
        # both decisions stay in the history.
        conn.execute(_DELETE_NOT_A_MATCH, records)
        entity, alerts = link.apply_approve(conn, pair.id, decision_id)
    else:
        if reason == ReasonCode.DIFFERENT_PERSON:
            conn.execute(_INSERT_NOT_A_MATCH, {**records, "decision_id": decision_id, "actor": actor})
        link.apply_reject(conn, pair.id, decision_id)
    write_event(
        conn,
        event_type=EVENT[action],
        actor=actor,
        actor_type=ActorType.REGISTRAR,
        pair_id=pair.id,
        decision_id=decision_id,
        entity_id=entity.id if entity else None,
        band=Band(current.band),
        outcome=OUTCOME[action],
        reason_code=reason.value if reason else None,
        versions=Versions(scorer_version=current.scorer_version, threshold_set_id=current.threshold_set_id),
        payload={
            "version": current.version + 1,
            "superseded_status": current.status,
            "has_note": body.note is not None,
            "alerts": len(alerts),
        },
    )
    decision = decision_from_row(current_decision_row(conn, pair.id))
    return ReviewResponse(decision=decision, entity=entity, alerts=alerts)


def _review(conn: Connection, scope: str, key: str, sha: str, pair_id: UUID, body) -> JSONResponse:
    stored = conn.execute(_STORED, {"scope": scope, "key": key}).one_or_none()
    if stored is not None:
        return _replay(stored, sha)
    try:
        conn.execute(_CLAIM, {"scope": scope, "key": key, "sha": sha})
    except IntegrityError:
        raise _ConcurrentDuplicate from None
    pair = conn.execute(_LOCK_PAIR, {"pair_id": pair_id}).one_or_none()
    current = current_decision_row(conn, pair_id) if pair is not None else None
    if pair is None or current is None:
        raise ApiError(ErrorCode.NOT_FOUND, "candidate pair not found")
    reject_control_characters(body)
    action = ReviewAction(body.action)
    reason = body.reason_code if action == ReviewAction.REJECT else None
    step = transition(
        DecisionStatus(current.status), ReasonCode(current.reason_code) if current.reason_code else None, action, reason
    )
    if step == Transition.NOT_PENDING:
        raise ApiError(
            ErrorCode.DECISION_NOT_PENDING,
            f"decision is {current.status}, not PROPOSED",
            {"status": current.status, "version": current.version},
        )
    if step == Transition.SAME_STATE:
        entity = link.entity_for_pair(conn, pair_id) if current.status == DecisionStatus.LINKED else None
        # A double-click's second Approve lands here; the flag card renders from this response too (R3b).
        alerts = link.alerts_for_entity(conn, entity.id) if entity is not None else []
        status_code = 200
        response = ReviewResponse(decision=decision_from_row(current), entity=entity, alerts=alerts)
    else:
        status_code, response = 201, apply_effect(conn, pair, current, body, action)
    content = response.model_dump(by_alias=True, mode="json")
    conn.execute(_STORE, {"scope": scope, "key": key, "status_code": status_code, "response": json.dumps(content)})
    return JSONResponse(status_code=status_code, content=content)


@router.post(
    "/candidate-pairs/{pair_id}/reviews",
    response_model=ReviewResponse,
    status_code=201,
    responses=error_responses(
        ErrorCode.NOT_FOUND,
        ErrorCode.CANNOT_LINK_CONFLICT,
        ErrorCode.DECISION_NOT_PENDING,
        ErrorCode.IDEMPOTENCY_MISMATCH,
    )
    | common_error_responses()
    | {
        200: {
            "model": ReviewResponse,
            "description": "same-state request: the current decision, no new version, no event",
        }
    },
    description="Lane W3a (+W3b rule). The human decision; also the registrar's FrontDesk handoff decision. "
    "Idempotency-Key required; only PROPOSED moves; same-state request returns 200 with no new version. "
    "A superseding review on the same pair (REJECTED then APPROVE) lifts that pair's own not_a_match row; "
    "both decisions stay in the history.",
)
def create_review(pair_id: UUID, body: ReviewRequest, idempotency_key: IdempotencyKey, engine: EngineDep):
    scope = f"{ROUTE_TEMPLATE} {pair_id}"
    sha = request_sha256(body)
    try:
        with engine.begin() as conn:
            return _review(conn, scope, idempotency_key, sha, pair_id, body)
    except _ConcurrentDuplicate:
        with engine.connect() as conn:
            stored = conn.execute(_STORED, {"scope": scope, "key": idempotency_key}).one()
        return _replay(stored, sha)
