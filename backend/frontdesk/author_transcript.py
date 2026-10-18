"""Build the AUTHORED FrontDesk transcript from the hero files (ADR-016 §7).

    uv run python -m backend.frontdesk.author_transcript [--hero-dir data/scenarios/hero] [--out <path>]

The returning patient is the hero's ER-side rendering (``hero.json`` ``records.ER_FHIR``), which lands
in REVIEW against the Clinic record, so the gate denies ``propose_new_chart`` with
``CANDIDATE_IN_REVIEW_OR_HIGHER``. The new patient is a synthetic person who shares no block key with
any corpus record (checked against the seed-20261017 corpus on 2026-10-17), so the gate allows.
Every evidence quote is a verbatim substring of the typed text, as the grounding check requires.

The call shapes follow the spike's verified live calls (one ``propose_new_chart`` with ``sex: UNKNOWN``
when unstated, then plain text). ``expect.toolResultSha256`` is null until a run through the real
engine fills it; ``ReplayAgentModel`` skips the divergence check for null hashes.

Author: Christian Flores (Q1.4 builder).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from backend.frontdesk.replay import (
    DEFAULT_TRANSCRIPT_PATH,
    HERO_DIR,
    TRANSCRIPT_VERSION,
    StepExpect,
    TextModelStep,
    ToolCallModelStep,
    Transcript,
    TranscriptStep,
    TranscriptTurn,
    fold,
)
from contracts.models.policy import PolicyOutcome, PolicyReason
from contracts.version import TOOL_SCHEMA_VERSION

AUTHORED_MODEL_ID = "authored (not a recorded model run)"
DEFAULT_PROMPT_VERSION = "fd-prompt/1"
# Latencies measured at the venue (docs/spikes/gemini.md): tool step 3.9–7.8 s, plain text 2.6–2.9 s.
TOOL_STEP_LATENCY_MS = 5200
TEXT_STEP_LATENCY_MS = 2700

MONTHS_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)  # fmt: skip
MONTHS_EN = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip

# A synthetic person far from every corpus record: no shared DOB, swapped DOB, phone last-7 or
# (surname Double Metaphone, birth year) key in the seed-20261017 corpus.
NEW_PATIENT = {
    "givenName": "Teodoro",
    "familyName": "Quintanilla Abasolo",
    "birthDate": "1951-11-09",
    "phone": "555-012-7734",
}

RETURNING_TEXT = {
    "ES": "Gracias, {given}. Una persona de registro va a confirmar su expediente en un momento.",
    "EN": "Thank you, {given}. A registrar will confirm your record in a moment.",
}
NEW_PATIENT_TEXT = {
    "ES": "Gracias, {given}. Hemos iniciado su registro; una persona de registro lo termina con usted en un momento.",
    "EN": "Thank you, {given}. We have started your registration; a registrar will finish it with you in a moment.",
}


def _utterance(lang: str, given: str, family: str, birth: date, phone: str | None, address: str | None) -> str:
    if lang == "ES":
        parts = [f"Me llamo {given} {family}, nací el {birth.day} de {MONTHS_ES[birth.month - 1]} de {birth.year}"]
        if phone:
            parts.append(f"mi teléfono es {phone}")
        if address:
            parts.append(f"vivo en {address}")
    else:
        parts = [f"My name is {given} {family}, born {MONTHS_EN[birth.month - 1]} {birth.day}, {birth.year}"]
        if phone:
            parts.append(f"my phone is {phone}")
        if address:
            parts.append(f"I live at {address}")
    return ", ".join(parts) + "."


def _birth_quote(lang: str, birth: date) -> str:
    if lang == "ES":
        return f"{birth.day} de {MONTHS_ES[birth.month - 1]} de {birth.year}"
    return f"{MONTHS_EN[birth.month - 1]} {birth.day}, {birth.year}"


def _propose_args(lang: str, given: str, family: str, birth: date, phone: str | None, address: str | None) -> dict:
    evidence = {"givenName": given, "familyName": family, "birthDate": _birth_quote(lang, birth)}
    args = {
        "givenName": given,
        "familyName": family,
        "birthDate": birth.isoformat(),
        "sex": "UNKNOWN",  # the patient did not state it; never invented (spike: verified call shape)
        "preferredLanguage": lang,
    }
    if phone:
        args["phone"] = phone
        evidence["phone"] = phone
    if address:
        args["addressLine"] = address
        evidence["addressLine"] = address
    args["evidence"] = evidence
    return args


def _check_grounded(utterance: str, args: dict) -> None:
    folded = fold(utterance)
    for field, quote in args["evidence"].items():
        if fold(quote) not in folded:
            raise ValueError(f"evidence for {field} is not a verbatim substring of the utterance")


def _script(
    lang: str,
    given: str,
    family: str,
    birth: date,
    phone: str | None,
    address: str | None,
    expect: StepExpect,
    text_template: dict[str, str],
) -> TranscriptTurn:
    utterance = _utterance(lang, given, family, birth, phone, address)
    args = _propose_args(lang, given, family, birth, phone, address)
    _check_grounded(utterance, args)
    return TranscriptTurn(
        turn_index=0,
        user_text=utterance,
        user_text_folded=fold(utterance),
        steps=[
            TranscriptStep(
                step_index=0,
                latency_ms=TOOL_STEP_LATENCY_MS,
                model=ToolCallModelStep(type="TOOL_CALL", tool_name="propose_new_chart", args=args),
                expect=expect.model_copy(),  # own instance: a shared one would take the last script's hash
            ),
            TranscriptStep(
                step_index=1,
                latency_ms=TEXT_STEP_LATENCY_MS,
                model=TextModelStep(type="TEXT", text=text_template[lang].format(given=given)),
            ),
        ],
    )


def _prompt_version() -> str:
    try:
        from backend.frontdesk import prompts  # Q1.2's module; absent until that lane lands

        return str(getattr(prompts, "PROMPT_VERSION", DEFAULT_PROMPT_VERSION))
    except ImportError:
        return DEFAULT_PROMPT_VERSION


def build_transcript(hero_dir: Path) -> Transcript:
    hero = json.loads((hero_dir / "hero.json").read_text(encoding="utf-8"))
    intake = json.loads((hero_dir / "frontdesk_intake.json").read_text(encoding="utf-8"))
    er = hero["records"]["ER_FHIR"]
    birth = date.fromisoformat(er["birth_date"])
    deny = StepExpect(
        gate_outcome=PolicyOutcome.DENY,
        reason_code=PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER,
        tool_result_sha256=None,
    )
    allow = StepExpect(gate_outcome=PolicyOutcome.ALLOW, reason_code=None, tool_result_sha256=None)
    new_birth = date.fromisoformat(NEW_PATIENT["birthDate"])
    turns = [
        _script(lang, er["given_name"], er["family_name"], birth, er["phone"], er["address_line"], deny, RETURNING_TEXT)
        for lang in ("ES", "EN")
    ] + [
        _script(
            lang,
            NEW_PATIENT["givenName"],
            NEW_PATIENT["familyName"],
            new_birth,
            NEW_PATIENT["phone"],
            None,
            allow,
            NEW_PATIENT_TEXT,
        )
        for lang in ("ES", "EN")
    ]
    return Transcript(
        transcript_version=TRANSCRIPT_VERSION,
        kind="AUTHORED",
        recorded_at=datetime.now(UTC).replace(microsecond=0),
        model_id=AUTHORED_MODEL_ID,
        prompt_version=_prompt_version(),
        tool_schema_version=TOOL_SCHEMA_VERSION,
        scorer_version=hero["scorerVersion"],
        threshold_set_id=hero["thresholdsId"],
        hero_scenario_sha256=hashlib.sha256((hero_dir / "scenario.json").read_bytes()).hexdigest(),
        scenario_context_id=intake["scenarioContextId"],
        authoring={
            "constructed": True,
            "note": "authored from the spike's verified call shapes; not a recorded model run",
            "heroEntityId": hero["entityId"],
            "heroRecordId": er["record_id"],
        },
        turns=turns,
    )


def write_transcript(transcript: Transcript, out: Path) -> None:
    body = json.dumps(transcript.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2)
    out.write_text(body + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hero-dir", type=Path, default=HERO_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_TRANSCRIPT_PATH)
    parser.add_argument(
        "--fill-hashes",
        metavar="DATABASE_URL",
        help="run every script through the real engine on this database and record expect.toolResultSha256 "
        "(the database must hold the hero's Clinic record; never the dev database during a demo)",
    )
    args = parser.parse_args(argv)
    transcript = build_transcript(args.hero_dir)
    if args.fill_hashes:
        from backend.app.db import make_engine

        transcript = fill_hashes(transcript, make_engine(args.fill_hashes))
        transcript.authoring = {
            **(transcript.authoring or {}),
            "toolResultHashesFilledAt": transcript.recorded_at.isoformat(),
        }
    write_transcript(transcript, args.out)
    print(f"wrote {args.out}")
    return 0


# Filling expect.toolResultSha256 by running the scripts through the real engine. The recorder
# learns each step's result hash from the next request, so wrapping the replay adapter in it and
# driving the loop once per script yields exactly the hashes playback will check.


def fill_hashes(transcript: Transcript, engine) -> Transcript:
    """Return a copy of ``transcript`` whose tool steps carry the engine's ToolResult hashes.

    One fresh intake session per script (``turnIndex 0`` entries), every turn of that script in order,
    and what the script wrote (its session, handoff pairs, intake record) is purged before the next
    script, because an intake record is itself a candidate for the next session with the same
    demographics. Every hash is therefore recorded from the state a demo reset leaves: the database
    must hold the records the scripts expect (the hero's Clinic record), nothing from earlier intakes.
    The purge is why this only runs against a database whose name contains ``test``.
    """
    from backend.frontdesk import loop, store
    from backend.frontdesk.replay import RecordingAgentModel, ReplayAgentModel, TranscriptPins
    from contracts.models.intake import AgentMode, TurnRequest

    pins = TranscriptPins(
        model_id=transcript.model_id,
        scorer_version=transcript.scorer_version,
        threshold_set_id=transcript.threshold_set_id,
        hero_scenario_sha256=transcript.hero_scenario_sha256,
        scenario_context_id=transcript.scenario_context_id,
    )
    _require_test_database(engine)
    _require_clean_state(engine)
    # Record against a hash-free copy: a stale hash would make the inner adapter diverge mid-script
    # and the steps after it would never be requested, let alone observed.
    blank = _without_hashes(transcript)
    recorded: dict[tuple[int, str], list] = {}
    for first in (t for t in transcript.turns if t.turn_index == 0):
        language = _language_of(first)
        session_id = uuid4()
        with engine.begin() as conn:
            store.insert_session(
                conn,
                session_id=session_id,
                language=language,
                agent_mode=AgentMode.REPLAY,
                scenario_context_id=transcript.scenario_context_id,
                prompt_version=transcript.prompt_version,
                tool_schema_version=transcript.tool_schema_version,
                model_id=None,
            )
        with tempfile.TemporaryDirectory() as scratch:
            recorder = RecordingAgentModel(
                ReplayAgentModel(blank, pacing=False), Path(scratch) / "recording.json", pins
            )
            for turn in _script_turns(transcript, first):
                loop.run_turn(
                    engine, recorder, session_id=session_id, key=str(uuid4()), body=TurnRequest(text=turn.user_text)
                )
            for turn in recorder.transcript().turns:
                recorded[(turn.turn_index, fold(turn.user_text_folded))] = turn.steps
        _purge_intake_session(engine, session_id)
    filled = _without_hashes(transcript)  # a hash this run did not observe is null, never a stale value
    for turn in filled.turns:
        steps = recorded.get((turn.turn_index, fold(turn.user_text_folded)), [])
        for step, seen in zip(turn.steps, steps, strict=False):
            if step.expect is not None and seen.expect is not None:
                step.expect.tool_result_sha256 = seen.expect.tool_result_sha256
    return filled


def _without_hashes(transcript: Transcript) -> Transcript:
    copy = transcript.model_copy(deep=True)
    for turn in copy.turns:
        for step in turn.steps:
            if step.expect is not None:
                step.expect.tool_result_sha256 = None
    return copy


def _language_of(turn: TranscriptTurn):
    from contracts.models.policy import Language

    first = turn.steps[0].model
    if isinstance(first, ToolCallModelStep) and first.args.get("preferredLanguage") in ("ES", "EN"):
        return Language(first.args["preferredLanguage"])
    return Language.EN


def _script_turns(transcript: Transcript, first: TranscriptTurn) -> list[TranscriptTurn]:
    """The script starting at ``first``: turn 0 then every higher turn index (one script per index > 0)."""
    later = sorted((t for t in transcript.turns if t.turn_index > 0), key=lambda t: t.turn_index)
    return [first, *later]


def _require_test_database(engine) -> None:
    name = (engine.url.database or "").rsplit("/", 1)[-1]
    if "test" not in name:
        raise SystemExit(f"--fill-hashes purges the intake rows it writes; refusing to run on database {name!r}")


def _require_clean_state(engine) -> None:
    """Hashes are only meaningful from the state a demo reset leaves: a leftover intake record from an
    earlier session is itself a candidate and would change every ToolResult recorded here."""
    from sqlalchemy import text

    with engine.connect() as conn:
        leftovers = conn.execute(
            text(
                "SELECT (SELECT count(*) FROM source_record WHERE kind = 'FRONTDESK_INTAKE') "
                "+ (SELECT count(*) FROM intake_session)"
            )
        ).scalar_one()
    if leftovers:
        raise SystemExit(
            f"--fill-hashes needs a clean state; {leftovers} intake record(s)/session(s) are left over. "
            "Purge them (or reset the demo) and run again."
        )


def _purge_intake_session(engine, session_id) -> None:
    """Remove one fill run's rows: events, handoff pairs and decisions, the intake record, the session."""
    from sqlalchemy import text

    with engine.begin() as conn:
        record = conn.execute(
            text("SELECT intake_record_id FROM intake_session WHERE id = :s"), {"s": session_id}
        ).scalar()
        pairs = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT id FROM candidate_pair WHERE intake_session_id = :s OR record_a_id = :r OR record_b_id = :r"
                ),
                {"s": session_id, "r": record},
            )
        ]
        conn.execute(
            text("DELETE FROM event_log WHERE intake_session_id = :s OR pair_id = ANY(:p)"),
            {"s": session_id, "p": pairs},
        )
        conn.execute(text("DELETE FROM match_decision WHERE pair_id = ANY(:p)"), {"p": pairs})
        conn.execute(text("DELETE FROM candidate_pair WHERE id = ANY(:p)"), {"p": pairs})
        conn.execute(text("DELETE FROM intake_session WHERE id = :s"), {"s": session_id})
        if record is not None:
            conn.execute(text("DELETE FROM source_record WHERE id = :r"), {"r": record})


if __name__ == "__main__":
    raise SystemExit(main())
