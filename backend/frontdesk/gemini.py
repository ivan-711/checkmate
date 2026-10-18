"""LIVE adapter: one Gemini function-calling step per ``next_step`` (ADR-016 §1, §8; S0 spike notes).

The ONLY module in the backend that imports ``google.genai``. Schema-only declarations straight
from ``contracts/tools/*.json``, automatic function calling off, temperature 0, SDK retries off
(the loop owns the single retry), one timeout per call. Every failure becomes an ``ErrorStep``;
nothing raises to the loop. Logs carry the exception class and HTTP code only: never ``str(exc)``,
never the key.
"""

from __future__ import annotations

import logging
import time

import httpx
from google.genai import Client, errors, types

from backend.frontdesk.model import ErrorStep, Message, ModelRequest, ModelStep, TextStep, ToolCallStep
from contracts.models.intake import AgentMode
from contracts.version import AUTO_MODE_PROBE_S, MODEL_TIMEOUT_MS

log = logging.getLogger("checkmate.frontdesk.gemini")

SDK_ATTEMPTS = 1  # includes the original call: no SDK retry, the loop retries once itself
# The live API rejects role "tool" for function responses (400, measured at the venue); "user" is accepted.
FUNCTION_RESPONSE_ROLE = "user"
_RETRYABLE_HTTP_MIN = 500
_RATE_LIMITED = 429
_BLOCKED_FINISH = {types.FinishReason.SAFETY: "SAFETY_BLOCKED", types.FinishReason.MALFORMED_FUNCTION_CALL: "MALFORMED"}


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


class GeminiAgentModel:
    mode = AgentMode.LIVE

    def __init__(self, *, api_key: str, model_id: str) -> None:
        self._model_id = model_id
        self._http_options = types.HttpOptions(
            timeout=MODEL_TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=SDK_ATTEMPTS)
        )
        self._client = Client(api_key=api_key, http_options=self._http_options)

    def _config(self, req: ModelRequest) -> types.GenerateContentConfig:
        declarations = [
            types.FunctionDeclaration(
                name=spec["name"], description=spec["description"], parameters_json_schema=spec["parameters"]
            )
            for spec in req.tools
        ]
        return types.GenerateContentConfig(
            system_instruction=req.system_instruction,
            temperature=0,
            tools=[types.Tool(function_declarations=declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            http_options=self._http_options,
        )

    def next_step(self, req: ModelRequest) -> ModelStep:
        started = time.perf_counter()
        try:
            response = self._client.models.generate_content(
                model=self._model_id, contents=contents_from_messages(req.messages), config=self._config(req)
            )
        except httpx.TimeoutException as exc:
            log.warning("gemini timeout exception_class=%s", type(exc).__name__)
            return ErrorStep(kind="TIMEOUT", retryable=True, mode=self.mode)
        except errors.APIError as exc:
            retryable = exc.code == _RATE_LIMITED or (exc.code or 0) >= _RETRYABLE_HTTP_MIN
            log.warning("gemini api error exception_class=%s code=%s", type(exc).__name__, exc.code)
            return ErrorStep(kind="UNAVAILABLE", retryable=retryable, mode=self.mode)
        except httpx.HTTPError as exc:
            log.warning("gemini transport error exception_class=%s", type(exc).__name__)
            return ErrorStep(kind="UNAVAILABLE", retryable=True, mode=self.mode)
        return step_from_response(response, _elapsed_ms(started), self.mode)


def probe_live(*, api_key: str, model_id: str) -> bool:
    """AUTO mode's session-start probe: one metadata read inside AUTO_MODE_PROBE_S. Any failure,
    including the API refusing the short deadline, pins the session to REPLAY (fail closed)."""
    try:
        client = Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(AUTO_MODE_PROBE_S * 1000)))
        client.models.get(model=model_id)
        return True
    except (httpx.HTTPError, errors.APIError) as exc:
        log.warning("gemini probe failed exception_class=%s code=%s", type(exc).__name__, getattr(exc, "code", None))
        return False


def contents_from_messages(messages: tuple[Message, ...]) -> list[types.Content]:
    """Rebuild the conversation for one call: user turns, the model's own tool calls echoed back,
    and one function response per call with the role the live API accepts."""
    contents: list[types.Content] = []
    for m in messages:
        if m.role == "user":
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=m.text or "")]))
        elif m.role == "model":
            if m.tool_call is not None:
                part = types.Part.from_function_call(name=m.tool_call.tool_name, args=dict(m.tool_call.args))
                if m.tool_call.model_call_id:
                    part.function_call.id = m.tool_call.model_call_id
                contents.append(types.Content(role="model", parts=[part]))
            else:
                contents.append(types.Content(role="model", parts=[types.Part.from_text(text=m.text or "")]))
        else:  # function result
            name = m.tool_call.tool_name if m.tool_call is not None else "unknown"
            part = types.Part.from_function_response(name=name, response=m.tool_result or {})
            if m.tool_call is not None and m.tool_call.model_call_id:
                part.function_response.id = m.tool_call.model_call_id
            contents.append(types.Content(role=FUNCTION_RESPONSE_ROLE, parts=[part]))
    return contents


def step_from_response(response: types.GenerateContentResponse, latency_ms: int, mode: AgentMode) -> ModelStep:
    candidates = response.candidates or []
    if not candidates:
        log.warning("gemini empty candidates block_reason=%s", getattr(response.prompt_feedback, "block_reason", None))
        return ErrorStep(kind="SAFETY_BLOCKED", retryable=False, mode=mode)
    first = candidates[0]
    blocked = _BLOCKED_FINISH.get(first.finish_reason)
    if blocked is not None:
        log.warning("gemini finish_reason=%s", first.finish_reason)
        return ErrorStep(kind=blocked, retryable=False, mode=mode)
    calls = response.function_calls or []
    if calls:
        # One step per call: a second call in the same response is asked for again after the first
        # result goes back, so the gate sees every call with the state the previous one left.
        call = calls[0]
        return ToolCallStep(
            tool_name=call.name or "",
            args=dict(call.args or {}),
            model_call_id=call.id,
            latency_ms=latency_ms,
            mode=mode,
        )
    text = (response.text or "").strip()
    if not text:
        return ErrorStep(kind="MALFORMED", retryable=False, mode=mode)
    return TextStep(text=text, latency_ms=latency_ms, mode=mode)
