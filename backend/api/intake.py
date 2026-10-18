"""The three FrontDesk routes (ADR-016; contracts/api_spec.py ``frontdesk`` tag).

POST /intake-sessions            201 IntakeSession; the server pins the agent mode (never the client)
POST /intake-sessions/{id}/turns 201 IntakeTurn; Idempotency-Key required (422 when missing, as reviews)
GET  /intake-sessions/{id}       IntakeSession with turns and the derived registration

The model adapter comes from the ``get_model_factory`` dependency (``adapters.make_model`` by
default); tests override it with ``app.dependency_overrides`` to inject a scripted fake.
"""

from __future__ import annotations

import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.app.deps import EngineDep, SettingsDep
from backend.app.errors import ApiError
from backend.app.openapi_meta import common_error_responses, error_responses
from backend.frontdesk import adapters, loop, registration, store
from backend.frontdesk.audit import event_mode, write_agent_event
from backend.frontdesk.prompts import PROMPT_VERSION
from contracts.api_spec import IdempotencyKey
from contracts.models.common import ErrorCode, EventType
from contracts.models.events import Versions
from contracts.models.intake import AgentMode, CreateIntakeSessionRequest, IntakeSession, IntakeTurn, TurnRequest
from contracts.models.policy import Language
from contracts.version import API_PREFIX, TOOL_SCHEMA_VERSION

router = APIRouter(prefix=API_PREFIX, tags=["frontdesk"])

DEFAULT_LANGUAGE = Language.EN

# JSON lets a string carry U+0000 and the frozen schema allows it, but Postgres text and jsonb cannot hold
# it: the insert raised DataError, a 500 (CI schemathesis). Only NUL is refused; every other schema-valid
# string is kept. (An unpaired surrogate never gets this far: Pydantic rejects it as a 422.)
_NUL = "\x00"


def get_model_factory() -> adapters.ModelFactory:
    return adapters.make_model


ModelFactoryDep = Annotated[adapters.ModelFactory, Depends(get_model_factory)]


def reject_unstorable_text(field: str, value: str | None) -> None:
    """Checklist 13: validate at the boundary, before any row, event or model call; 422, never a 500."""
    if value is not None and _NUL in value:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, f"{field} contains a character that cannot be stored", {"field": field}
        )


def _session_view(conn, session_id: UUID) -> IntakeSession:
    session = store.read_session(conn, session_id)
    if session is None:
        raise ApiError(ErrorCode.NOT_FOUND, "intake session not found")
    turns = [
        IntakeTurn.model_validate(t.response)
        for t in store.read_turns(conn, session_id)
        if t.status == "COMPLETED" and t.response
    ]
    return IntakeSession(
        id=session.id,
        created_at=session.created_at,
        language=session.language,
        agent_mode=session.agent_mode,
        registration=registration.derive(conn, session_id),
        turns=turns,
        closed=session.closed,
        prompt_version=session.prompt_version,
        tool_schema_version=session.tool_schema_version,
    )


@router.post(
    "/intake-sessions",
    response_model=IntakeSession,
    status_code=201,
    responses=error_responses(ErrorCode.NOT_FOUND) | common_error_responses(),
    description="Lane Q1.2. Start an intake; the server pins the agent mode from FRONTDESK_AGENT_MODE.",
)
def create_intake_session(body: CreateIntakeSessionRequest, engine: EngineDep, settings: SettingsDep):
    reject_unstorable_text("scenarioContextId", body.scenario_context_id)
    session_id = uuid.uuid4()
    language = body.language or DEFAULT_LANGUAGE
    mode = adapters.pin_mode(settings)
    model_id = settings.gemini_model_id if mode == AgentMode.LIVE else None
    with engine.begin() as conn:
        store.insert_session(
            conn,
            session_id=session_id,
            language=language,
            agent_mode=mode,
            scenario_context_id=body.scenario_context_id,
            prompt_version=PROMPT_VERSION,
            tool_schema_version=TOOL_SCHEMA_VERSION,
            model_id=model_id,
        )
        write_agent_event(
            conn,
            event_type=EventType.INTAKE_STARTED,
            intake_session_id=session_id,
            mode=event_mode(mode),
            outcome=mode.value,
            versions=Versions(
                prompt_version=PROMPT_VERSION, tool_schema_version=TOOL_SCHEMA_VERSION, model_id=model_id
            ),
            payload={"language": language.value, "scenarioContextId": body.scenario_context_id},
        )
        return _session_view(conn, session_id)


@router.post(
    "/intake-sessions/{session_id}/turns",
    response_model=IntakeTurn,
    status_code=201,
    responses=error_responses(
        ErrorCode.NOT_FOUND, ErrorCode.TURN_IN_PROGRESS, ErrorCode.SESSION_CLOSED, ErrorCode.IDEMPOTENCY_MISMATCH
    )
    | common_error_responses(),
    description="Lane Q1.2 (gate: Q1.1). One typed message runs the agent loop. Idempotency-Key required.",
)
def create_intake_turn(
    session_id: UUID,
    body: TurnRequest,
    idempotency_key: IdempotencyKey,
    engine: EngineDep,
    settings: SettingsDep,
    model_factory: ModelFactoryDep,
):
    reject_unstorable_text("text", body.text)
    with engine.connect() as conn:
        session = store.read_session(conn, session_id)
    if session is None:
        raise ApiError(ErrorCode.NOT_FOUND, "intake session not found")
    model = model_factory(session.agent_mode, settings)
    status_code, response = loop.run_turn(engine, model, session_id=session_id, key=idempotency_key, body=body)
    return JSONResponse(status_code=status_code, content=response)


@router.get(
    "/intake-sessions/{session_id}",
    response_model=IntakeSession,
    responses=error_responses(ErrorCode.NOT_FOUND) | common_error_responses(),
    description="Lane Q1.2. Transcript, tool calls and derived registration state, for reload and the registrar.",
)
def get_intake_session(session_id: UUID, engine: EngineDep):
    with engine.connect() as conn:
        return _session_view(conn, session_id)
