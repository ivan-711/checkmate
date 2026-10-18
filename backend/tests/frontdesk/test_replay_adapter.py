"""ReplayAgentModel: step mapping, input mismatch, divergence, out-of-range, pacing, never raises.

Author: Christian Flores (Q1.4 builder).
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from backend.frontdesk.model import ErrorStep, Message, ModelRequest, TextStep, ToolCallStep
from backend.frontdesk.replay import (
    DEFAULT_TRANSCRIPT_PATH,
    ReplayAgentModel,
    Transcript,
    TranscriptError,
    fold,
    load_transcript,
    transcript_sha256,
)
from contracts.models.intake import AgentMode
from contracts.models.policy import Language
from contracts.version import REPLAY_PACING_CAP_MS, TOOL_SCHEMA_VERSION

SHA_A = "a" * 64
SHA_B = "b" * 64


def _pins() -> dict:
    return {
        "transcriptVersion": 1,
        "kind": "AUTHORED",
        "recordedAt": "2026-10-17T19:30:00Z",
        "modelId": "authored",
        "promptVersion": "fd-prompt/1",
        "toolSchemaVersion": TOOL_SCHEMA_VERSION,
        "scorerVersion": "handset-1",
        "thresholdSetId": "provisional-1",
        "heroScenarioSha256": "0" * 64,
        "scenarioContextId": "test",
    }


def _transcript_dict() -> dict:
    return {
        **_pins(),
        "turns": [
            {
                "turnIndex": 0,
                "userText": "Me llamo Ana Pérez, nací el 2 de marzo de 1990.",
                "userTextFolded": "me llamo ana perez, naci el 2 de marzo de 1990.",
                "steps": [
                    {
                        "stepIndex": 0,
                        "latencyMs": 5000,
                        "model": {
                            "type": "TOOL_CALL",
                            "toolName": "propose_new_chart",
                            "args": {"givenName": "Ana", "familyName": "Pérez", "evidence": {"givenName": "Ana"}},
                        },
                        "expect": {"gateOutcome": "ALLOW", "toolResultSha256": SHA_A},
                    },
                    {
                        "stepIndex": 1,
                        "latencyMs": 900,
                        "model": {"type": "TEXT", "text": "Gracias, Ana."},
                    },
                ],
            }
        ],
    }


def _transcript() -> Transcript:
    return Transcript.model_validate(_transcript_dict())


def _req(turn: int, step: int, text: str, last_sha: str | None = None) -> ModelRequest:
    return ModelRequest(
        session_id=uuid4(),
        turn_index=turn,
        step_index=step,
        language=Language.ES,
        prompt_version="fd-prompt/1",
        tool_schema_version=TOOL_SCHEMA_VERSION,
        system_instruction="",
        messages=(Message(role="user", text=text),),
        tools=(),
        user_text_folded=fold(text),
        last_tool_result_sha256=last_sha,
    )


USER_TEXT = "Me llamo Ana Pérez, nací el 2 de marzo de 1990."


def test_fold_strips_accents_case_and_whitespace():
    assert fold("  Me llamo  Ana PÉREZ ") == "me llamo ana perez"


def test_step_0_maps_to_tool_call_with_replay_mode_and_transcript_latency():
    adapter = ReplayAgentModel(_transcript(), pacing=False)
    step = adapter.next_step(_req(0, 0, USER_TEXT))
    assert isinstance(step, ToolCallStep)
    assert step.tool_name == "propose_new_chart"
    assert step.args["givenName"] == "Ana"
    assert step.mode == AgentMode.REPLAY
    assert step.latency_ms == 5000
    assert adapter.mode == AgentMode.REPLAY


def test_step_1_maps_to_text_when_previous_result_hash_matches():
    adapter = ReplayAgentModel(_transcript(), pacing=False)
    step = adapter.next_step(_req(0, 1, USER_TEXT, last_sha=SHA_A))
    assert isinstance(step, TextStep)
    assert step.text == "Gracias, Ana."
    assert step.mode == AgentMode.REPLAY


def test_input_mismatch_when_typed_text_differs():
    adapter = ReplayAgentModel(_transcript(), pacing=False)
    step = adapter.next_step(_req(0, 0, "Me llamo Juan Pérez, nací el 2 de marzo de 1990."))
    assert step == ErrorStep(kind="REPLAY_INPUT_MISMATCH", retryable=False, mode=AgentMode.REPLAY)


def test_input_match_ignores_case_accents_and_spacing():
    adapter = ReplayAgentModel(_transcript(), pacing=False)
    step = adapter.next_step(_req(0, 0, "ME LLAMO   Ana Perez, naci el 2 de marzo de 1990."))
    assert isinstance(step, ToolCallStep)


def test_diverged_when_previous_result_hash_differs():
    adapter = ReplayAgentModel(_transcript(), pacing=False)
    step = adapter.next_step(_req(0, 1, USER_TEXT, last_sha=SHA_B))
    assert step == ErrorStep(kind="REPLAY_DIVERGED", retryable=False, mode=AgentMode.REPLAY)


def test_diverged_when_previous_result_hash_missing():
    adapter = ReplayAgentModel(_transcript(), pacing=False)
    step = adapter.next_step(_req(0, 1, USER_TEXT, last_sha=None))
    assert step == ErrorStep(kind="REPLAY_DIVERGED", retryable=False, mode=AgentMode.REPLAY)


def test_null_expected_hash_skips_the_divergence_check():
    data = _transcript_dict()
    data["turns"][0]["steps"][0]["expect"]["toolResultSha256"] = None
    adapter = ReplayAgentModel(Transcript.model_validate(data), pacing=False)
    step = adapter.next_step(_req(0, 1, USER_TEXT, last_sha=SHA_B))
    assert isinstance(step, TextStep)


def test_step_beyond_transcript_is_diverged():
    adapter = ReplayAgentModel(_transcript(), pacing=False)
    step = adapter.next_step(_req(0, 2, USER_TEXT, last_sha=SHA_A))
    assert step == ErrorStep(kind="REPLAY_DIVERGED", retryable=False, mode=AgentMode.REPLAY)


def test_turn_beyond_transcript_is_diverged():
    adapter = ReplayAgentModel(_transcript(), pacing=False)
    step = adapter.next_step(_req(1, 0, "Hola"))
    assert step == ErrorStep(kind="REPLAY_DIVERGED", retryable=False, mode=AgentMode.REPLAY)


def test_pacing_sleeps_min_of_latency_and_cap():
    slept: list[float] = []
    adapter = ReplayAgentModel(_transcript(), pacing=True, sleep=slept.append)
    adapter.next_step(_req(0, 0, USER_TEXT))
    adapter.next_step(_req(0, 1, USER_TEXT, last_sha=SHA_A))
    assert slept == [REPLAY_PACING_CAP_MS / 1000, 0.9]


def test_pacing_off_never_sleeps():
    slept: list[float] = []
    adapter = ReplayAgentModel(_transcript(), pacing=False, sleep=slept.append)
    adapter.next_step(_req(0, 0, USER_TEXT))
    assert slept == []


def test_error_steps_do_not_sleep():
    slept: list[float] = []
    adapter = ReplayAgentModel(_transcript(), pacing=True, sleep=slept.append)
    adapter.next_step(_req(3, 0, USER_TEXT))
    assert slept == []


def test_never_raises_even_when_sleep_fails():
    def boom(_: float) -> None:
        raise RuntimeError("clock broken")

    adapter = ReplayAgentModel(_transcript(), pacing=True, sleep=boom)
    step = adapter.next_step(_req(0, 0, USER_TEXT))
    assert isinstance(step, ToolCallStep)


def test_loop_can_read_transcript_sha_for_the_audit_row(tmp_path: Path):
    path = tmp_path / "t.json"
    path.write_text(json.dumps(_transcript_dict()), encoding="utf-8")
    adapter = ReplayAgentModel(load_transcript(path), pacing=False, transcript_sha256=transcript_sha256(path))
    assert adapter.transcript_sha256 == transcript_sha256(path)
    assert len(adapter.transcript_sha256) == 64


# load_transcript validation


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "t.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_load_transcript_round_trips(tmp_path: Path):
    t = load_transcript(_write(tmp_path, _transcript_dict()))
    assert t.kind == "AUTHORED"
    assert t.turns[0].steps[1].model.text == "Gracias, Ana."


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(transcriptVersion=2),
        lambda d: d.update(kind="IMPROVISED"),
        lambda d: d.pop("modelId"),
        lambda d: d.pop("promptVersion"),
        lambda d: d.pop("toolSchemaVersion"),
        lambda d: d.pop("scorerVersion"),
        lambda d: d.pop("thresholdSetId"),
        lambda d: d.pop("heroScenarioSha256"),
        lambda d: d.pop("scenarioContextId"),
        lambda d: d["turns"][0]["steps"][0]["model"].update(type="DANCE"),
        lambda d: d["turns"][0]["steps"][0]["model"].update(score=0.9),
        lambda d: d["turns"][0]["steps"][0]["expect"].update(toolResultSha256="short"),
    ],
    ids=[
        "version",
        "kind",
        "modelId",
        "promptVersion",
        "toolSchemaVersion",
        "scorerVersion",
        "thresholdSetId",
        "heroScenarioSha256",
        "scenarioContextId",
        "stepType",
        "extraKey",
        "shaShape",
    ],
)
def test_load_transcript_rejects_bad_pins(tmp_path: Path, mutate):
    data = _transcript_dict()
    mutate(data)
    with pytest.raises(TranscriptError):
        load_transcript(_write(tmp_path, data))


def test_load_transcript_rejects_missing_file(tmp_path: Path):
    with pytest.raises(TranscriptError):
        load_transcript(tmp_path / "nope.json")


def test_load_transcript_rejects_non_json(tmp_path: Path):
    path = tmp_path / "t.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(TranscriptError):
        load_transcript(path)


def test_load_transcript_rejects_duplicate_script(tmp_path: Path):
    data = _transcript_dict()
    data["turns"].append(dict(data["turns"][0]))
    with pytest.raises(TranscriptError):
        load_transcript(_write(tmp_path, data))


def test_two_scripts_share_turn_zero_and_the_typed_text_picks_one(tmp_path: Path):
    data = _transcript_dict()
    english = json.loads(json.dumps(data["turns"][0]))
    english["userText"] = "My name is Ana Perez, born March 2, 1990."
    english["userTextFolded"] = fold(english["userText"])
    english["steps"][1]["model"]["text"] = "Thank you, Ana."
    data["turns"].append(english)
    adapter = ReplayAgentModel(load_transcript(_write(tmp_path, data)), pacing=False)
    es = adapter.next_step(_req(0, 1, USER_TEXT, last_sha=SHA_A))
    en = adapter.next_step(_req(0, 1, english["userText"], last_sha=SHA_A))
    assert isinstance(es, TextStep) and es.text == "Gracias, Ana."
    assert isinstance(en, TextStep) and en.text == "Thank you, Ana."


def test_load_transcript_rejects_step_index_gap(tmp_path: Path):
    data = _transcript_dict()
    data["turns"][0]["steps"][1]["stepIndex"] = 5
    with pytest.raises(TranscriptError):
        load_transcript(_write(tmp_path, data))


def test_transcript_sha256_is_stable_over_bytes(tmp_path: Path):
    path = _write(tmp_path, _transcript_dict())
    before = transcript_sha256(path)
    assert before == transcript_sha256(path)
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert transcript_sha256(path) != before


def test_default_transcript_path_is_the_hero_file():
    assert DEFAULT_TRANSCRIPT_PATH == Path("data/scenarios/hero/frontdesk_transcript.json")
