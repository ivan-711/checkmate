"""CheckMate API process: 127.0.0.1 only, one pool, error envelope, request log line.

Composition root. Starts from the frozen stub app so every unimplemented route answers 501
with the contract's error envelope; each lane's router replaces its stubs by adding the
(METHOD, path) pairs to IMPLEMENTED and including the router here.
"""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from starlette.responses import Response

from backend.api import match_runs, pairs, reviews, sessions, thresholds, tiles
from backend.app import request_context
from backend.app.config import load_settings
from backend.app.db import db_is_up, make_engine
from backend.app.errors import ApiError
from backend.app.openapi_meta import common_error_responses
from contracts.api_spec import build_app, error_envelope
from contracts.models.common import ErrorCode
from contracts.models.health import AgentStatus, DependencyStatus, Health, HealthVersions
from contracts.version import API_PREFIX, CONTRACT_VERSION, POLICY_VERSION, TOOL_SCHEMA_VERSION

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("checkmate.request")
settings = load_settings()
engine = make_engine(settings.database_url)
# Routes the backend implements for real; their stubs are dropped. Lanes add to this set.
IMPLEMENTED = frozenset(
    {
        ("GET", API_PREFIX + "/health"),
        ("POST", API_PREFIX + "/sessions"),  # W3a (loader seam: W1)
        ("POST", API_PREFIX + "/match-runs"),  # W3a (core seam: W2)
        ("GET", API_PREFIX + "/candidate-pairs"),  # W3a
        ("GET", API_PREFIX + "/candidate-pairs/{pair_id}"),  # W3a
        ("POST", API_PREFIX + "/candidate-pairs/{pair_id}/reviews"),  # W3a (link seam: W3b)
        ("GET", API_PREFIX + "/metrics/tiles"),  # W3a
    ("GET", API_PREFIX + "/threshold-sets/current"),  # W3a (stub added to the contract at 256ca4a)
    }
)
app = build_app(implemented=IMPLEMENTED)
app.state.engine = engine
app.state.settings = settings
for router in (sessions.router, match_runs.router, pairs.router, reviews.router, tiles.router, thresholds.router):
    app.include_router(router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Idempotency-Key", "Authorization"],
    expose_headers=["X-Request-Id"],
)


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError):
    return error_envelope(exc.code, exc.message, exc.details)


@app.exception_handler(PoolTimeout)
@app.exception_handler(OperationalError)
async def _db_unavailable(_: Request, exc: Exception):
    """Pool exhausted or the database away: 503, never a stack trace (architecture §2, §15)."""
    log.warning("database unavailable: %s", type(exc).__name__)
    return error_envelope(ErrorCode.UPSTREAM_UNAVAILABLE, "database unavailable")


@app.exception_handler(DBAPIError)
async def _db_error(_: Request, exc: DBAPIError):
    """A statement failed: class and request id only; the message may name the statement."""
    log.error(
        "database error exception_class=%s request_id=%s", type(exc).__name__, request_context.current().request_id
    )
    return error_envelope(ErrorCode.INTERNAL, "internal error")


@app.middleware("http")
async def request_id_and_log(request: Request, call_next) -> Response:
    ctx = request_context.new_context(
        request.headers.get("X-Request-Id"), request_context.parse_mode(settings.frontdesk_agent_mode)
    )
    token = request_context.bind(ctx)  # the event writer reads request_id and latency_ms from here
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001  the envelope is the contract; nothing may leak past here
        # Class and request id only: a database error's text carries the statement and the
        # bound parameters, which are record fields. No traceback, no message.
        log.error("unhandled exception_class=%s request_id=%s", type(exc).__name__, ctx.request_id)
        response = error_envelope(ErrorCode.INTERNAL, "internal error")
    finally:
        request_context.reset(token)
    response.headers["X-Request-Id"] = ctx.request_id
    # one structured line per request: method, path, status, latency, mode; never whole records
    log.info(
        "method=%s path=%s status=%s latency_ms=%s mode=%s request_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        ctx.elapsed_ms(),
        settings.frontdesk_agent_mode,
        ctx.request_id,
    )
    return response


@app.get(
    API_PREFIX + "/health",
    response_model=Health,
    tags=["core"],
    responses=common_error_responses(),
    description="Lane: plumbing (lead session). Dependency status and versions.",
)
def health() -> Health:  # sync: db_is_up blocks, so it runs in the threadpool, never on the event loop
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
