"""CheckMate API process: 127.0.0.1 only, one pool, error envelope, request log line.

Starts from the frozen stub app so every unimplemented route answers 501 with the
contract's error envelope; lanes replace routes one at a time.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Annotated

from fastapi import Query, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from backend.app.config import load_settings
from backend.app.db import db_is_up, make_engine
from backend.golden.service import alert_page, entity_exists, read_alerts, read_entity, read_timeline
from backend.golden.timeline import BadCursor
from contracts.api_spec import build_app, error_envelope
from contracts.models.alerts import AlertStatus, SafetyAlert
from contracts.models.common import ERROR_STATUS, ErrorCode, ErrorEnvelope, Page
from contracts.models.entities import Entity, TimelineEvent
from contracts.models.health import AgentStatus, DependencyStatus, Health, HealthVersions
from contracts.version import (
    API_PREFIX,
    CONTRACT_VERSION,
    LIST_LIMIT_DEFAULT,
    LIST_LIMIT_MAX,
    POLICY_VERSION,
    TOOL_SCHEMA_VERSION,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("checkmate.request")
settings = load_settings()
engine = make_engine(settings.database_url)
# Routes the backend implements for real; their stubs are dropped. Lanes add to this set.
IMPLEMENTED = frozenset({
    ("GET", API_PREFIX + "/health"),
    ("GET", API_PREFIX + "/entities/{entity_id}"),           # W3b
    ("GET", API_PREFIX + "/entities/{entity_id}/timeline"),  # W3b
    ("GET", API_PREFIX + "/alerts"),                         # W3b
})
app = build_app(implemented=IMPLEMENTED)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Idempotency-Key", "Authorization"],
    expose_headers=["X-Request-Id"],
)


@app.middleware("http")
async def request_id_and_log(request: Request, call_next) -> Response:
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:  # never leak internals; the envelope is the contract
        log.exception("unhandled", extra={"request_id": request_id})
        response = error_envelope(ErrorCode.INTERNAL, "internal error")
    latency_ms = int((time.perf_counter() - started) * 1000)
    response.headers["X-Request-Id"] = request_id
    # one structured line per request: method, path, status, latency, mode; never whole records
    log.info("method=%s path=%s status=%s latency_ms=%s mode=%s request_id=%s",
             request.method, request.url.path, response.status_code, latency_ms,
             settings.frontdesk_agent_mode, request_id)
    return response


@app.get(API_PREFIX + "/health", response_model=Health, tags=["core"],
         description="Lane: plumbing (lead session). Dependency status and versions.")
async def health() -> Health:
    db = DependencyStatus.UP if db_is_up(engine) else DependencyStatus.DOWN
    agent = AgentStatus.REPLAY if settings.frontdesk_agent_mode != "LIVE" else AgentStatus.DOWN
    return Health(
        db=db,
        gemini=DependencyStatus.DOWN,
        modal=DependencyStatus.DOWN,
        mirror=DependencyStatus.DOWN,
        agent=agent,
        versions=HealthVersions(
            contract_version=CONTRACT_VERSION,
            policy_version=POLICY_VERSION,
            tool_schema_version=TOOL_SCHEMA_VERSION,
            git_sha=settings.git_sha,
        ),
    )


# W3b: read-time golden record, timeline and alerts (architecture section 5, section 8; ADR-014).
# Real handlers for the three stubs named in IMPLEMENTED above.
Limit = Annotated[int, Query(ge=1, description=f"clamped to {LIST_LIMIT_MAX}, never rejected")]


def _responses(*codes: ErrorCode) -> dict:
    """OpenAPI ``responses`` entries for the error envelope (the same shape api_spec uses for its stubs)."""
    return {ERROR_STATUS[c]: {"model": ErrorEnvelope, "description": c.value} for c in codes}


_NOT_FOUND = _responses(ErrorCode.NOT_FOUND)
_COMMON = _responses(ErrorCode.VALIDATION_ERROR, ErrorCode.INTERNAL)


def _clamp(limit: int) -> int:
    return min(limit, LIST_LIMIT_MAX)


@app.get(API_PREFIX + "/entities/{entity_id}", response_model=Entity, tags=["core"], responses=_NOT_FOUND | _COMMON,
         description="Lane W3b. Read-time golden record with crosswalks.")
def get_entity(entity_id: uuid.UUID):
    with engine.connect() as conn:
        entity = read_entity(conn, entity_id)
    return entity if entity is not None else error_envelope(ErrorCode.NOT_FOUND, "entity not found")


@app.get(API_PREFIX + "/entities/{entity_id}/timeline", response_model=Page[TimelineEvent], tags=["core"],
         responses=_NOT_FOUND | _COMMON,
         description="Lane W3b. Timeline across the entity's sources; bounded keyset list.")
def get_entity_timeline(entity_id: uuid.UUID, limit: Limit = LIST_LIMIT_DEFAULT, cursor: str | None = None):
    try:
        with engine.connect() as conn:
            page = read_timeline(conn, entity_id, _clamp(limit), cursor)
    except BadCursor as exc:
        return error_envelope(ErrorCode.VALIDATION_ERROR, str(exc))
    return page if page is not None else error_envelope(ErrorCode.NOT_FOUND, "entity not found")


@app.get(API_PREFIX + "/alerts", response_model=Page[SafetyAlert], tags=["core"], responses=_NOT_FOUND | _COMMON,
         description="Lane W3b. DetectedIssue-shaped alerts, optionally for one entity; bounded keyset list.")
def list_alerts(entity_id: Annotated[uuid.UUID | None, Query(alias="entityId")] = None,
                status: AlertStatus | None = None, limit: Limit = LIST_LIMIT_DEFAULT, cursor: str | None = None):
    with engine.connect() as conn:
        if entity_id is not None and not entity_exists(conn, entity_id):
            return error_envelope(ErrorCode.NOT_FOUND, "entity not found")
        alerts = read_alerts(conn, entity_id, status=status)
    try:
        return alert_page(alerts, _clamp(limit), cursor)
    except BadCursor as exc:
        return error_envelope(ErrorCode.VALIDATION_ERROR, str(exc))
