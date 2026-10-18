"""REPLAY adapter: plays a committed model transcript through the real engine (ADR-016 §7).

Only the model is replayed. The executor, matcher, gate, writes and audit rows run for real, so a
replayed step is never played on top of a different engine state: the typed text must fold to the
recorded text (else ``REPLAY_INPUT_MISMATCH``) and the live ToolResult hash of the previous step
must equal the recorded one (else ``REPLAY_DIVERGED``). Both fail closed into the template turn.

Also here: ``load_transcript`` (validated pins), ``transcript_sha256`` (stamped on audit rows) and
``RecordingAgentModel``, which wraps a live adapter and writes the same format with ``kind: RECORDED``.

Author: Christian Flores (Q1.4 builder).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, ValidationError, model_validator

from backend.frontdesk.model import AgentModel, ErrorStep, ModelRequest, ModelStep, TextStep, ToolCallStep
from backend.policy.args import fold  # the grounding check's fold: replay matching must agree with it
from contracts.models.common import ContractModel
from contracts.models.health import AgentStatus
from contracts.models.intake import AgentMode
from contracts.models.policy import PolicyOutcome, PolicyReason
from contracts.version import REPLAY_PACING_CAP_MS

log = logging.getLogger("checkmate.frontdesk.replay")

TRANSCRIPT_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[2]
HERO_DIR = REPO_ROOT / "data" / "scenarios" / "hero"
DEFAULT_TRANSCRIPT_PATH = HERO_DIR / "frontdesk_transcript.json"
TRANSCRIPT_PATH_ENV = "FRONTDESK_TRANSCRIPT"  # override for tests and rehearsals
PACING_ENV = "FRONTDESK_REPLAY_PACING"  # "0" turns the latency pacing off (tests); default on
RECORD_TO_ENV = "FRONTDESK_RECORD_TO"  # when set in LIVE mode, the live adapter is wrapped and recorded here
_OFF_VALUES = frozenset({"0", "false", "no", "off"})

_SHA256_RE = r"^[0-9a-f]{64}$"
Sha256 = Annotated[str, Field(pattern=_SHA256_RE)]

__all__ = ["fold"]  # re-exported so the authoring script and tests fold exactly as the gate does


class TranscriptError(ValueError):
    """The transcript file is missing, unreadable or fails validation. Raised at load, never at playback."""


class ToolCallModelStep(ContractModel):
    type: Literal["TOOL_CALL"]
    tool_name: str
    args: dict
    model_call_id: str | None = None


class TextModelStep(ContractModel):
    type: Literal["TEXT"]
    text: str


class StepExpect(ContractModel):
    """What the engine is expected to answer. ``tool_result_sha256`` may be null in AUTHORED
    transcripts (the hash is only known once the step has run through the real engine)."""

    gate_outcome: PolicyOutcome | None = None
    reason_code: PolicyReason | None = None
    tool_result_sha256: Sha256 | None = None


class TranscriptStep(ContractModel):
    step_index: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    model: Annotated[ToolCallModelStep | TextModelStep, Field(discriminator="type")]
    expect: StepExpect | None = None


class TranscriptTurn(ContractModel):
    turn_index: int = Field(ge=0)
    user_text: str
    user_text_folded: str
    steps: list[TranscriptStep] = Field(min_length=1)

    @model_validator(mode="after")
    def _steps_are_contiguous(self) -> TranscriptTurn:
        if [s.step_index for s in self.steps] != list(range(len(self.steps))):
            raise ValueError("stepIndex must run 0..n-1 in order")
        return self


class Transcript(ContractModel):
    transcript_version: Literal[1]
    kind: Literal["RECORDED", "AUTHORED"]
    recorded_at: datetime
    model_id: str
    prompt_version: str
    tool_schema_version: str
    scorer_version: str
    threshold_set_id: str
    hero_scenario_sha256: Sha256
    scenario_context_id: str
    authoring: dict | None = Field(default=None, description="AUTHORED only: constructed flag and note")
    turns: list[TranscriptTurn]

    @model_validator(mode="after")
    def _scripts_are_unique(self) -> Transcript:
        # Several scripts (ES/EN, returning/new patient) share turnIndex 0 because every session
        # starts there; the typed text picks the script, so (turnIndex, folded text) must be unique.
        seen = [(t.turn_index, fold(t.user_text_folded)) for t in self.turns]
        if len(set(seen)) != len(seen):
            raise ValueError("(turnIndex, userTextFolded) must be unique")
        return self

    def has_turn(self, index: int) -> bool:
        return any(t.turn_index == index for t in self.turns)

    def turn(self, index: int, user_text_folded: str) -> TranscriptTurn | None:
        wanted = fold(user_text_folded)
        return next((t for t in self.turns if t.turn_index == index and fold(t.user_text_folded) == wanted), None)


def transcript_path(env: dict[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    return Path(source.get(TRANSCRIPT_PATH_ENV) or DEFAULT_TRANSCRIPT_PATH)


def load_transcript(path: Path | str) -> Transcript:
    try:
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
        return Transcript.model_validate(data)
    except (OSError, ValueError, ValidationError) as exc:  # json.JSONDecodeError is a ValueError
        raise TranscriptError(f"transcript at {path}: {type(exc).__name__}") from exc


def transcript_sha256(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _diverged() -> ErrorStep:
    return ErrorStep(kind="REPLAY_DIVERGED", retryable=False, mode=AgentMode.REPLAY)


def _input_mismatch() -> ErrorStep:
    return ErrorStep(kind="REPLAY_INPUT_MISMATCH", retryable=False, mode=AgentMode.REPLAY)


class ReplayAgentModel:
    """``AgentModel`` that answers from a transcript. Never raises: every failure is an ``ErrorStep``."""

    mode: AgentMode = AgentMode.REPLAY

    def __init__(
        self,
        transcript: Transcript,
        pacing: bool = True,
        sleep: Callable[[float], None] = time.sleep,
        transcript_sha256: str | None = None,
    ) -> None:
        self.transcript = transcript
        self.pacing = pacing
        self._sleep = sleep
        self.transcript_sha256 = transcript_sha256  # the loop stamps it on AGENT_TOOL_CALLED versions

    def next_step(self, req: ModelRequest) -> ModelStep:
        try:
            return self._next_step(req)
        except Exception:
            log.exception("replay step failed turn=%s step=%s", req.turn_index, req.step_index)
            return _diverged()

    def _next_step(self, req: ModelRequest) -> ModelStep:
        if not self.transcript.has_turn(req.turn_index):
            return _diverged()
        turn = self.transcript.turn(req.turn_index, req.user_text_folded)
        if turn is None:
            return _input_mismatch()
        if req.step_index < 0 or req.step_index >= len(turn.steps):  # a negative index must never play steps[-1]
            return _diverged()
        if req.step_index > 0 and not self._previous_result_matches(turn, req):
            return _diverged()
        step = turn.steps[req.step_index]
        self._pace(step.latency_ms)
        return _to_model_step(step)

    @staticmethod
    def _previous_result_matches(turn: TranscriptTurn, req: ModelRequest) -> bool:
        expect = turn.steps[req.step_index - 1].expect
        expected = expect.tool_result_sha256 if expect else None
        if expected is None:  # AUTHORED transcripts may omit the hash; nothing to compare against
            return True
        return req.last_tool_result_sha256 == expected

    def _pace(self, latency_ms: int) -> None:
        if not self.pacing:
            return
        try:
            self._sleep(min(latency_ms, REPLAY_PACING_CAP_MS) / 1000)
        except Exception:  # noqa: BLE001  pacing is cosmetic; a failing clock must not lose the step
            return


def _to_model_step(step: TranscriptStep) -> ToolCallStep | TextStep:
    model = step.model
    if isinstance(model, ToolCallModelStep):
        return ToolCallStep(
            tool_name=model.tool_name,
            args=model.args,
            model_call_id=model.model_call_id,
            latency_ms=step.latency_ms,
            mode=AgentMode.REPLAY,
        )
    return TextStep(text=model.text, latency_ms=step.latency_ms, mode=AgentMode.REPLAY)


class TranscriptPins(ContractModel):
    """Engine versions a recording is pinned to; the wiring fills them from the running engine."""

    model_id: str
    scorer_version: str
    threshold_set_id: str
    hero_scenario_sha256: Sha256
    scenario_context_id: str


class RecordingAgentModel:
    """Wraps a live adapter and writes every answered step into a RECORDED transcript.

    The previous step's ToolResult hash arrives on the *next* request (``last_tool_result_sha256``),
    so it is written back into ``expect`` of step j-1 when step j is requested. ``ErrorStep`` answers
    are not recorded: they are not model output and the loop degrades the turn anyway. The file is
    rewritten after every step so a crash mid-session leaves a valid prefix on disk, and an existing
    RECORDED file at ``out_path`` is resumed, because the routes build a fresh adapter per turn.
    """

    def __init__(self, inner: AgentModel, out_path: Path | str, pins: TranscriptPins) -> None:
        self.inner = inner
        self.mode = inner.mode
        self.out_path = Path(out_path)
        self.pins = pins
        self._turns: dict[tuple[int, str], TranscriptTurn] = {}  # keyed like Transcript.turn()
        self._started_at = datetime.now(UTC)
        self._prompt_version: str | None = None  # pinned from the first request; the loop never changes them
        self._tool_schema_version: str | None = None
        self._resume()

    def _resume(self) -> None:
        if not self.out_path.exists():
            return
        try:
            previous = load_transcript(self.out_path)
        except TranscriptError:
            log.warning("recording at %s is not a valid transcript; starting over", self.out_path)
            return
        if previous.kind != "RECORDED":
            return  # never append a live run onto an authored file
        self._turns = {(t.turn_index, fold(t.user_text_folded)): t for t in previous.turns}
        self._started_at = previous.recorded_at
        self._prompt_version = previous.prompt_version
        self._tool_schema_version = previous.tool_schema_version

    def next_step(self, req: ModelRequest) -> ModelStep:
        step = self.inner.next_step(req)
        if isinstance(step, ErrorStep):
            return step
        try:
            self._record(req, step)
        except Exception:  # noqa: BLE001  recording must never cost the live turn
            log.warning("recording step failed turn=%s step=%s", req.turn_index, req.step_index)
        return step

    def _record(self, req: ModelRequest, step: ToolCallStep | TextStep) -> None:
        self._prompt_version = self._prompt_version or req.prompt_version
        self._tool_schema_version = self._tool_schema_version or req.tool_schema_version
        key = (req.turn_index, fold(req.user_text_folded))
        turn = self._turns.get(key)
        if turn is None or req.step_index == 0:  # a new session re-records the script from its first step
            turn = TranscriptTurn(
                turn_index=req.turn_index,
                user_text=_last_user_text(req) or req.user_text_folded,
                user_text_folded=fold(req.user_text_folded),
                steps=[_from_model_step(req, step)],
            )
            self._turns[key] = turn
        else:
            if req.step_index > 0 and req.step_index - 1 < len(turn.steps):
                previous = turn.steps[req.step_index - 1]
                previous.expect = _expect_from_request(req, previous.expect)
            turn.steps.append(_from_model_step(req, step))
        self._write()

    def transcript(self) -> Transcript:
        return Transcript(
            transcript_version=TRANSCRIPT_VERSION,
            kind="RECORDED",
            recorded_at=self._started_at,
            model_id=self.pins.model_id,
            prompt_version=self._prompt_version or "fd-prompt/unknown",
            tool_schema_version=self._tool_schema_version or "fd-tools/unknown",
            scorer_version=self.pins.scorer_version,
            threshold_set_id=self.pins.threshold_set_id,
            hero_scenario_sha256=self.pins.hero_scenario_sha256,
            scenario_context_id=self.pins.scenario_context_id,
            turns=[self._turns[k] for k in sorted(self._turns)],
        )

    def _write(self) -> None:
        body = json.dumps(self.transcript().model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2)
        tmp = self.out_path.with_suffix(self.out_path.suffix + ".tmp")
        tmp.write_text(body + "\n", encoding="utf-8")
        os.replace(tmp, self.out_path)  # atomic on POSIX: readers never see a half-written file


def _last_user_text(req: ModelRequest) -> str | None:
    for message in reversed(req.messages):
        if message.role == "user" and message.text is not None:
            return message.text
    return None


def _expect_from_request(req: ModelRequest, previous: StepExpect | None) -> StepExpect:
    """Fill the previous step's expectation from what the loop fed back: the result hash and, when the
    function message is present, the gate's status and reason."""
    gate_outcome = previous.gate_outcome if previous else None
    reason_code = previous.reason_code if previous else None
    for message in reversed(req.messages):
        if message.role == "function" and isinstance(message.tool_result, dict):
            status = message.tool_result.get("status")
            gate_outcome = {"ALLOWED": PolicyOutcome.ALLOW, "DENIED": PolicyOutcome.DENY}.get(status, gate_outcome)
            raw_reason = message.tool_result.get("reasonCode")
            reason_code = PolicyReason(raw_reason) if raw_reason in PolicyReason.__members__ else reason_code
            break
    return StepExpect(
        gate_outcome=gate_outcome, reason_code=reason_code, tool_result_sha256=req.last_tool_result_sha256
    )


def _from_model_step(req: ModelRequest, step: ToolCallStep | TextStep) -> TranscriptStep:
    if isinstance(step, ToolCallStep):
        model: ToolCallModelStep | TextModelStep = ToolCallModelStep(
            type="TOOL_CALL", tool_name=step.tool_name, args=step.args, model_call_id=step.model_call_id
        )
    else:
        model = TextModelStep(type="TEXT", text=step.text)
    return TranscriptStep(step_index=req.step_index, latency_ms=step.latency_ms, model=model, expect=None)


# Wiring used by adapters.make_model and the /health route. Only the transcript path, the pacing
# switch and the recording path come from the environment; everything else is in Settings.


def pacing_enabled(env: dict[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    return (source.get(PACING_ENV) or "1").strip().lower() not in _OFF_VALUES


def build_replay_model(env: dict[str, str] | None = None) -> ReplayAgentModel | None:
    """The REPLAY adapter for the configured transcript, or None (logged) when it does not load.
    The caller degrades to an unavailable adapter: a broken transcript fails closed, never raises."""
    path = transcript_path(env)
    try:
        return ReplayAgentModel(
            load_transcript(path), pacing=pacing_enabled(env), transcript_sha256=transcript_sha256(path)
        )
    except TranscriptError as exc:
        log.warning("REPLAY transcript unavailable: %s", exc)
        return None


def pins_from_hero_dir(hero_dir: Path, model_id: str) -> TranscriptPins:
    """Recording pins from the committed hero files, so a recording is pinned exactly as the authored one."""
    hero = json.loads((hero_dir / "hero.json").read_text(encoding="utf-8"))
    intake = json.loads((hero_dir / "frontdesk_intake.json").read_text(encoding="utf-8"))
    return TranscriptPins(
        model_id=model_id,
        scorer_version=hero["scorerVersion"],
        threshold_set_id=hero["thresholdsId"],
        hero_scenario_sha256=hashlib.sha256((hero_dir / "scenario.json").read_bytes()).hexdigest(),
        scenario_context_id=intake["scenarioContextId"],
    )


def maybe_record(inner: AgentModel, model_id: str, env: dict[str, str] | None = None) -> AgentModel:
    """Wrap a LIVE adapter in a recorder when FRONTDESK_RECORD_TO names an output file."""
    source = os.environ if env is None else env
    out = source.get(RECORD_TO_ENV)
    if not out:
        return inner
    try:
        pins = pins_from_hero_dir(HERO_DIR, model_id)
    except (OSError, KeyError, ValueError, ValidationError) as exc:
        # Recording is optional; a broken hero file must not cost the live turn.
        log.warning("recording disabled: hero pins unavailable (%s)", type(exc).__name__)
        return inner
    return RecordingAgentModel(inner, Path(out), pins)


def agent_status(mode: str, live_configured: bool, env: dict[str, str] | None = None) -> AgentStatus:
    """/health ``agent``: LIVE when LIVE mode has a key and a model id; REPLAY when the transcript
    loads and validates (REPLAY and AUTO both play it when live is not available); DOWN otherwise."""
    if (mode or "").upper() == AgentMode.LIVE.value:
        return AgentStatus.LIVE if live_configured else AgentStatus.DOWN
    try:
        load_transcript(transcript_path(env))
    except TranscriptError:
        return AgentStatus.DOWN
    return AgentStatus.REPLAY
