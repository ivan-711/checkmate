"""The LIVE adapter against a fake SDK client: request shape, error mapping, response mapping.

No network, no key: ``Client`` is replaced by a stub whose ``models.generate_content`` is scripted.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from google.genai import errors, types
from google.genai._api_client import get_timeout_in_seconds, populate_server_timeout_header

from backend.frontdesk import gemini
from backend.frontdesk.model import ErrorStep, Message, ModelRequest, TextStep, ToolCallStep
from backend.frontdesk.prompts import PROMPT_VERSION, system_instruction
from backend.frontdesk.tools import tool_declarations
from contracts.models.intake import AgentMode
from contracts.models.policy import Language
from contracts.version import AUTO_MODE_PROBE_S, MODEL_TIMEOUT_MS, TOOL_SCHEMA_VERSION


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


class _ScriptedModels:
    """Answers each generate call with the next scripted response and keeps the contents it was sent."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _scripted_adapter(monkeypatch, responses) -> tuple[gemini.GeminiAgentModel, _ScriptedModels]:
    client = _Client(None)
    client.models = _ScriptedModels(responses)
    monkeypatch.setattr(gemini, "Client", lambda **kwargs: client)
    return gemini.GeminiAgentModel(api_key="not-a-real-key", model_id="fixture-model"), client.models


def _signed_call(name: str, signature: bytes, call_id: str) -> types.Part:
    return types.Part(
        function_call=types.FunctionCall(name=name, args={"evidence": {}}, id=call_id), thought_signature=signature
    )


def _second_call_contents(monkeypatch, first_parts) -> tuple[types.Content, list[types.Content]]:
    """Run two steps the way the loop does: the tool call, then the tool result sent back."""
    first = _response(first_parts)
    adapter, models = _scripted_adapter(monkeypatch, [first, _response([types.Part.from_text(text="Gracias")])])
    user = Message(role="user", text="Me llamo Sofia")
    step = adapter.next_step(_request((user,)))
    assert isinstance(step, ToolCallStep)
    adapter.next_step(
        _request(
            (
                user,
                Message(role="model", tool_call=step),
                Message(role="function", tool_call=step, tool_result={"status": "ALLOWED"}),
            )
        )
    )
    return first.candidates[0].content, models.calls[1]["contents"]


def test_second_call_echoes_the_models_function_call_content_with_its_thought_signature(monkeypatch):
    """Measured live 20:36 (gemini-3.6-flash): rebuilding the call without its thought signature gets
    400 INVALID_ARGUMENT "Function call is missing a thought_signature in functionCall parts" on the
    second call of every turn. The model's own Content goes back unchanged within the turn."""
    original, contents = _second_call_contents(
        monkeypatch, [_signed_call("search_patients", b"opaque-signature", "call-1")]
    )
    assert [c.role for c in contents] == ["user", "model", gemini.FUNCTION_RESPONSE_ROLE]
    assert contents[1] == original
    assert contents[1].parts[0].thought_signature == b"opaque-signature"
    assert contents[2].parts[0].function_response.id == "call-1"
    assert contents[2].parts[0].function_response.name == "search_patients"


def test_parallel_calls_echo_only_the_first_call_so_counts_match(monkeypatch):
    """The loop answers one call per step; the API needs one response per call it is shown, and only
    the first call of a parallel set carries the signature."""
    thought = types.Part(text="plan", thought=True)
    first = _signed_call("search_patients", b"sig-first", "call-1")
    second = types.Part(function_call=types.FunctionCall(name="propose_new_chart", args={}, id="call-2"))
    _, contents = _second_call_contents(monkeypatch, [thought, first, second])
    assert contents[1].parts == [thought, first]
    assert [c.role for c in contents] == ["user", "model", gemini.FUNCTION_RESPONSE_ROLE]


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

    def get(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome

    def generate_content(self, **kwargs):
        raise AssertionError("the probe is a metadata read (models.get), never a generate call")


class _ProbeClient:
    def __init__(self, outcome):
        self.models = _ProbeModels(outcome)
        self.http_options: types.HttpOptions | None = None


def _install_probe_client(monkeypatch, outcome) -> _ProbeClient:
    client = _ProbeClient(outcome)

    def build(**kwargs):
        client.http_options = kwargs.get("http_options")
        return client

    monkeypatch.setattr(gemini, "Client", build)
    return client


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


def test_probe_is_one_models_get_with_a_short_client_timeout_and_a_10s_server_deadline(monkeypatch):
    """Second layer, blocking 1: a 1.5 s HttpOptions.timeout alone makes the SDK send
    X-Server-Timeout: 2, which the API rejects (deadlines under 10 s), so AUTO could never pin LIVE.
    The probe is a metadata read with the 1.5 s client timeout and an explicit 10 s server deadline."""
    from backend.frontdesk import adapters

    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    client = _install_probe_client(monkeypatch, types.Model(name="models/fixture-model"))
    assert adapters.pin_mode(_auto_settings()) == AgentMode.LIVE
    assert client.models.calls == [{"model": "fixture-model"}]
    opts = client.http_options
    assert opts.timeout == int(AUTO_MODE_PROBE_S * 1000)
    assert opts.retry_options.attempts == 1
    assert int(opts.headers["X-Server-Timeout"]) >= MODEL_TIMEOUT_MS // 1000 >= 10
    # The SDK keeps a header already set and only fills it in from the client timeout when absent.
    headers = dict(opts.headers)
    populate_server_timeout_header(headers, get_timeout_in_seconds(opts.timeout))
    assert int(headers["X-Server-Timeout"]) >= 10


def test_auto_pins_replay_on_a_probe_429_resource_exhausted(monkeypatch):
    from backend.frontdesk import adapters

    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    client = _install_probe_client(
        monkeypatch, errors.APIError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}})
    )
    assert adapters.pin_mode(_auto_settings()) == AgentMode.REPLAY
    assert len(client.models.calls) == 1


@pytest.mark.parametrize(
    "outcome",
    [
        errors.APIError(429, {"error": {"message": "per-minute"}}),
        errors.APIError(403, {"error": {"message": "denied"}}),
        errors.APIError(404, {"error": {"message": "no such model"}}),
        errors.APIError(500, {"error": {"message": "internal"}}),
        errors.APIError(503, {"error": {"message": "overloaded"}}),
        errors.APIError(400, {"error": {"message": "deadline too short"}}),
        httpx.ReadTimeout("t"),
        httpx.ConnectError("down"),
        ValueError("unparseable model metadata"),
        RuntimeError("anything else from the library"),
    ],
)
def test_auto_pins_replay_on_any_probe_failure(monkeypatch, outcome):
    from backend.frontdesk import adapters

    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    client = _install_probe_client(monkeypatch, outcome)
    assert adapters.pin_mode(_auto_settings()) == AgentMode.REPLAY
    assert len(client.models.calls) == 1


def test_auto_pins_replay_when_the_client_cannot_be_built(monkeypatch):
    from backend.frontdesk import adapters

    def broken(**kwargs):
        raise ValueError("bad client options")

    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    monkeypatch.setattr(gemini, "Client", broken)
    assert adapters.pin_mode(_auto_settings()) == AgentMode.REPLAY


def test_auto_pins_replay_without_a_key_or_model_id_and_never_probes(monkeypatch):
    from backend.frontdesk import adapters

    def explode(**kwargs):
        raise AssertionError("no probe without a key and a model id")

    monkeypatch.setattr(gemini, "Client", explode)
    assert adapters.pin_mode(_auto_settings(key_present=False)) == AgentMode.REPLAY
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    assert adapters.pin_mode(_auto_settings(model_id=None)) == AgentMode.REPLAY


@pytest.mark.parametrize("outcome", [RuntimeError("boom SECRET-DETAILS"), ValueError("bad SECRET-DETAILS"), object()])
def test_any_other_library_exception_degrades_instead_of_raising(monkeypatch, caplog, outcome):
    """Second layer, item 3: a parse error, an auth error or anything else from the library (or a
    response the mapper cannot read) is an ErrorStep, never an exception and never a 500."""
    adapter, _ = _adapter(monkeypatch, outcome)
    with caplog.at_level("WARNING", logger="checkmate.frontdesk.gemini"):
        step = adapter.next_step(_request())
    assert step == ErrorStep(kind="UNAVAILABLE", retryable=False, mode=AgentMode.LIVE)
    assert "SECRET-DETAILS" not in caplog.text and "not-a-real-key" not in caplog.text


def test_a_client_that_cannot_be_built_degrades_every_step(monkeypatch):
    def broken(**kwargs):
        raise ValueError("bad client options")

    monkeypatch.setattr(gemini, "Client", broken)
    adapter = gemini.GeminiAgentModel(api_key="not-a-real-key", model_id="fixture-model")
    assert adapter.next_step(_request()) == ErrorStep(kind="UNAVAILABLE", retryable=False, mode=AgentMode.LIVE)
