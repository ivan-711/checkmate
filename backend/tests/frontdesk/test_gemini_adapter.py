"""The LIVE adapter against a fake SDK client: request shape, error mapping, response mapping.

No network, no key: ``Client`` is replaced by a stub whose ``models.generate_content`` is scripted.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from google.genai import errors, types

from backend.frontdesk import gemini
from backend.frontdesk.model import ErrorStep, Message, ModelRequest, TextStep, ToolCallStep
from backend.frontdesk.prompts import PROMPT_VERSION, system_instruction
from backend.frontdesk.tools import tool_declarations
from contracts.models.intake import AgentMode
from contracts.models.policy import Language
from contracts.version import MODEL_TIMEOUT_MS, TOOL_SCHEMA_VERSION


class _Models:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class _Client:
    def __init__(self, outcome):
        self.models = _Models(outcome)


def _adapter(monkeypatch, outcome) -> tuple[gemini.GeminiAgentModel, _Client]:
    client = _Client(outcome)
    monkeypatch.setattr(gemini, "Client", lambda **kwargs: client)
    return gemini.GeminiAgentModel(api_key="not-a-real-key", model_id="fixture-model"), client


def _request(messages=()) -> ModelRequest:
    return ModelRequest(
        session_id=uuid.uuid4(),
        turn_index=0,
        step_index=0,
        language=Language.ES,
        prompt_version=PROMPT_VERSION,
        tool_schema_version=TOOL_SCHEMA_VERSION,
        system_instruction=system_instruction(),
        messages=tuple(messages) or (Message(role="user", text="Hola"),),
        tools=tool_declarations(),
        user_text_folded="hola",
        last_tool_result_sha256=None,
    )


def _response(parts, finish_reason=None):
    content = types.Content(role="model", parts=parts)
    return types.GenerateContentResponse(candidates=[types.Candidate(content=content, finish_reason=finish_reason)])


def test_request_shape_is_the_contract(monkeypatch):
    adapter, client = _adapter(monkeypatch, _response([types.Part.from_text(text="Hola, ¿su nombre?")]))
    step = adapter.next_step(_request())
    assert isinstance(step, TextStep) and step.text == "Hola, ¿su nombre?" and step.mode == AgentMode.LIVE
    call = client.models.calls[0]
    assert call["model"] == "fixture-model"
    config = call["config"]
    assert config.temperature == 0
    assert config.automatic_function_calling.disable is True
    assert config.http_options.timeout == MODEL_TIMEOUT_MS
    assert config.http_options.retry_options.attempts == 1
    names = [d.name for d in config.tools[0].function_declarations]
    assert names == ["search_patients", "propose_new_chart", "attach_history"]
    assert config.tools[0].function_declarations[0].parameters_json_schema == tool_declarations()[0]["parameters"]
    assert config.system_instruction == system_instruction()


def test_function_call_becomes_a_tool_call_step(monkeypatch):
    part = types.Part.from_function_call(name="search_patients", args={"givenName": "Ana", "evidence": {}})
    adapter, _ = _adapter(monkeypatch, _response([part]))
    step = adapter.next_step(_request())
    assert isinstance(step, ToolCallStep)
    assert step.tool_name == "search_patients" and step.args == {"givenName": "Ana", "evidence": {}}


def test_contents_rebuilt_with_user_role_for_function_responses(monkeypatch):
    tc = ToolCallStep(
        tool_name="search_patients", args={"evidence": {}}, model_call_id=None, latency_ms=1, mode=AgentMode.LIVE
    )
    messages = (
        Message(role="user", text="Hola"),
        Message(role="model", tool_call=tc),
        Message(role="function", tool_call=tc, tool_result={"status": "ALLOWED"}),
    )
    adapter, client = _adapter(monkeypatch, _response([types.Part.from_text(text="ok")]))
    adapter.next_step(_request(messages))
    contents = client.models.calls[0]["contents"]
    assert [c.role for c in contents] == ["user", "model", gemini.FUNCTION_RESPONSE_ROLE]
    assert gemini.FUNCTION_RESPONSE_ROLE == "user"
    assert contents[1].parts[0].function_call.name == "search_patients"
    assert contents[2].parts[0].function_response.response == {"status": "ALLOWED"}


@pytest.mark.parametrize(
    "exc, kind, retryable",
    [
        (httpx.ReadTimeout("t"), "TIMEOUT", True),
        (httpx.ConnectTimeout("t"), "TIMEOUT", True),
        (errors.APIError(429, {"error": {"message": "quota"}}), "UNAVAILABLE", True),
        (errors.APIError(503, {"error": {"message": "overloaded"}}), "UNAVAILABLE", True),
        (errors.APIError(504, {"error": {"message": "deadline"}}), "UNAVAILABLE", True),
        (errors.APIError(400, {"error": {"message": "bad"}}), "UNAVAILABLE", False),
        (errors.APIError(404, {"error": {"message": "no model"}}), "UNAVAILABLE", False),
        (httpx.ConnectError("down"), "UNAVAILABLE", False),
    ],
)
def test_errors_become_error_steps(monkeypatch, exc, kind, retryable):
    """ADR-016 §8: the one retry only for a timeout, a 429 that fits, or a 5xx; never another 4xx or a
    transport failure."""
    adapter, _ = _adapter(monkeypatch, exc)
    step = adapter.next_step(_request())
    assert step == ErrorStep(kind=kind, retryable=retryable, mode=AgentMode.LIVE)


def _rate_limited(retry_after: str | None, status: str | None = None) -> errors.APIError:
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    response = httpx.Response(429, headers=headers, request=httpx.Request("POST", "https://example.invalid"))
    body = {"error": {"message": "quota", "status": status}} if status else {"error": {"message": "quota"}}
    return errors.APIError(429, body, response)


def test_429_resource_exhausted_degrades_at_once_without_a_retry(monkeypatch, caplog):
    """Lead decision 19:31: the free tier's daily quota is gone until tomorrow; the retry is wasted."""
    adapter, _ = _adapter(monkeypatch, _rate_limited(None, "RESOURCE_EXHAUSTED"))
    with caplog.at_level("WARNING", logger="checkmate.frontdesk.gemini"):
        step = adapter.next_step(_request())
    assert step == ErrorStep(kind="UNAVAILABLE", retryable=False, mode=AgentMode.LIVE)
    assert "status=RESOURCE_EXHAUSTED" in caplog.text and "quota" not in caplog.text


def test_429_resource_exhausted_with_a_short_retry_after_is_still_not_retried(monkeypatch):
    adapter, _ = _adapter(monkeypatch, _rate_limited("1", "RESOURCE_EXHAUSTED"))
    assert adapter.next_step(_request()).retryable is False


@pytest.mark.parametrize(
    "retry_after, retryable", [(None, True), ("1", True), ("0.5", True), ("20", False), ("Wed, 21 Oct", False)]
)
def test_429_is_retried_only_when_retry_after_fits_the_retry_delay(monkeypatch, retry_after, retryable):
    adapter, _ = _adapter(monkeypatch, _rate_limited(retry_after))
    assert adapter.next_step(_request()).retryable is retryable


def test_blocked_and_malformed_finish_reasons(monkeypatch):
    adapter, _ = _adapter(monkeypatch, types.GenerateContentResponse(candidates=[]))
    assert adapter.next_step(_request()).kind == "SAFETY_BLOCKED"
    adapter, _ = _adapter(monkeypatch, _response([types.Part.from_text(text="")], types.FinishReason.SAFETY))
    assert adapter.next_step(_request()).kind == "SAFETY_BLOCKED"
    adapter, _ = _adapter(
        monkeypatch, _response([types.Part.from_text(text="")], types.FinishReason.MALFORMED_FUNCTION_CALL)
    )
    assert adapter.next_step(_request()).kind == "MALFORMED"


def test_error_logs_never_carry_the_message_or_the_key(monkeypatch, caplog):
    adapter, _ = _adapter(monkeypatch, errors.APIError(503, {"error": {"message": "SECRET-DETAILS"}}))
    with caplog.at_level("WARNING", logger="checkmate.frontdesk.gemini"):
        adapter.next_step(_request())
    assert "SECRET-DETAILS" not in caplog.text and "not-a-real-key" not in caplog.text
    assert "code=503" in caplog.text


class _ProbeModels:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome

    def get(self, **kwargs):
        raise AssertionError("the probe must make a real generate call, not a metadata read")


class _ProbeClient:
    def __init__(self, outcome):
        self.models = _ProbeModels(outcome)


def _auto_settings(key_present: bool = True, model_id: str | None = "fixture-model"):
    from backend.app.config import Settings

    return Settings(
        database_url="unused",
        cors_origins=(),
        frontdesk_agent_mode="AUTO",
        gemini_model_id=model_id,
        gemini_api_key_present=key_present,
        capture_dir=None,
        git_sha=None,
    )


def test_auto_pins_replay_on_a_probe_429_resource_exhausted(monkeypatch):
    from backend.frontdesk import adapters

    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    client = _ProbeClient(errors.APIError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}}))
    monkeypatch.setattr(gemini, "Client", lambda **kwargs: client)
    assert adapters.pin_mode(_auto_settings()) == AgentMode.REPLAY
    assert len(client.models.calls) == 1  # one real generate call, one request of the daily quota


@pytest.mark.parametrize(
    "outcome",
    [
        errors.APIError(429, {"error": {"message": "per-minute"}}),
        errors.APIError(503, {"error": {"message": "overloaded"}}),
        errors.APIError(400, {"error": {"message": "deadline too short"}}),
        httpx.ReadTimeout("t"),
        httpx.ConnectError("down"),
    ],
)
def test_auto_pins_replay_on_any_probe_failure(monkeypatch, outcome):
    from backend.frontdesk import adapters

    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    monkeypatch.setattr(gemini, "Client", lambda **kwargs: _ProbeClient(outcome))
    assert adapters.pin_mode(_auto_settings()) == AgentMode.REPLAY


def test_auto_pins_live_only_when_the_probe_generate_call_answers(monkeypatch):
    from backend.frontdesk import adapters

    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    client = _ProbeClient(_response([types.Part.from_text(text="ok")]))
    monkeypatch.setattr(gemini, "Client", lambda **kwargs: client)
    assert adapters.pin_mode(_auto_settings()) == AgentMode.LIVE
    assert client.models.calls[0]["model"] == "fixture-model"


def test_auto_pins_replay_without_a_key_or_model_id_and_never_probes(monkeypatch):
    from backend.frontdesk import adapters

    def explode(**kwargs):
        raise AssertionError("no probe without a key and a model id")

    monkeypatch.setattr(gemini, "Client", explode)
    assert adapters.pin_mode(_auto_settings(key_present=False)) == AgentMode.REPLAY
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    assert adapters.pin_mode(_auto_settings(model_id=None)) == AgentMode.REPLAY
