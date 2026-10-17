"""GET /candidate-pairs (the review queue, bounded, keyset cursor) and GET /candidate-pairs/{id}
(the evidence view). Architecture §5: ordered by |p-0.5|; limit default 50, max 200, clamped."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import text
from sqlalchemy.engine import Connection, Row

from backend.api.common import (
    DECISION_COLUMNS,
    current_decision_row,
    decision_from_row,
    decode_cursor,
    encode_cursor,
    source_card,
)
from backend.app.deps import EngineDep
from backend.app.errors import ApiError
from backend.app.openapi_meta import common_error_responses, error_responses
from backend.link import service as link
from contracts.models.common import Band, DecisionStatus, ErrorCode, Page, PairOrigin
from contracts.models.pairs import CandidatePair, CandidatePairDetail, MatchDecision
from contracts.version import API_PREFIX, LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX

router = APIRouter(prefix=API_PREFIX, tags=["core"])

PAIR_COLUMNS = "cp.id AS cp_id, cp.record_a_id, cp.record_b_id, cp.block_keys, cp.origin, cp.intake_session_id"
# The current decision is the first row of the (pair_id, version DESC) index.
_CURRENT_JOIN = (
    "FROM candidate_pair cp JOIN LATERAL (SELECT * FROM match_decision md WHERE md.pair_id = cp.id "
    "ORDER BY md.version DESC LIMIT 1) d ON true"
)
# Filter columns are a closed map: the request picks a key, never an identifier.
FILTER_COLUMNS = {"band": "d.band", "status": "d.status", "origin": "cp.origin"}
_PAIR_FOR_DETAIL = text(f"SELECT {PAIR_COLUMNS} FROM candidate_pair cp WHERE cp.id = :pair_id")
_HISTORY = text(
    f"SELECT {DECISION_COLUMNS}, d.evidence_snapshot FROM match_decision d WHERE d.pair_id = :pair_id ORDER BY d.version"
)


def pair_from_row(row: Row, decision: MatchDecision) -> CandidatePair:
    return CandidatePair(
        id=row.cp_id, record_a_id=row.record_a_id, record_b_id=row.record_b_id, block_keys=list(row.block_keys or []),
        origin=row.origin, intake_session_id=row.intake_session_id, decision=decision,
        auto_eligible=decision.band == Band.AUTO_LINK,
    )


def list_query(filters: dict[str, str], after: tuple[float, UUID] | None, limit: int) -> tuple[str, dict]:
    clauses, params = [], {"limit_plus_one": limit + 1}
    for name, value in filters.items():
        clauses.append(f"{FILTER_COLUMNS[name]} = :{name}")
        params[name] = value
    if after is not None:
        clauses.append("(abs(d.p - 0.5), cp.id) > (CAST(:after_distance AS double precision), CAST(:after_id AS uuid))")
        params["after_distance"], params["after_id"] = after
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (f"SELECT {PAIR_COLUMNS}, {DECISION_COLUMNS}, abs(d.p - 0.5) AS distance {_CURRENT_JOIN}{where} "
           "ORDER BY distance, cp.id LIMIT :limit_plus_one")
    return sql, params


@router.get("/candidate-pairs", response_model=Page[CandidatePair], responses=common_error_responses(),
            description="Lane W3a. Review queue ordered by |p-0.5|. Bounded list.")
def list_candidate_pairs(
    engine: EngineDep,
    band: Band | None = None,
    status: DecisionStatus | None = None,
    origin: PairOrigin | None = None,
    limit: int = Query(LIST_LIMIT_DEFAULT, ge=1, description=f"clamped to {LIST_LIMIT_MAX}"),
    cursor: str | None = None,
) -> Page[CandidatePair]:
    limit = min(limit, LIST_LIMIT_MAX)
    after = decode_cursor(cursor) if cursor else None
    filters = {k: v.value for k, v in {"band": band, "status": status, "origin": origin}.items() if v is not None}
    sql, params = list_query(filters, after, limit)
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).all()
    page = rows[:limit]
    items = [pair_from_row(r, decision_from_row(r)) for r in page]
    next_cursor = encode_cursor(page[-1].distance, page[-1].cp_id) if len(rows) > limit else None
    return Page[CandidatePair](items=items, next_cursor=next_cursor)


def load_detail(conn: Connection, pair_id: UUID) -> CandidatePairDetail:
    pair_row = conn.execute(_PAIR_FOR_DETAIL, {"pair_id": pair_id}).one_or_none()
    if pair_row is None:
        raise ApiError(ErrorCode.NOT_FOUND, "candidate pair not found")
    history = [decision_from_row(r, r.evidence_snapshot) for r in conn.execute(_HISTORY, {"pair_id": pair_id})]
    current = history[-1]
    return CandidatePairDetail(
        pair=pair_from_row(pair_row, current),
        record_a=source_card(conn, pair_row.record_a_id, include_raw=True),
        record_b=source_card(conn, pair_row.record_b_id, include_raw=True),
        contributions=list(current.evidence_snapshot.contributions),
        history=history,
        merge_preview=link.preview_approve(conn, pair_id),
    )


@router.get("/candidate-pairs/{pair_id}", response_model=CandidatePairDetail,
            responses=error_responses(ErrorCode.NOT_FOUND) | common_error_responses(),
            description="Lane W3a. Evidence view: records, contributions, decision history, merge preview.")
def get_candidate_pair(pair_id: UUID, engine: EngineDep) -> CandidatePairDetail:
    with engine.connect() as conn:
        if current_decision_row(conn, pair_id) is None:
            raise ApiError(ErrorCode.NOT_FOUND, "candidate pair not found")
        return load_detail(conn, pair_id)
