"""RecordingAgentModel writes a RECORDED transcript that round-trips through load_transcript and
plays back identically. Uses a fake inner adapter; no network, no SDK.

Author: Christian Flores (Q1.4 builder).
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from backend.frontdesk.model import ErrorStep, Message, ModelRequest, ModelStep, TextStep, ToolCallStep
from backend.frontdesk.replay import (
    RecordingAgentModel,
    ReplayAgentModel,
    TranscriptPins,
    fold,
    load_transcript,
)
from contracts.models.intake import AgentMode
from contracts.models.policy import Language, PolicyOutcome, PolicyReason
from contracts.version import TOOL_SCHEMA_VERSION

USER_TEXT = "My name is Ana Perez, born March 2, 1990."
SHA_A = "a" * 64
ARGS = {"givenName": "Ana", "familyName": "Perez", "evidence": {"givenName": "Ana", "familyName": "Perez"}}


class FakeLive:
    """Scripted LIVE adapter: tool call, then text; anything further is an error."""

    mode = AgentMode.LIVE

    def __init__(self) -> None:
        self.calls = 0

    def next_step(self, req: ModelRequest) -> ModelStep:
        self.calls += 1
        if req.step_index == 0:
            return ToolCallStep("propose_new_chart", ARGS, "call-1", 4100, AgentMode.LIVE)
        if req.step_index == 1:
            return TextStep("Thank you, Ana. A registrar will finish your registration.", 2700, AgentMode.LIVE)
        return ErrorStep("TIMEOUT", True, AgentMode.LIVE)


def _pins() -> TranscriptPins:
    return TranscriptPins(
        model_id="fake-model",
        scorer_version="handset-1",
        threshold_set_id="provisional-1",
        hero_scenario_sha256="0" * 64,
        scenario_context_id="test",
    )


def _req(step: int, messages: tuple[Message, ...], last_sha: str | None) -> ModelRequest:
    return ModelRequest(
        session_id=uuid4(),
        turn_index=0,
        step_index=step,
        language=Language.EN,
        prompt_version="fd-prompt/1",
        tool_schema_version=TOOL_SCHEMA_VERSION,
        system_instruction="",
        messages=messages,
        tools=(),
        user_text_folded=fold(USER_TEXT),
        last_tool_result_sha256=last_sha,
    )


def _drive(recorder: RecordingAgentModel) -> list[ModelStep]:
    user = Message(role="user", text=USER_TEXT)
    first = recorder.next_step(_req(0, (user,), None))
    tool_result = {"status": "DENIED", "reasonCode": "CANDIDATE_IN_REVIEW_OR_HIGHER"}
    second = recorder.next_step(
        _req(
            1, (user, Message(role="model", tool_call=first), Message(role="function", tool_result=tool_result)), SHA_A
        )
    )
    return [first, second]


def test_recording_passes_inner_steps_through_unchanged(tmp_path: Path):
    inner = FakeLive()
    recorder = RecordingAgentModel(inner, tmp_path / "rec.json", _pins())
    first, second = _drive(recorder)
    assert recorder.mode == AgentMode.LIVE
    assert isinstance(first, ToolCallStep) and first.mode == AgentMode.LIVE
    assert isinstance(second, TextStep)
    assert inner.calls == 2


def test_recorded_file_round_trips_and_carries_pins(tmp_path: Path):
    out = tmp_path / "rec.json"
    _drive(RecordingAgentModel(FakeLive(), out, _pins()))
    t = load_transcript(out)
    assert t.kind == "RECORDED"
    assert t.model_id == "fake-model"
    assert t.prompt_version == "fd-prompt/1"
    assert t.tool_schema_version == TOOL_SCHEMA_VERSION
    assert t.scorer_version == "handset-1"
    assert t.threshold_set_id == "provisional-1"
    turn = t.turns[0]
    assert turn.user_text == USER_TEXT
    assert turn.user_text_folded == fold(USER_TEXT)
    assert [s.step_index for s in turn.steps] == [0, 1]
    assert turn.steps[0].latency_ms == 4100
    assert turn.steps[0].model.tool_name == "propose_new_chart"
    assert turn.steps[0].model.args == ARGS


def test_previous_step_expectation_is_filled_from_the_next_request(tmp_path: Path):
    out = tmp_path / "rec.json"
    _drive(RecordingAgentModel(FakeLive(), out, _pins()))
    expect = load_transcript(out).turns[0].steps[0].expect
    assert expect is not None
    assert expect.tool_result_sha256 == SHA_A
    assert expect.gate_outcome == PolicyOutcome.DENY
    assert expect.reason_code == PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER
    assert load_transcript(out).turns[0].steps[1].expect is None  # text step: nothing follows it


def test_recorded_transcript_plays_back_identically(tmp_path: Path):
    out = tmp_path / "rec.json"
    live_steps = _drive(RecordingAgentModel(FakeLive(), out, _pins()))
    replay = ReplayAgentModel(load_transcript(out), pacing=False)
    user = Message(role="user", text=USER_TEXT)
    r0 = replay.next_step(_req(0, (user,), None))
    r1 = replay.next_step(_req(1, (user,), SHA_A))
    assert isinstance(r0, ToolCallStep) and isinstance(live_steps[0], ToolCallStep)
    assert (r0.tool_name, r0.args, r0.latency_ms) == (live_steps[0].tool_name, live_steps[0].args, 4100)
    assert r0.mode == AgentMode.REPLAY
    assert isinstance(r1, TextStep) and isinstance(live_steps[1], TextStep)
    assert r1.text == live_steps[1].text
    # and a different engine answer on step 0 is caught
    assert replay.next_step(_req(1, (user,), "b" * 64)) == ErrorStep("REPLAY_DIVERGED", False, AgentMode.REPLAY)


def test_error_steps_are_passed_through_and_not_recorded(tmp_path: Path):
    out = tmp_path / "rec.json"
    recorder = RecordingAgentModel(FakeLive(), out, _pins())
    _drive(recorder)
    user = Message(role="user", text=USER_TEXT)
    third = recorder.next_step(_req(2, (user,), SHA_A))
    assert isinstance(third, ErrorStep)
    assert len(load_transcript(out).turns[0].steps) == 2


def test_file_is_valid_after_the_first_step(tmp_path: Path):
    out = tmp_path / "rec.json"
    recorder = RecordingAgentModel(FakeLive(), out, _pins())
    recorder.next_step(_req(0, (Message(role="user", text=USER_TEXT),), None))
    t = load_transcript(out)
    assert len(t.turns[0].steps) == 1
    assert t.turns[0].steps[0].expect is None
    assert not out.with_suffix(".json.tmp").exists()
