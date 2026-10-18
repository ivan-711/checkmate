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
from backend.frontdesk.templates import banned_phrase
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


def test_assistant_text_passes_the_production_banned_phrase_check(transcript):
    """loop.py runs banned_phrase on every TextStep in REPLAY too, so a never-say.txt entry that
    matched a recorded reply would turn a demo turn into the template line; this pins the demo
    to the production lists with the chart effect the scripted gate outcome produces."""
    for turn in transcript.turns:
        created = False
        for step in turn.steps:
            if isinstance(step.model, ToolCallModelStep):
                created = created or (
                    step.model.tool_name == "propose_new_chart"
                    and step.expect is not None
                    and step.expect.gate_outcome == PolicyOutcome.ALLOW
                )
            else:
                hit = banned_phrase(step.model.text, new_chart_created=created)
                assert hit is None, f"{hit!r} in {step.model.text!r}"


def test_authoring_script_reproduces_the_committed_file(tmp_path: Path):
    built = author_transcript.build_transcript(HERO_DIR)
    committed = load_transcript(TRANSCRIPT)
    # the hashes and the fill timestamp come from a --fill-hashes run, not from the hero files
    for turn in committed.turns:
        for step in turn.steps:
            if step.expect is not None:
                step.expect.tool_result_sha256 = None
    committed.authoring.pop("toolResultHashesFilledAt", None)
    assert built.model_dump(exclude={"recorded_at"}) == committed.model_dump(exclude={"recorded_at"})
    out = tmp_path / "t.json"
    author_transcript.write_transcript(built, out)
    assert load_transcript(out).turns == committed.turns


def test_fill_hashes_records_real_result_hashes_that_then_replay_cleanly(hero_records, intake_sessions):
    """The recorder around the replay adapter learns each ToolResult hash from the engine; the filled
    transcript then plays through the loop with the divergence check active and never diverges."""
    import uuid

    from sqlalchemy import text as sql

    from backend.frontdesk import loop, store
    from backend.frontdesk.replay import ReplayAgentModel, TextModelStep
    from backend.tests.frontdesk.conftest import engine, purge_session
    from contracts.models.intake import AgentMode, IntakeTurn, TurnRequest
    from contracts.models.policy import Language

    filled = author_transcript.fill_hashes(load_transcript(TRANSCRIPT), engine)
    with engine.connect() as conn:  # fill_hashes purges its own sessions and intake records
        left = conn.execute(
            sql("SELECT count(*) FROM intake_session WHERE scenario_context_id = :c"), {"c": filled.scenario_context_id}
        ).scalar_one()
    assert left == 0
    hashes = set()
    for turn in filled.turns:
        tool_steps = [s for s in turn.steps if isinstance(s.model, ToolCallModelStep)]
        assert tool_steps
        for step in tool_steps:
            assert step.expect is not None and step.expect.tool_result_sha256
            assert len(step.expect.tool_result_sha256) == 64
            hashes.add(step.expect.tool_result_sha256)
        assert all(s.expect is None for s in turn.steps if isinstance(s.model, TextModelStep))
    assert len(hashes) == len(filled.turns), "ES and EN results differ by message, so every script has its own hash"
    # The committed hashes are the ones a demo reset's state produces; this state seeds the same records
    # (hero.json's ER and Clinic), so a drift between them fails here, not on stage.
    committed = load_transcript(TRANSCRIPT)
    assert [[s.expect and s.expect.tool_result_sha256 for s in t.steps] for t in filled.turns] == [
        [s.expect and s.expect.tool_result_sha256 for s in t.steps] for t in committed.turns
    ], "the committed toolResultSha256 values no longer match the reset state; re-run --fill-hashes"

    # Replay from the same clean state the fill used: an intake record is a candidate for the next
    # session with the same demographics, so every session is purged right after its turn.
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
        _, response = loop.run_turn(
            engine, model, session_id=sid, key=str(uuid.uuid4()), body=TurnRequest(text=turn.user_text)
        )
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            purge_session(conn, str(sid))
        played = IntakeTurn.model_validate(response)
        assert played.degraded is None, played.degraded
        assert played.assistant_text == turn.steps[-1].model.text


def test_built_scripts_do_not_share_expectation_objects():
    """A shared StepExpect would make every script take the last recorded hash."""
    built = author_transcript.build_transcript(HERO_DIR)
    expects = [id(t.steps[0].expect) for t in built.turns]
    assert len(set(expects)) == len(expects)


def test_fill_hashes_refuses_a_database_with_leftover_intake_state(intake_sessions):
    import uuid

    from backend.frontdesk import store
    from backend.tests.frontdesk.conftest import engine
    from contracts.models.intake import AgentMode
    from contracts.models.policy import Language

    sid = uuid.uuid4()
    with engine.begin() as conn:
        store.insert_session(
            conn,
            session_id=sid,
            language=Language.EN,
            agent_mode=AgentMode.REPLAY,
            scenario_context_id="leftover",
            prompt_version="fd-prompt/1",
            tool_schema_version="fd-tools/1",
            model_id=None,
        )
    intake_sessions.append(str(sid))
    with pytest.raises(SystemExit, match="clean state"):
        author_transcript.fill_hashes(load_transcript(TRANSCRIPT), engine)


def test_fill_hashes_cli_entry_point_reaches_fill_hashes(tmp_path: Path):
    """``python -m backend.frontdesk.author_transcript --fill-hashes URL`` is the documented refill path:
    run as ``__main__`` it must reach ``fill_hashes`` (here its non-test-database refusal, before any
    connection is opened), never a NameError from a guard placed above the function."""
    import subprocess
    import sys

    out = tmp_path / "t.json"
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.frontdesk.author_transcript",
            "--fill-hashes",
            "postgresql://nobody:nothing@127.0.0.1:1/checkmate_demo",
            "--out",
            str(out),
        ],
        check=False,
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "NameError" not in done.stderr, done.stderr
    assert done.returncode != 0
    assert "refusing to run on database 'checkmate_demo'" in done.stderr
    assert not out.exists()


def test_author_cli_entry_point_writes_the_transcript(tmp_path: Path):
    import subprocess
    import sys

    out = tmp_path / "t.json"
    done = subprocess.run(
        [sys.executable, "-m", "backend.frontdesk.author_transcript", "--out", str(out)],
        check=False,
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    assert load_transcript(out).turns
