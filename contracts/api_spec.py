"""The 12 frozen endpoints as a FastAPI stub (architecture §22.4).

Every handler returns 501 NOT_IMPLEMENTED until its lane lands. ``openapi.json`` is
generated from this app, so the frontend client, ``schemathesis`` and every lane build
against one spec from the freeze on. Each route's description names the lane it serves.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from contracts.models.alerts import SafetyAlert
from contracts.models.common import (
    ERROR_STATUS,
    Band,
    DecisionStatus,
    ErrorBody,
    ErrorCode,
    ErrorEnvelope,
    Page,
    PairOrigin,
)
from contracts.models.entities import Entity, HistoryEvent, TimelineEvent
from contracts.models.events import EventLogRow
from contracts.models.health import Health
from contracts.models.intake import CreateIntakeSessionRequest, IntakeSession, IntakeTurn, TurnRequest
from contracts.models.pairs import CandidatePair, CandidatePairDetail
from contracts.models.reviews import ReviewRequest, ReviewResponse
from contracts.models.sessions import CreateSessionRequest, MatchRunResponse, SessionResponse
from contracts.models.thresholds import ThresholdSet
from contracts.models.tiles import TilesResponse
from contracts.models.whatifs import WhatIfRequest, WhatIfResponse
from contracts.version import API_PREFIX, CONTRACT_VERSION, LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=8, max_length=128,
           description="UUIDv4 minted once per user intent and resent on retry"),
]


def _err(*codes: ErrorCode) -> dict:
    return {ERROR_STATUS[c]: {"model": ErrorEnvelope, "description": c.value} for c in codes}


def error_envelope(code: ErrorCode, message: str, details=None, headers: dict[str, str] | None = None) -> JSONResponse:
    body = ErrorEnvelope(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(status_code=ERROR_STATUS[code], content=body.model_dump(by_alias=True), headers=headers)


def not_implemented(lane: str) -> JSONResponse:
    return error_envelope(ErrorCode.NOT_IMPLEMENTED, f"stub: implemented by lane {lane}")


Route = tuple[str, str]  # (METHOD, path)


def build_app(implemented: frozenset[Route] = frozenset()) -> FastAPI:
    """Build the stub app. ``implemented`` names (METHOD, path) pairs whose stub is skipped
    because the backend registers the real handler (backend/app/main.py keeps that set)."""
    app = FastAPI(
        title="CheckMate API",
        version=CONTRACT_VERSION,
        description="Frozen contract (tag contracts-v1). Synthetic data only. Not for clinical use. Bound to 127.0.0.1.",
        openapi_url="/openapi.json",
    )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_envelope(ErrorCode.VALIDATION_ERROR, "request failed validation", jsonable_encoder(exc.errors()))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Framework-raised errors (malformed body 400, unknown route 404, wrong method 405)
        still use the one envelope. A malformed body is a validation error."""
        if exc.status_code in (400, 415):
            return error_envelope(ErrorCode.VALIDATION_ERROR, str(exc.detail))
        if exc.status_code == 404:
            return error_envelope(ErrorCode.NOT_FOUND, str(exc.detail))
        if exc.status_code == 405:  # keep the Allow header (RFC 9110)
            return error_envelope(ErrorCode.METHOD_NOT_ALLOWED, str(exc.detail), headers=exc.headers)
        return error_envelope(ErrorCode.INTERNAL, str(exc.detail))

    p = API_PREFIX
    common_errors = _err(ErrorCode.VALIDATION_ERROR, ErrorCode.INTERNAL, ErrorCode.NOT_IMPLEMENTED)

    @app.get(p + "/health", response_model=Health, tags=["core"], responses=common_errors,
             description="Lane: plumbing (lead session). Dependency status and versions.")
    async def health():  # pragma: no cover - replaced by backend
        return not_implemented("plumbing")

    @app.post(p + "/sessions", response_model=SessionResponse, status_code=201, tags=["core"],
              responses=_err(ErrorCode.NOT_FOUND) | common_errors,
              description="Lane W1/W3a. Reset: truncate state, load the scenario, append DEMO_RESET.")
    async def create_session(body: CreateSessionRequest):
        return not_implemented("W1/W3a")

    @app.post(p + "/match-runs", response_model=MatchRunResponse, status_code=201, tags=["core"],
              responses=common_errors,
              description='Lane W2/W3a. UX "Resolve identity": block, score, band. Returns counts and the first 50 queued pair ids.')
    async def create_match_run():
        return not_implemented("W2/W3a")

    @app.get(p + "/candidate-pairs", response_model=Page[CandidatePair], tags=["core"], responses=common_errors,
             description="Lane W3a. Review queue ordered by |p-0.5|. Bounded list.")
    async def list_candidate_pairs(
        band: Band | None = None,
        status: DecisionStatus | None = None,
        origin: PairOrigin | None = None,
        limit: int = Query(LIST_LIMIT_DEFAULT, ge=1, le=LIST_LIMIT_MAX),
        cursor: str | None = None,
    ):
        return not_implemented("W3a")

    @app.get(p + "/candidate-pairs/{pair_id}", response_model=CandidatePairDetail, tags=["core"],
             responses=_err(ErrorCode.NOT_FOUND) | common_errors,
             description="Lane W3a. Evidence view: records, contributions, decision history, merge preview.")
    async def get_candidate_pair(pair_id: UUID):
        return not_implemented("W3a")

    @app.post(p + "/candidate-pairs/{pair_id}/reviews", response_model=ReviewResponse, status_code=201, tags=["core"],
              responses={200: {"model": ReviewResponse, "description": "Same-state request: the current decision, no new version"}}
              | _err(ErrorCode.NOT_FOUND, ErrorCode.CANNOT_LINK_CONFLICT, ErrorCode.DECISION_NOT_PENDING,
                     ErrorCode.IDEMPOTENCY_MISMATCH) | common_errors,
              description="Lane W3a (+W3b rule). The human decision; also the registrar's FrontDesk handoff decision. "
                          "Idempotency-Key required. PROPOSED or REJECTED may move to LINKED or REJECTED (a second review supersedes the first, "
                          "so the demo can reject and then approve; history keeps both). LINKED only accepts the same-state APPROVE, which "
                          "returns 200 with the current decision and no new version; any other request on a non-pending state is 409 DECISION_NOT_PENDING.")
    async def create_review(pair_id: UUID, body: ReviewRequest, idempotency_key: IdempotencyKey):
        return not_implemented("W3a")

    @app.post(p + "/candidate-pairs/{pair_id}/what-ifs", response_model=WhatIfResponse, tags=["core"],
              responses=_err(ErrorCode.NOT_FOUND) | common_errors,
              description="Lane Q3.1. Judge what-ifs on the hero pair; writes nothing but WHATIF_APPLIED. p95 <= 300 ms.")
    async def create_what_if(pair_id: UUID, body: WhatIfRequest):
        return not_implemented("Q3.1")

    @app.get(p + "/entities/{entity_id}", response_model=Entity, tags=["core"],
             responses=_err(ErrorCode.NOT_FOUND) | common_errors,
             description="Lane W3b. Read-time golden record with crosswalks.")
    async def get_entity(entity_id: UUID):
        return not_implemented("W3b")

    # Additive routes (reversible forks, flagged 14:15): models existed at the freeze; stubs added so the
    # generated frontend client sees them. Lanes W3a/W3b implement them.
    @app.get(p + "/entities/{entity_id}/timeline", response_model=Page[TimelineEvent], tags=["core"],
             responses=_err(ErrorCode.NOT_FOUND) | common_errors,
             description="Lane W3b (additive). Timeline across the entity's sources; bounded list.")
    async def get_entity_timeline(entity_id: UUID, limit: int = Query(LIST_LIMIT_DEFAULT, ge=1, le=LIST_LIMIT_MAX),
                                  cursor: str | None = None):
        return not_implemented("W3b")

    @app.get(p + "/entities/{entity_id}/history", response_model=Page[HistoryEvent], tags=["core"],
             responses=_err(ErrorCode.NOT_FOUND) | common_errors,
             description="Lane Q8 (additive). Identity history events for the entity; bounded list.")
    async def get_entity_history(entity_id: UUID, limit: int = Query(LIST_LIMIT_DEFAULT, ge=1, le=LIST_LIMIT_MAX),
                                 cursor: str | None = None):
        return not_implemented("Q8")

    @app.get(p + "/alerts", response_model=Page[SafetyAlert], tags=["core"], responses=common_errors,
             description="Lane W3b (additive). DetectedIssue-shaped alerts, optionally for one entity; bounded list.")
    async def list_alerts(entity_id: Annotated[UUID | None, Query(alias="entityId")] = None,
                          limit: int = Query(LIST_LIMIT_DEFAULT, ge=1, le=LIST_LIMIT_MAX), cursor: str | None = None):
        return not_implemented("W3b")

    @app.get(p + "/events", response_model=Page[EventLogRow], tags=["core"], responses=common_errors,
             description="Lane W3a (additive, G16 step 7). The append-only event feed, newest first; bounded list "
                         "with an opaque keyset cursor over (ts, eventId).")
    async def list_events(limit: int = Query(LIST_LIMIT_DEFAULT, ge=1, le=LIST_LIMIT_MAX), cursor: str | None = None):
        return not_implemented("W3a")

    @app.get(p + "/threshold-sets/current", response_model=ThresholdSet, tags=["core"], responses=common_errors,
             description="Lane W3a (additive). The current raw-score cutoffs; Platt values display-only.")
    async def get_current_thresholds():
        return not_implemented("W3a")

    @app.get(p + "/metrics/tiles", response_model=TilesResponse, tags=["core"], responses=common_errors,
             description="Lane W3a (AGENT_GATE tile: Q1.3). Continuous-aggregate tiles for a window.")
    async def get_tiles(window_minutes: int = Query(60, ge=1, le=1440)):
        return not_implemented("W3a")

    @app.post(p + "/intake-sessions", response_model=IntakeSession, status_code=201, tags=["frontdesk"],
              responses=_err(ErrorCode.NOT_FOUND) | common_errors,
              description="Lane Q1.2. Start an intake; the server pins the agent mode from FRONTDESK_AGENT_MODE.")
    async def create_intake_session(body: CreateIntakeSessionRequest):
        return not_implemented("Q1.2")

    @app.post(p + "/intake-sessions/{session_id}/turns", response_model=IntakeTurn, status_code=201, tags=["frontdesk"],
              responses=_err(ErrorCode.NOT_FOUND, ErrorCode.TURN_IN_PROGRESS, ErrorCode.SESSION_CLOSED,
                             ErrorCode.IDEMPOTENCY_MISMATCH) | common_errors,
              description="Lane Q1.2 (gate: Q1.1). One typed message runs the agent loop. Idempotency-Key required.")
    async def create_intake_turn(session_id: UUID, body: TurnRequest, idempotency_key: IdempotencyKey):
        return not_implemented("Q1.2")

    @app.get(p + "/intake-sessions/{session_id}", response_model=IntakeSession, tags=["frontdesk"],
             responses=_err(ErrorCode.NOT_FOUND) | common_errors,
             description="Lane Q1.2. Transcript, tool calls and derived registration state, for reload and the registrar.")
    async def get_intake_session(session_id: UUID):
        return not_implemented("Q1.2")

    if implemented:
        app.router.routes = [
            r for r in app.router.routes
            if not (hasattr(r, "methods") and any((m, r.path) in implemented for m in r.methods))
        ]
    return app


app = build_app()
