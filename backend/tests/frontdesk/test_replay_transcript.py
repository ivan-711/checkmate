"""The committed AUTHORED transcript: validates, is pinned to the hero on disk, and is reproducible
from ``author_transcript``. Fails if the hero changes without a rebuild.

Author: Christian Flores (Q1.4 builder).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from backend.frontdesk import author_transcript
from backend.frontdesk.replay import DEFAULT_TRANSCRIPT_PATH, ToolCallModelStep, fold, load_transcript
from contracts.models.policy import PolicyOutcome, PolicyReason, ProposeArgs
from contracts.version import TOOL_SCHEMA_VERSION

REPO = Path(__file__).resolve().parents[3]
HERO_DIR = REPO / "data" / "scenarios" / "hero"
TRANSCRIPT = DEFAULT_TRANSCRIPT_PATH

# Words the kiosk must never say to a patient (clinical or alarming); the brief's never-say list.
NEVER_SAY = (
    "duplicate",
    "duplicado",
    "flag",
    "alert",
    "alerta",
    "allerg",
    "alerg",
    "match",
    "score",
    "chart was created",
)


@pytest.fixture(scope="module")
def transcript():
    return load_transcript(TRANSCRIPT)


@pytest.fixture(scope="module")
def hero() -> dict:
    return json.loads((HERO_DIR / "hero.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def intake() -> dict:
    return json.loads((HERO_DIR / "frontdesk_intake.json").read_text(encoding="utf-8"))


def test_transcript_is_authored_and_marked_constructed(transcript):
    assert transcript.kind == "AUTHORED"
    assert transcript.authoring and transcript.authoring["constructed"] is True
    assert transcript.tool_schema_version == TOOL_SCHEMA_VERSION


def test_pins_match_the_hero_files(transcript, hero, intake):
    assert transcript.scorer_version == hero["scorerVersion"]
    assert transcript.threshold_set_id == hero["thresholdsId"]
    assert transcript.scenario_context_id == intake["scenarioContextId"]
    assert transcript.hero_scenario_sha256 == hashlib.sha256((HERO_DIR / "scenario.json").read_bytes()).hexdigest()


def test_returning_patient_is_the_hero_er_record_in_both_languages(transcript, hero, intake):
    er = hero["records"]["ER_FHIR"]
    by_text = {t.user_text: t for t in transcript.turns}
    for utterance, lang in ((intake["utteranceEs"], "ES"), (intake["utteranceEn"], "EN")):
        turn = by_text[utterance]
        assert turn.turn_index == 0
        step0 = turn.steps[0]
        assert isinstance(step0.model, ToolCallModelStep)
        assert step0.model.tool_name == "propose_new_chart"
        args = ProposeArgs.model_validate(step0.model.args)
        assert (args.given_name, args.family_name, args.birth_date) == (
            er["given_name"],
            er["family_name"],
            er["birth_date"],
        )
        assert args.sex == "UNKNOWN"  # the utterance never states it
        assert args.preferred_language == lang
        assert step0.expect.gate_outcome == PolicyOutcome.DENY
        assert step0.expect.reason_code == PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER
        assert turn.steps[1].model.type == "TEXT"
        assert er["given_name"] in turn.steps[1].model.text


def test_new_patient_scripts_expect_allow(transcript):
    new = [t for t in transcript.turns if author_transcript.NEW_PATIENT["givenName"] in t.user_text]
    assert len(new) == 2
    for turn in new:
        assert turn.steps[0].expect.gate_outcome == PolicyOutcome.ALLOW
        assert turn.steps[0].expect.reason_code is None


def test_every_evidence_quote_is_verbatim_in_the_typed_text(transcript):
    for turn in transcript.turns:
        folded = fold(turn.user_text)
        for step in turn.steps:
            if isinstance(step.model, ToolCallModelStep):
                assert step.model.args["evidence"], "a propose without evidence cannot be grounded"
                for field, quote in step.model.args["evidence"].items():
                    assert fold(quote) in folded, f"{field!r} quote is not in the utterance"


def test_folded_text_is_the_fold_of_the_text(transcript):
    for turn in transcript.turns:
        assert turn.user_text_folded == fold(turn.user_text)


def test_assistant_text_is_plain_and_never_claims_a_chart(transcript):
    for turn in transcript.turns:
        for step in turn.steps:
            if step.model.type == "TEXT":
                low = step.model.text.lower()
                for word in NEVER_SAY:
                    assert word not in low, f"{word!r} in {step.model.text!r}"
                assert "registr" in low  # a registrar is always named as the next step


def test_authoring_script_reproduces_the_committed_file(tmp_path: Path):
    built = author_transcript.build_transcript(HERO_DIR)
    committed = load_transcript(TRANSCRIPT)
    assert built.model_dump(exclude={"recorded_at"}) == committed.model_dump(exclude={"recorded_at"})
    out = tmp_path / "t.json"
    author_transcript.write_transcript(built, out)
    assert load_transcript(out).turns == committed.turns


def test_fill_hashes_records_real_result_hashes_that_then_replay_cleanly(hero_clinic_record, intake_sessions):
    """The recorder around the replay adapter learns each ToolResult hash from the engine; the filled
    transcript then plays through the routes with the divergence check active and never diverges."""
    import uuid

    from sqlalchemy import text as sql

    from backend.frontdesk.replay import ReplayAgentModel, TextModelStep
    from backend.tests.frontdesk.conftest import engine

    filled = author_transcript.fill_hashes(load_transcript(TRANSCRIPT), engine)
    with engine.connect() as conn:  # fill_hashes opened its own sessions; collect them for the purge
        intake_sessions.extend(
            str(r[0])
            for r in conn.execute(
                sql("SELECT id FROM intake_session WHERE scenario_context_id = :c AND model_id IS NULL"),
                {"c": filled.scenario_context_id},
            )
        )
    for turn in filled.turns:
        tool_steps = [s for s in turn.steps if isinstance(s.model, ToolCallModelStep)]
        assert tool_steps and all(
            s.expect is not None and s.expect.tool_result_sha256 and len(s.expect.tool_result_sha256) == 64
            for s in tool_steps
        )
        assert all(s.expect is None for s in turn.steps if isinstance(s.model, TextModelStep))

    # replay the filled transcript: the text step after each tool call requires the hash to match
    from backend.frontdesk import loop, store
    from contracts.models.intake import AgentMode, IntakeTurn, TurnRequest
    from contracts.models.policy import Language

    model = ReplayAgentModel(filled, pacing=False)
    for turn in filled.turns:
        sid = uuid.uuid4()
        lang = Language(turn.steps[0].model.args["preferredLanguage"])
        with engine.begin() as conn:
            store.insert_session(
                conn,
                session_id=sid,
                language=lang,
                agent_mode=AgentMode.REPLAY,
                scenario_context_id="fill-hashes-replay",
                prompt_version=filled.prompt_version,
                tool_schema_version=filled.tool_schema_version,
                model_id=None,
            )
        intake_sessions.append(str(sid))
        _, response = loop.run_turn(
            engine, model, session_id=sid, key=str(uuid.uuid4()), body=TurnRequest(text=turn.user_text)
        )
        played = IntakeTurn.model_validate(response)
        assert played.degraded is None, played.degraded
        assert played.assistant_text == turn.steps[-1].model.text
