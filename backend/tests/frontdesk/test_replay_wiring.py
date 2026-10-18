"""Wiring helpers: transcript path and pacing from the environment, fail-closed adapter build,
/health agent status, and the recording wrapper switch.

Author: Christian Flores (Q1.4 builder).
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.app.config import Settings
from backend.frontdesk import adapters
from backend.frontdesk.replay import (
    DEFAULT_TRANSCRIPT_PATH,
    PACING_ENV,
    RECORD_TO_ENV,
    TRANSCRIPT_PATH_ENV,
    RecordingAgentModel,
    ReplayAgentModel,
    agent_status,
    build_replay_model,
    maybe_record,
    pacing_enabled,
    transcript_path,
)
from backend.tests.frontdesk.test_replay_adapter import _transcript_dict
from contracts.models.health import AgentStatus
from contracts.models.intake import AgentMode


def test_transcript_path_defaults_to_the_committed_file_and_honours_the_env():
    assert transcript_path({}) == DEFAULT_TRANSCRIPT_PATH
    assert transcript_path({TRANSCRIPT_PATH_ENV: "/tmp/x.json"}) == Path("/tmp/x.json")
    assert transcript_path({TRANSCRIPT_PATH_ENV: ""}) == DEFAULT_TRANSCRIPT_PATH


def test_pacing_is_on_by_default_and_off_for_the_usual_false_values():
    assert pacing_enabled({}) is True
    for off in ("0", "false", "No", " OFF "):
        assert pacing_enabled({PACING_ENV: off}) is False
    assert pacing_enabled({PACING_ENV: "1"}) is True


def test_build_replay_model_reads_the_configured_transcript(tmp_path: Path):
    path = tmp_path / "t.json"
    path.write_text(json.dumps(_transcript_dict()), encoding="utf-8")
    model = build_replay_model({TRANSCRIPT_PATH_ENV: str(path), PACING_ENV: "0"})
    assert isinstance(model, ReplayAgentModel)
    assert model.pacing is False
    assert model.transcript_sha256 and len(model.transcript_sha256) == 64


def test_build_replay_model_is_none_when_the_transcript_does_not_load(tmp_path: Path):
    assert build_replay_model({TRANSCRIPT_PATH_ENV: str(tmp_path / "missing.json")}) is None


def test_make_model_replay_falls_to_unavailable_when_the_transcript_is_broken(monkeypatch, tmp_path: Path):
    monkeypatch.setenv(TRANSCRIPT_PATH_ENV, str(tmp_path / "missing.json"))
    settings = Settings(
        database_url="postgresql://x/test",
        cors_origins=(),
        frontdesk_agent_mode="REPLAY",
        gemini_model_id=None,
        gemini_api_key_present=False,
        capture_dir=None,
        git_sha=None,
    )
    model = adapters.make_model(AgentMode.REPLAY, settings)
    assert isinstance(model, adapters.UnavailableAgentModel)
    assert model.mode == AgentMode.REPLAY


def test_make_model_replay_uses_the_committed_transcript(monkeypatch):
    monkeypatch.delenv(TRANSCRIPT_PATH_ENV, raising=False)
    settings = Settings(
        database_url="postgresql://x/test",
        cors_origins=(),
        frontdesk_agent_mode="REPLAY",
        gemini_model_id=None,
        gemini_api_key_present=False,
        capture_dir=None,
        git_sha=None,
    )
    model = adapters.make_model(AgentMode.REPLAY, settings)
    assert isinstance(model, ReplayAgentModel)
    assert model.mode == AgentMode.REPLAY


def test_agent_status_live_replay_down(tmp_path: Path):
    assert agent_status("LIVE", True) == AgentStatus.LIVE
    assert agent_status("LIVE", False) == AgentStatus.DOWN
    assert agent_status("REPLAY", False, {}) == AgentStatus.REPLAY  # the committed transcript loads
    assert agent_status("AUTO", False, {}) == AgentStatus.REPLAY
    assert agent_status("REPLAY", False, {TRANSCRIPT_PATH_ENV: str(tmp_path / "nope.json")}) == AgentStatus.DOWN


class _Inner:
    mode = AgentMode.LIVE

    def next_step(self, req):  # pragma: no cover - never called here
        raise AssertionError


def test_maybe_record_wraps_only_when_the_output_path_is_set(tmp_path: Path):
    inner = _Inner()
    assert maybe_record(inner, "model-x", {}) is inner
    wrapped = maybe_record(inner, "model-x", {RECORD_TO_ENV: str(tmp_path / "rec.json")})
    assert isinstance(wrapped, RecordingAgentModel)
    assert wrapped.mode == AgentMode.LIVE
    assert wrapped.pins.model_id == "model-x"
    assert wrapped.pins.scenario_context_id == "hero-er-arrival"


def test_maybe_record_degrades_to_the_bare_adapter_when_the_hero_pins_are_unavailable(tmp_path: Path, monkeypatch):
    from backend.frontdesk import replay

    monkeypatch.setattr(replay, "HERO_DIR", tmp_path / "no-hero-dir")
    inner = _Inner()
    assert maybe_record(inner, "model-x", {RECORD_TO_ENV: str(tmp_path / "rec.json")}) is inner
