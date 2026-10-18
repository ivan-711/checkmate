"""The only module that inserts intake records, handoff pairs, chart effects and intake history
(ADR-016 §1, §3). Every function requires a token built by ``backend.policy.decide``; a bare
``PolicyDecision`` is refused, so nothing reaches these rows without the gate.

All statements run on the caller's connection, inside the executor's transaction with the audit
row. Values are bound parameters; identifiers are literal in the statements below.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from backend.core.api import CORE
from backend.core.normalize import normalize_record
from backend.events.writer import write_event
from backend.policy.args import fold
from backend.policy.tokens import PolicyAllow, PolicyHandoff, require_token
from contracts.models.common import ActorType, Band, DecisionStatus, EventType, PairOrigin, SourceKind
from contracts.models.events import Versions
from contracts.models.intake import Effect, EffectStatus
from contracts.models.policy import HistoryItem, ProposeArgs, ScoredCandidate, ToolName
from contracts.version import POLICY_VERSION

INTAKE_SOURCE_SYSTEM = "FRONTDESK_INTAKE"
GATE_ACTOR = "system:frontdesk-gate"


def intake_effect_key(session_id: UUID) -> str:
    return f"intake:v1:{session_id}"


def chart_effect_key(session_id: UUID) -> str:
    return f"chart:v1:{session_id}"


def history_item_sha256(item: HistoryItem) -> str:
    return hashlib.sha256(f"{item.kind.value}|{fold(item.text)}".encode()).hexdigest()


def attach_effect_key(session_id: UUID, item: HistoryItem) -> str:
    return f"attach:v1:{session_id}:{history_item_sha256(item)}"


_SESSION = text("SELECT intake_record_id, intake_args_sha256 FROM intake_session WHERE id = :session_id FOR UPDATE")
_INSERT_SOURCE = text(
    "INSERT INTO source_record (id, source_system, source_local_id, kind, raw_payload, payload_sha256, is_constructed) "
    "VALUES (:id, :source_system, :local_id, :kind, CAST(:payload AS jsonb), :sha, false)"
)
_INSERT_NORMALIZED = text(
    "INSERT INTO normalized_record (record_id, given_name, family_name, given_name_folded, family_name_folded, "
    "birth_date, birth_year, birth_month, birth_day, sex, phone_e164, address_line, zip5) VALUES (:record_id, "
    ":given_name, :family_name, :given_name_folded, :family_name_folded, :birth_date, :birth_year, :birth_month, "
    ":birth_day, :sex, :phone_e164, :address_line, :zip5)"
)
_INSERT_BLOCK_KEY = text(
    "INSERT INTO block_key (key_type, key_value, record_id) VALUES (:key_type, :key_value, :record_id) "
    "ON CONFLICT DO NOTHING"
)
_SET_INTAKE = text(
    "UPDATE intake_session SET intake_record_id = :record_id, intake_args_sha256 = :sha WHERE id = :session_id"
)
# A pair a match run already created keeps its origin but is attached to the session, so the
# registrar's later decision on it is found by the gate and the board alike.
_UPSERT_PAIR = text(
    "INSERT INTO candidate_pair (id, record_a_id, record_b_id, block_keys, origin, intake_session_id) "
    "VALUES (:id, :a, :b, '{}', :origin, :session_id) "
    "ON CONFLICT (record_a_id, record_b_id) DO UPDATE SET intake_session_id = EXCLUDED.intake_session_id RETURNING id"
)
_CURRENT_DECISION = text(
    "SELECT version, status FROM match_decision WHERE pair_id = :pair_id ORDER BY version DESC LIMIT 1 FOR UPDATE"
)
_INSERT_DECISION = text(
    "INSERT INTO match_decision (id, pair_id, version, logit, p, raw_score, band, negative_rules_fired, "
    "evidence_snapshot, status, actor, actor_type, scorer_version, threshold_set_id) VALUES (:id, :pair_id, :version, "
    ":logit, :p, :raw_score, :band, :rules, CAST(:snapshot AS jsonb), :status, :actor, :actor_type, :scorer_version, "
    ":threshold_set_id)"
)
_EFFECT_CLAIMED = text("SELECT effect_ref FROM agent_tool_call WHERE effect_key = :key")
_INTAKE_BELONGS = text("SELECT 1 FROM intake_session WHERE id = :session_id AND intake_record_id = :record_id")
_EXISTING_HISTORY = text(
    "SELECT id, text FROM intake_history_item WHERE intake_record_id = :record_id AND kind = :kind"
)
_INSERT_HISTORY = text(
    "INSERT INTO intake_history_item (id, intake_record_id, kind, text, evidence_quote) "
    "VALUES (:id, :record_id, :kind, :text, :quote)"
)


def intake_payload(args: ProposeArgs) -> dict:
    """What the intake source record stores: the validated demographics and their evidence quotes."""
    return args.model_dump(mode="json", by_alias=True, exclude_none=True)


def normalized_row(args: ProposeArgs) -> dict:
    """The intake demographics through the same normalizer ingest uses (one folding rule set)."""
    return normalize_record(
        {
            "given_name": args.given_name,
            "family_name": args.family_name,
            "birth_date": args.birth_date,
            "sex": args.sex.value if args.sex else None,
            "phone": args.phone,
            "address_line": args.address_line,
            "zip": args.postal_code,
        }
    ).to_row_dict()


def create_intake_record(
    conn: Connection,
    token: PolicyAllow | PolicyHandoff,
    *,
    session_id: UUID,
    args: ProposeArgs,
    args_sha256: str,
    scenario_context_id: str | None,
) -> UUID:
    """Source record (kind FRONTDESK_INTAKE), normalized row and block keys for this session's intake;
    idempotent: a session that already has an intake record gets the existing id back."""
    require_token(token, PolicyAllow, PolicyHandoff, tool=ToolName.PROPOSE_NEW_CHART)
    session = conn.execute(_SESSION, {"session_id": session_id}).one()
    if session.intake_record_id is not None:
        return session.intake_record_id
    record_id = uuid.uuid4()
    payload = intake_payload(args)
    if scenario_context_id is not None:
        payload = {**payload, "scenarioContextId": scenario_context_id}
    encoded = json.dumps(payload, sort_keys=True)
    conn.execute(
        _INSERT_SOURCE,
        {
            "id": record_id,
            "source_system": INTAKE_SOURCE_SYSTEM,
            "local_id": f"intake:{session_id}",
            "kind": SourceKind.FRONTDESK_INTAKE.value,
            "payload": encoded,
            "sha": hashlib.sha256(encoded.encode()).hexdigest(),
        },
    )
    row = {**normalized_row(args), "record_id": record_id}
    conn.execute(_INSERT_NORMALIZED, row)
    for key in CORE.block_keys(row):
        conn.execute(_INSERT_BLOCK_KEY, {"key_type": key.key_type, "key_value": key.key_value, "record_id": record_id})
    conn.execute(_SET_INTAKE, {"record_id": record_id, "sha": args_sha256, "session_id": session_id})
    return record_id


def create_handoff_pairs(
    conn: Connection,
    token: PolicyHandoff,
    *,
    session_id: UUID,
    intake_record_id: UUID,
    candidates: Sequence[ScoredCandidate],
    evidence_snapshot: dict,
    thresholds_id: str,
    scorer_version: str,
) -> list[UUID]:
    """One candidate_pair (origin FRONTDESK_HANDOFF) per blocking candidate in the decision's evidence,
    with a PROPOSED decision by the gate carrying the matcher's snapshot, and one INTAKE_HANDOFF_CREATED
    event per pair. A pair that already has a PROPOSED decision keeps it."""
    require_token(token, PolicyHandoff, tool=ToolName.PROPOSE_NEW_CHART)
    blocking_ids = {ref.id for ref in token.decision.evidence_ids}
    per_candidate = {entry["recordId"]: entry for entry in evidence_snapshot.get("candidates", [])}
    pair_ids: list[UUID] = []
    for candidate in candidates:
        if candidate.record_id not in blocking_ids or candidate.record_id == intake_record_id:
            continue
        a, b = sorted([intake_record_id, candidate.record_id])
        pair_id = conn.execute(
            _UPSERT_PAIR,
            {
                "id": uuid.uuid4(),
                "a": a,
                "b": b,
                "origin": PairOrigin.FRONTDESK_HANDOFF.value,
                "session_id": session_id,
            },
        ).scalar_one()
        pair_ids.append(pair_id)
        current = conn.execute(_CURRENT_DECISION, {"pair_id": pair_id}).one_or_none()
        if current is not None and current.status in (DecisionStatus.PROPOSED.value, DecisionStatus.LINKED.value):
            continue  # already in the queue, or already a chart: nothing to re-propose
        entry = per_candidate.get(str(candidate.record_id), {})
        matcher = entry.get("matcher") or {}
        decision_id = uuid.uuid4()
        conn.execute(
            _INSERT_DECISION,
            {
                "id": decision_id,
                "pair_id": pair_id,
                "version": 1 if current is None else current.version + 1,
                "logit": matcher.get("rawScore", candidate.s),
                "p": candidate.p,
                "raw_score": candidate.s,
                "band": Band(candidate.band).value,
                "rules": list(candidate.negative_rules_fired),
                "snapshot": json.dumps(matcher),
                "status": DecisionStatus.PROPOSED.value,
                "actor": GATE_ACTOR,
                "actor_type": ActorType.SYSTEM.value,
                "scorer_version": scorer_version,
                "threshold_set_id": thresholds_id,
            },
        )
        write_event(
            conn,
            event_type=EventType.INTAKE_HANDOFF_CREATED,
            actor=GATE_ACTOR,
            actor_type=ActorType.SYSTEM,
            pair_id=pair_id,
            decision_id=decision_id,
            band=candidate.band,
            outcome=token.decision.outcome.value,
            reason_code=token.decision.reason_code.value if token.decision.reason_code else None,
            versions=Versions(
                scorer_version=scorer_version, threshold_set_id=thresholds_id, policy_version=POLICY_VERSION
            ),
            payload={"intakeSessionId": str(session_id), "candidateRecordId": str(candidate.record_id)},
            intake_session_id=session_id,
            gate_outcome=token.decision.outcome.value,
        )
    return pair_ids


def mark_new_chart(conn: Connection, token: PolicyAllow, *, session_id: UUID, intake_record_id: UUID) -> Effect:
    """The new-chart effect for this session: APPLIED the first time, REPLAYED once the effect key
    ``chart:v1:{session_id}`` has been claimed on an earlier tool call. Registration state is derived
    on read from the intake record and its decisions, so there is nothing else to flip."""
    require_token(token, PolicyAllow, tool=ToolName.PROPOSE_NEW_CHART)
    if conn.execute(_INTAKE_BELONGS, {"session_id": session_id, "record_id": intake_record_id}).one_or_none() is None:
        raise ValueError("intake record does not belong to this session")
    claimed = conn.execute(_EFFECT_CLAIMED, {"key": chart_effect_key(session_id)}).one_or_none()
    if claimed is not None:
        return Effect(status=EffectStatus.REPLAYED, ref=claimed.effect_ref or str(intake_record_id))
    return Effect(status=EffectStatus.APPLIED, ref=str(intake_record_id))


def append_intake_history(
    conn: Connection, token: PolicyAllow, *, intake_record_id: UUID, items: Sequence[HistoryItem]
) -> list[Effect]:
    """Append patient-reported items to this intake record only; an item already present with the same
    kind and folded text is REPLAYED, never duplicated."""
    require_token(token, PolicyAllow, tool=ToolName.ATTACH_HISTORY)
    effects: list[Effect] = []
    for item in items:
        existing = conn.execute(_EXISTING_HISTORY, {"record_id": intake_record_id, "kind": item.kind.value}).all()
        same = next((r for r in existing if fold(r.text) == fold(item.text)), None)
        if same is not None:
            effects.append(Effect(status=EffectStatus.REPLAYED, ref=str(same.id)))
            continue
        item_id = uuid.uuid4()
        conn.execute(
            _INSERT_HISTORY,
            {
                "id": item_id,
                "record_id": intake_record_id,
                "kind": item.kind.value,
                "text": item.text,
                "quote": item.evidence_quote,
            },
        )
        effects.append(Effect(status=EffectStatus.APPLIED, ref=str(item_id)))
    return effects
