"""POST /match-runs: block, score, band over the loaded records (architecture §3, §5, §6).

Writes candidate_pair rows (origin MATCH_RUN), a PROPOSED decision with the immutable
evidence snapshot, one PAIR_SCORED event per pair and MATCH_RUN_COMPLETED, all in one
transaction. Idempotent by natural keys: pairs are unique on the record pair and a new
decision version is written only when §7 allows (first proposal; a changed evidence
snapshot on a PROPOSED pair or on an INSUFFICIENT_EVIDENCE rejection).
"""

from __future__ import annotations

import json
import time
import uuid
from itertools import combinations
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.engine import Connection, Row

from backend.api.common import current_decision_row, current_thresholds
from backend.app.deps import EngineDep
from backend.app.openapi_meta import common_error_responses
from backend.events.writer import write_event
from backend.match.seam import MatchCore, MatchResult, Thresholds, resolve_core
from contracts.models.common import ActorType, Band, DecisionStatus, EventType, PairOrigin, ReasonCode
from contracts.models.events import Versions
from contracts.models.records import NormalizedRecord
from contracts.models.sessions import MatchRunResponse, OversizedBlock
from contracts.version import API_PREFIX, BLOCK_MAX_RECORDS, MATCH_RUN_QUEUED_PAIR_IDS_MAX

router = APIRouter(prefix=API_PREFIX, tags=["core"])

SCORER_ACTOR = "system:scorer"

_RECORDS = text(
    "SELECT record_id, given_name, family_name, given_name_folded, family_name_folded, birth_date, sex, phone_e164, "
    "address_line, zip5 FROM normalized_record"
)
_BLOCK_KEYS = text("SELECT key_type, key_value, record_id FROM block_key")
_NOT_A_MATCH = text("SELECT record_a_id, record_b_id FROM not_a_match")
_ENTITY_COUNT = text("SELECT count(*) FROM entity")
_UPSERT_PAIR = text(
    "INSERT INTO candidate_pair (id, record_a_id, record_b_id, block_keys, origin) "
    "VALUES (:id, :a, :b, :block_keys, :origin) "
    "ON CONFLICT (record_a_id, record_b_id) DO UPDATE SET block_keys = EXCLUDED.block_keys RETURNING id"
)
_INSERT_DECISION = text(
    "INSERT INTO match_decision (id, pair_id, version, logit, p, raw_score, band, negative_rules_fired, "
    "evidence_snapshot, status, actor, actor_type, scorer_version, threshold_set_id) VALUES (:id, :pair_id, :version, "
    ":logit, :p, :raw_score, :band, :rules, CAST(:snapshot AS jsonb), :status, :actor, :actor_type, :scorer_version, "
    ":threshold_set_id)"
)


def load_records(conn: Connection) -> dict[UUID, NormalizedRecord]:
    return {r.record_id: NormalizedRecord(**r._mapping) for r in conn.execute(_RECORDS)}


def build_blocks(conn: Connection) -> dict[tuple[str, str], list[UUID]]:
    blocks: dict[tuple[str, str], list[UUID]] = {}
    for r in conn.execute(_BLOCK_KEYS):
        blocks.setdefault((r.key_type, r.key_value), []).append(r.record_id)
    return blocks


def block_pairs(ids: list[UUID]):
    """Every (a<b) pair inside one block. Only ever called for a block within BLOCK_MAX_RECORDS."""
    return combinations(sorted(ids), 2)


def pairs_in_block(n: int) -> int:
    return n * (n - 1) // 2


def candidate_pairs(blocks: dict[tuple[str, str], list[UUID]], suppressed: set[tuple[UUID, UUID]]):
    """S3: pairs (a<b) from blocks of at most BLOCK_MAX_RECORDS members, minus not_a_match.
    Returns (pairs -> block keys, oversized blocks, pairs reachable only through an oversized block).
    An oversized block is never expanded: its pair count is arithmetic, and the pairs it shares
    with small blocks are found by walking the small-block pairs (linear), so memory stays
    proportional to the pairs actually scored."""
    pairs: dict[tuple[UUID, UUID], list[str]] = {}
    oversized: list[OversizedBlock] = []
    oversized_members: list[frozenset[UUID]] = []
    for (key_type, key_value), ids in blocks.items():
        if len(ids) > BLOCK_MAX_RECORDS:
            oversized.append(OversizedBlock(key_type=key_type, size=len(ids)))
            oversized_members.append(frozenset(ids))
            continue
        for a, b in block_pairs(ids):
            pairs.setdefault((a, b), []).append(f"{key_type}:{key_value}")
    skipped = 0
    for members in oversized_members:
        also_small = sum(1 for a, b in pairs if a in members and b in members)
        skipped += pairs_in_block(len(members)) - also_small
    for p in suppressed:
        pairs.pop(p, None)
    return pairs, oversized, skipped


def needs_new_version(current: Row | None, result: MatchResult) -> bool:
    """Architecture §7: first proposal; or re-propose when the evidence changed on a PROPOSED pair
    or on an INSUFFICIENT_EVIDENCE rejection. LINKED, REVOKED and DIFFERENT_PERSON never move here."""
    if current is None:
        return True
    same_evidence = current.evidence_snapshot == result.evidence.model_dump(mode="json")
    if current.status == DecisionStatus.PROPOSED:
        return not same_evidence
    if current.status == DecisionStatus.REJECTED and current.reason_code == ReasonCode.INSUFFICIENT_EVIDENCE:
        return not same_evidence
    return False


def propose(
    conn: Connection, pair_id: UUID, version: int, result: MatchResult, core: MatchCore, thresholds: Thresholds
) -> UUID:
    decision_id = uuid.uuid4()
    conn.execute(
        _INSERT_DECISION,
        {
            "id": decision_id,
            "pair_id": pair_id,
            "version": version,
            "logit": result.logit,
            "p": result.p,
            "raw_score": result.evidence.raw_score,
            "band": result.band.value,
            "rules": list(result.evidence.negative_rules_fired),
            "snapshot": json.dumps(result.evidence.model_dump(mode="json")),
            "status": DecisionStatus.PROPOSED.value,
            "actor": SCORER_ACTOR,
            "actor_type": ActorType.SYSTEM.value,
            "scorer_version": core.scorer_version,
            "threshold_set_id": thresholds.threshold_set_id,
        },
    )
    return decision_id


@router.post(
    "/match-runs",
    response_model=MatchRunResponse,
    status_code=201,
    responses=common_error_responses(),
    description='Lane W2/W3a. UX "Resolve identity": block, score, band. Returns counts and the first 50 queued pair ids.',
)
def create_match_run(engine: EngineDep) -> MatchRunResponse:
    started = time.perf_counter()
    core = resolve_core()
    run_id = uuid.uuid4()
    with engine.begin() as conn:
        thresholds = current_thresholds(conn)
        versions = Versions(scorer_version=core.scorer_version, threshold_set_id=thresholds.threshold_set_id)
        records = load_records(conn)
        suppressed = {(r.record_a_id, r.record_b_id) for r in conn.execute(_NOT_A_MATCH)}
        pairs, oversized, skipped = candidate_pairs(build_blocks(conn), suppressed)
        band_counts = {b: 0 for b in Band}
        queue: list[tuple[float, UUID]] = []
        for (a, b), block_keys in pairs.items():
            result = core.match(records[a], records[b], thresholds)
            pair_id = conn.execute(
                _UPSERT_PAIR,
                {
                    "id": uuid.uuid4(),
                    "a": a,
                    "b": b,
                    "block_keys": sorted(block_keys),
                    "origin": PairOrigin.MATCH_RUN.value,
                },
            ).scalar_one()
            current = current_decision_row(conn, pair_id)
            new_version = needs_new_version(current, result)
            if new_version:
                decision_id = propose(
                    conn, pair_id, 1 if current is None else current.version + 1, result, core, thresholds
                )
                status = DecisionStatus.PROPOSED
            else:
                decision_id, status = current.id, DecisionStatus(current.status)
            band_counts[result.band] += 1
            if status == DecisionStatus.PROPOSED:
                queue.append((abs(result.p - 0.5), pair_id))
            write_event(
                conn,
                event_type=EventType.PAIR_SCORED,
                actor=SCORER_ACTOR,
                actor_type=ActorType.SYSTEM,
                run_id=run_id,
                pair_id=pair_id,
                decision_id=decision_id,
                band=result.band,
                versions=versions,
                payload={
                    "raw_score": result.evidence.raw_score,
                    "p": result.p,
                    "new_version": new_version,
                    "negative_rules_fired": list(result.evidence.negative_rules_fired),
                },
            )
        n = len(records)
        all_pairs = n * (n - 1) // 2
        response = MatchRunResponse(
            run_id=run_id,
            records=n,
            entities=conn.execute(_ENTITY_COUNT).scalar_one(),
            all_pairs=all_pairs,
            candidate_pairs=len(pairs),
            reduction_ratio=(1 - len(pairs) / all_pairs) if all_pairs else 0.0,
            band_counts=band_counts,
            oversized_blocks=oversized,
            pairs_skipped_oversized=skipped,
            queued_pair_ids=[pid for _, pid in sorted(queue)[:MATCH_RUN_QUEUED_PAIR_IDS_MAX]],
            scorer_version=core.scorer_version,
            threshold_set_id=thresholds.threshold_set_id,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
        write_event(
            conn,
            event_type=EventType.MATCH_RUN_COMPLETED,
            actor=SCORER_ACTOR,
            actor_type=ActorType.SYSTEM,
            run_id=run_id,
            versions=versions,
            payload={
                "records": n,
                "all_pairs": all_pairs,
                "candidate_pairs": len(pairs),
                "band_counts": {b.value: c for b, c in band_counts.items()},
                "oversized_blocks": len(oversized),
                "pairs_skipped_oversized": skipped,
                "elapsed_ms": response.elapsed_ms,
            },
        )
    return response
