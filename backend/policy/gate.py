"""The gate wrapper: recompute the candidates for a tool call against the chart store, score them
with the frozen matcher and current thresholds, then ``decide`` (ADR-016 §1 steps 1-3).

Reads only. The model never supplies candidates: block keys are recomputed from the arguments,
oversized blocks are never skipped here, and the session's sticky set is re-read from
``agent_tool_call`` on every call. Any matcher or database failure raises ``GateUnavailable`` so
the executor degrades the turn; the gate never answers ALLOW on an error.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from backend.api.common import current_thresholds
from backend.core.api import CORE
from backend.core.normalize import normalize_record
from backend.policy.args import parse_action
from backend.policy.decide import decide
from contracts.models.common import Band, DecisionStatus
from contracts.models.policy import (
    AgentAction,
    EvidenceKind,
    PolicyDecision,
    ProposeArgs,
    ScoredCandidate,
    SearchArgs,
    SessionFacts,
)
from contracts.version import TOP_CONTRIBUTIONS_IN_LIST_VIEWS

BAND_RANK: dict[Band, int] = {Band.AUTO_LINK: 2, Band.REVIEW: 1, Band.KEEP_SEPARATE: 0}


class GateUnavailable(RuntimeError):
    """Matcher or database failure: the executor degrades the turn; no effect."""


@dataclass(frozen=True)
class GateEvaluation:
    action: AgentAction
    candidates: tuple[ScoredCandidate, ...]
    decision: PolicyDecision
    evidence_snapshot: dict
    highest_band: Band | None
    thresholds_id: str
    scorer_version: str


_RECORDS_BY_KEYS = text(
    "SELECT DISTINCT record_id FROM block_key WHERE (key_type, key_value) IN "
    "(SELECT unnest(CAST(:types AS text[])), unnest(CAST(:values AS text[])))"
)
_STICKY = text("SELECT DISTINCT unnest(evidence_ids) AS record_id FROM agent_tool_call WHERE session_id = :session_id")
# Every band a candidate was ever given in this session, read from the audit rows (never process memory).
_STICKY_BANDS = text(
    "SELECT c->>'recordId' AS record_id, c->>'band' AS band FROM agent_tool_call, "
    "jsonb_array_elements(evidence_snapshot->'candidates') AS c WHERE session_id = :session_id"
)
_RECORD = text(
    "SELECT sr.id AS record_id, sr.source_system, nr.given_name, nr.family_name, nr.given_name_folded, "
    "nr.family_name_folded, nr.birth_date, nr.birth_year, nr.birth_month, nr.birth_day, nr.sex, nr.phone_e164, "
    "nr.address_line, nr.zip5 FROM source_record sr JOIN normalized_record nr ON nr.record_id = sr.id "
    "WHERE sr.id = ANY(CAST(:ids AS uuid[]))"
)
# Every pair between the intake record and a candidate, whatever its origin (ADR-016 §2 rule 1 has no
# origin restriction): a match run may have created the pair before the gate did.
_PAIR_STATUS = text(
    "SELECT cp.id AS pair_id, cp.record_a_id, cp.record_b_id, d.id AS decision_id, d.status "
    "FROM candidate_pair cp JOIN LATERAL (SELECT id, status FROM match_decision WHERE pair_id = cp.id "
    "ORDER BY version DESC LIMIT 1) d ON true "
    "WHERE cp.record_a_id = :intake_record_id OR cp.record_b_id = :intake_record_id"
)


def demographics_of(args: SearchArgs | ProposeArgs) -> dict:
    return {
        "given_name": args.given_name,
        "family_name": args.family_name,
        "birth_date": args.birth_date,
        "sex": args.sex.value if args.sex else None,
        "phone": args.phone,
        "address_line": args.address_line,
        "zip": args.postal_code,
    }


def _candidate_ids_by_block(conn: Connection, probe) -> set[UUID]:
    keys = CORE.block_keys(probe)
    if not keys:
        return set()
    rows = conn.execute(_RECORDS_BY_KEYS, {"types": [k.key_type for k in keys], "values": [k.key_value for k in keys]})
    return {r.record_id for r in rows}


def _sticky_ids(conn: Connection, session_id: UUID) -> set[UUID]:
    return {r.record_id for r in conn.execute(_STICKY, {"session_id": session_id})}


def _sticky_bands(conn: Connection, session_id: UUID) -> dict[UUID, Band]:
    """Highest band each candidate ever had in this session (ADR-016 §2(b), §8(3)): a REVIEW-or-higher
    hit stays blocking even when the model's next arguments no longer resemble that record."""
    highest: dict[UUID, Band] = {}
    for r in conn.execute(_STICKY_BANDS, {"session_id": session_id}):
        if not r.record_id or not r.band:
            continue
        record_id, band = UUID(r.record_id), Band(r.band)
        if record_id not in highest or BAND_RANK[band] > BAND_RANK[highest[record_id]]:
            highest[record_id] = band
    return highest


def _pair_status(conn: Connection, intake_record_id: UUID | None) -> dict[UUID, tuple[UUID, UUID, DecisionStatus]]:
    """candidate record id -> (pair id, latest decision id, status) over every pair with the intake record."""
    if intake_record_id is None:
        return {}
    out = {}
    for r in conn.execute(_PAIR_STATUS, {"intake_record_id": intake_record_id}):
        other = r.record_b_id if r.record_a_id == intake_record_id else r.record_a_id
        out[other] = (r.pair_id, r.decision_id, DecisionStatus(r.status))
    return out


def _snapshot_entry(record_id: UUID, source_system: str, result, band: Band, sticky: Band | None) -> dict:
    contributions = sorted(result.evidence.contributions, key=lambda c: -abs(c.logit))
    return {
        "recordId": str(record_id),
        "sourceSystem": source_system,
        "s": result.evidence.raw_score,
        "p": result.p,
        "band": band.value,
        "bandNow": Band(result.band).value,
        "bandSticky": sticky.value if sticky else None,
        "negativeRulesFired": list(result.evidence.negative_rules_fired),
        "topContributions": [
            c.model_dump(mode="json", by_alias=True) for c in contributions[:TOP_CONTRIBUTIONS_IN_LIST_VIEWS]
        ],
        "matcher": result.evidence.model_dump(mode="json", by_alias=True),
    }


def _sha256(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _score(conn: Connection, session_id: UUID, args: SearchArgs | ProposeArgs, session: SessionFacts):
    thresholds = current_thresholds(conn)
    probe = normalize_record(demographics_of(args))
    ids = _candidate_ids_by_block(conn, probe) | _sticky_ids(conn, session_id)
    ids.discard(session.intake_record_id)
    sticky_bands = _sticky_bands(conn, session_id)
    statuses = _pair_status(conn, session.intake_record_id)
    candidates: list[ScoredCandidate] = []
    entries: list[dict] = []
    if ids:
        for row in conn.execute(_RECORD, {"ids": list(ids)}):
            result = CORE.match(probe, row._mapping, thresholds)
            sticky = sticky_bands.get(row.record_id)
            band = Band(result.band)
            if sticky is not None and BAND_RANK[sticky] > BAND_RANK[band]:
                band = sticky
            entry = _snapshot_entry(row.record_id, row.source_system, result, band, sticky)
            sha = _sha256(entry)
            entry["sha256"] = sha
            pair_id, decision_id, status = statuses.get(row.record_id, (None, None, None))
            candidates.append(
                ScoredCandidate(
                    record_id=row.record_id,
                    source_system=row.source_system,
                    s=result.evidence.raw_score,
                    p=result.p,
                    band=band,
                    negative_rules_fired=list(result.evidence.negative_rules_fired),
                    human_status=status,
                    pair_id=pair_id,
                    decision_id=decision_id,
                    evidence_snapshot_sha256=sha,
                )
            )
            entries.append(entry)
    order = sorted(range(len(candidates)), key=lambda i: (-BAND_RANK[candidates[i].band], -candidates[i].s))
    candidates = [candidates[i] for i in order]
    entries = [entries[i] for i in order]
    snapshot = {
        "candidates": entries,
        "cLow": thresholds.c_low,
        "cHigh": thresholds.c_high,
        "thresholdsId": thresholds.threshold_set_id,
        "scorerVersion": CORE.scorer_version,
    }
    return candidates, snapshot, thresholds


def evaluate(
    conn: Connection,
    *,
    session_id: UUID,
    tool_name: str,
    raw_args: dict,
    user_texts: Sequence[str],
    session: SessionFacts,
) -> GateEvaluation:
    try:
        action = parse_action(tool_name, raw_args, user_texts=user_texts, session=session)
        if isinstance(action.args, (SearchArgs, ProposeArgs)):
            candidates, snapshot, thresholds = _score(conn, session_id, action.args, session)
            thresholds_id = thresholds.threshold_set_id
        else:
            candidates, thresholds_id = [], current_thresholds(conn).threshold_set_id
            snapshot = {"candidates": [], "thresholdsId": thresholds_id, "scorerVersion": CORE.scorer_version}
        decision = decide(action, candidates)
    except Exception as exc:  # fail closed: anything the matcher or database throws
        raise GateUnavailable(f"gate could not evaluate {tool_name}: {type(exc).__name__}") from exc
    evidence_ids = {ref.id for ref in decision.evidence_ids if ref.kind == EvidenceKind.CANDIDATE_RECORD}
    snapshot["evidenceRecordIds"] = sorted(str(i) for i in evidence_ids)
    return GateEvaluation(
        action=action,
        candidates=tuple(candidates),
        decision=decision,
        evidence_snapshot=snapshot,
        highest_band=candidates[0].band if candidates else None,
        thresholds_id=thresholds_id,
        scorer_version=CORE.scorer_version,
    )
