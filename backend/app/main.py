"""CheckMate API process: 127.0.0.1 only, one pool, error envelope, request log line.

Starts from the frozen stub app so every unimplemented route answers 501 with the
contract's error envelope; lanes replace routes one at a time.
"""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from backend.app.config import load_settings
from backend.app.db import db_is_up, make_engine
from contracts.api_spec import build_app, error_envelope
from contracts.models.common import ErrorCode
from contracts.models.health import AgentStatus, DependencyStatus, Health, HealthVersions
from contracts.version import API_PREFIX, CONTRACT_VERSION, POLICY_VERSION, TOOL_SCHEMA_VERSION

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("checkmate.request")
settings = load_settings()
engine = make_engine(settings.database_url)
# Routes the backend implements for real; their stubs are dropped. Lanes add to this set.
IMPLEMENTED = frozenset({("GET", API_PREFIX + "/health")})
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
def health() -> Health:  # sync on purpose: the DB ping uses the sync pool, so it runs in the threadpool
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
