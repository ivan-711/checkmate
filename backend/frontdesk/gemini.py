"""LIVE adapter: one Gemini function-calling step per ``next_step`` (ADR-016 §1, §8; S0 spike notes).

The ONLY module in the backend that imports ``google.genai``. Schema-only declarations straight
from ``contracts/tools/*.json``, automatic function calling off, temperature 0, SDK retries off
(the loop owns the single retry), one timeout per call. Every failure becomes an ``ErrorStep``;
nothing raises to the loop. Logs carry the exception class and HTTP code only: never ``str(exc)``,
never the key.
"""

from __future__ import annotations

import logging
import math
import time

import httpx
from google.genai import Client, errors, types

from backend.frontdesk.budget import RETRY_AFTER_MAX_S
from backend.frontdesk.model import ErrorStep, Message, ModelRequest, ModelStep, TextStep, ToolCallStep
from contracts.models.intake import AgentMode
from contracts.version import AUTO_MODE_PROBE_S, MODEL_TIMEOUT_MS

log = logging.getLogger("checkmate.frontdesk.gemini")

SDK_ATTEMPTS = 1  # includes the original call: no SDK retry, the loop retries once itself
# The live API rejects role "tool" for function responses (400, measured at the venue); "user" is accepted.
FUNCTION_RESPONSE_ROLE = "user"
_RETRYABLE_HTTP_MIN = 500
_RATE_LIMITED = 429
QUOTA_STATUS = "RESOURCE_EXHAUSTED"
SERVER_TIMEOUT_HEADER = "X-Server-Timeout"
# The API rejects a server deadline under 10 s; the per-call model timeout is that floor (contracts).
PROBE_SERVER_DEADLINE_S = MODEL_TIMEOUT_MS // 1000
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
        try:
            self._client = Client(api_key=api_key, http_options=self._http_options)
        except Exception as exc:  # noqa: BLE001 — a client that cannot be built degrades each step, never a 500
            log.warning("gemini client unavailable exception_class=%s", type(exc).__name__)
            self._client = None

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
        if self._client is None:
            return ErrorStep(kind="UNAVAILABLE", retryable=False, mode=self.mode)
        started = time.perf_counter()
        try:
            response = self._client.models.generate_content(
                model=self._model_id, contents=contents_from_messages(req.messages), config=self._config(req)
            )
            return step_from_response(response, _elapsed_ms(started), self.mode)
        except httpx.TimeoutException as exc:
            log.warning("gemini timeout exception_class=%s", type(exc).__name__)
            return ErrorStep(kind="TIMEOUT", retryable=True, mode=self.mode)
        except errors.APIError as exc:
            log.warning(
                "gemini api error exception_class=%s code=%s status=%s", type(exc).__name__, exc.code, _status(exc)
            )
            return ErrorStep(kind="UNAVAILABLE", retryable=api_error_retryable(exc), mode=self.mode)
        except httpx.HTTPError as exc:
            # ADR-016 §8: the one retry is for a timeout, a 429 that fits, or a 5xx; a transport
            # failure (connection refused, DNS) is none of those.
            log.warning("gemini transport error exception_class=%s", type(exc).__name__)
            return ErrorStep(kind="UNAVAILABLE", retryable=False, mode=self.mode)
        except Exception as exc:  # noqa: BLE001 — a parse or auth error from the library degrades the turn
            # Not retried: an unknown failure is not one of ADR-016 §8's retryable cases.
            log.warning("gemini unexpected error exception_class=%s", type(exc).__name__)
            return ErrorStep(kind="UNAVAILABLE", retryable=False, mode=self.mode)


def retry_after_seconds(exc: errors.APIError) -> float | None:
    """``Retry-After`` from the 429 response: None when absent, ``inf`` when present but not a number
    of seconds (an HTTP-date cannot be shown to fit the retry delay)."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    raw = headers.get("retry-after") if headers is not None else None
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return math.inf


def _status(exc: errors.APIError) -> str | None:
    """The gRPC-style status string (e.g. RESOURCE_EXHAUSTED); never the message body."""
    status = getattr(exc, "status", None)
    return str(status) if status else None


def quota_exhausted(exc: errors.APIError) -> bool:
    """A 429 carrying RESOURCE_EXHAUSTED is the free tier's daily quota (lead decision 19:31): gone
    until the next day, so not worth the one retry."""
    return exc.code == _RATE_LIMITED and QUOTA_STATUS in (_status(exc) or "").upper()


def api_error_retryable(exc: errors.APIError) -> bool:
    """5xx: yes. 429: only when it is not RESOURCE_EXHAUSTED and Retry-After is absent or fits the
    loop's retry delay. Other 4xx: no."""
    code = exc.code or 0
    if code >= _RETRYABLE_HTTP_MIN:
        return True
    if code == _RATE_LIMITED:
        if quota_exhausted(exc):
            return False
        wait = retry_after_seconds(exc)
        return wait is None or wait <= RETRY_AFTER_MAX_S
    return False


def probe_http_options() -> types.HttpOptions:
    """The probe's own options: a short client-side wait (AUTO_MODE_PROBE_S) so session start never
    stalls, and an explicit server deadline. Without the header the SDK derives X-Server-Timeout from
    the client timeout (1.5 s → "2"), and the API rejects any deadline under 10 s, so every probe
    would fail and AUTO could never pin LIVE."""
    return types.HttpOptions(
        timeout=int(AUTO_MODE_PROBE_S * 1000),
        headers={SERVER_TIMEOUT_HEADER: str(PROBE_SERVER_DEADLINE_S)},
        retry_options=types.HttpRetryOptions(attempts=SDK_ATTEMPTS),
    )


def probe_live(*, api_key: str, model_id: str) -> bool:
    """AUTO mode's session-start probe: one cheap metadata read (``models.get`` on the configured
    model id), no generate call, so it spends no generation quota (billing is linked since 19:41).
    Any 429, 403, 404, 5xx, timeout, transport failure or other library error pins the session to
    REPLAY (fail closed)."""
    try:
        client = Client(api_key=api_key, http_options=probe_http_options())
        client.models.get(model=model_id)
        return True
    except errors.APIError as exc:
        log.warning(
            "gemini probe failed exception_class=%s code=%s status=%s", type(exc).__name__, exc.code, _status(exc)
        )
        return False
    except Exception as exc:  # noqa: BLE001 — fail closed: anything else from the library also pins REPLAY
        log.warning("gemini probe failed exception_class=%s", type(exc).__name__)
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
