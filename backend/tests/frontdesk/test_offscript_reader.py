"""Off-script reader (REPLAY, FRONTDESK_OFFSCRIPT_READER=on): rules-based extraction, the same tool
flow through the same gate, and the scripted lines and the flag-off path unchanged.

Author: Christian Flores (offscript-reader builder).
"""

from __future__ import annotations

import dataclasses
from uuid import uuid4

import pytest

from backend.app.config import Settings, load_settings
from backend.frontdesk import adapters
from backend.frontdesk.model import ErrorStep, Message, ModelRequest, TextStep, ToolCallStep
from backend.frontdesk.offscript import (
    OffscriptReplayModel,
    extract,
)
from backend.frontdesk.replay import ReplayAgentModel, build_replay_model, fold
from backend.frontdesk.templates import TEMPLATE_LINE, banned_phrase
from backend.policy.args import demographics_grounded
from backend.tests.frontdesk.conftest import create_session, turn
from contracts.models.intake import AgentMode, IntakeTurn, RegistrationState
from contracts.models.policy import Language, PolicyOutcome, PolicyReason, ProposeArgs, SearchArgs
from contracts.version import TOOL_SCHEMA_VERSION

SOFIA_VARIANT = "sofia mesa lopez, born 5/16/1964, phone 555 757 3688"
NEW_PATIENT_EN = "Hi, my name is Zebulon Quarrington-Vance, born March 14, 1987, my phone is (512) 555-0199."
NEW_PATIENT_ES = "Me llamo Ximena Ébano Quiroga, nací el 3 de febrero de 1979, vivo en 12 Calle Pino, 78701"


# ---- extraction ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "iso", "quote"),
    [
        ("born May 16, 1964", "1964-05-16", "May 16, 1964"),
        ("born 16 May 1964", "1964-05-16", "16 May 1964"),
        ("born 5/16/1964", "1964-05-16", "5/16/1964"),
        ("born 1964-05-16", "1964-05-16", "1964-05-16"),
        ("nací el 16 de mayo de 1964", "1964-05-16", "16 de mayo de 1964"),
    ],
)
def test_each_date_format_reads_to_iso_with_the_typed_quote(text, iso, quote):
    found = extract(text)
    assert found.birth_date is not None
    assert (found.birth_date.value, found.birth_date.quote) == (iso, quote)


def test_an_impossible_date_is_not_read():
    assert extract("born 2/31/1990").birth_date is None


def test_english_sample_reads_name_date_phone_exactly_as_typed():
    found = extract(NEW_PATIENT_EN)
    assert found.given_name.value == "Zebulon"
    assert found.family_name.value == "Quarrington-Vance"
    assert found.birth_date.value == "1987-03-14"
    assert found.phone.value == "(512) 555-0199"
    assert found.address_line is None


def test_spanish_sample_keeps_accents_and_reads_address_and_zip():
    found = extract(NEW_PATIENT_ES)
    assert (found.given_name.value, found.family_name.value) == ("Ximena", "Ébano Quiroga")
    assert found.birth_date.value == "1979-02-03"
    assert found.address_line.value == "12 Calle Pino"
    assert found.postal_code.value == "78701"
    assert found.phone is None


def test_scripted_sofia_es_line_reads_like_the_transcript():
    found = extract(
        "Me llamo Sofia Mesa-López, nací el 16 de mayo de 1964, mi teléfono es 555-757-3688, vivo en 899 Sawayn Trafficway."
    )
    assert (found.given_name.value, found.family_name.value) == ("Sofia", "Mesa-López")
    assert found.birth_date.quote == "16 de mayo de 1964"
    assert found.phone.value == "555-757-3688"
    assert found.address_line.value == "899 Sawayn Trafficway"


@pytest.mark.parametrize(
    ("text", "given", "family"),
    [
        ("I'm Ana Ruiz, born 1/2/1990", "Ana", "Ruiz"),
        ("I am Ana Ruiz born 1/2/1990", "Ana", "Ruiz"),
        ("Soy Teodoro Quintanilla Abasolo, nací el 9 de noviembre de 1951", "Teodoro", "Quintanilla Abasolo"),
        ("Mi nombre es Ana Ruiz", "Ana", "Ruiz"),
        (SOFIA_VARIANT, "sofia", "mesa lopez"),
    ],
)
def test_name_cues_and_a_leading_name(text, given, family):
    found = extract(text)
    assert (found.given_name.value, found.family_name.value) == (given, family)


def test_no_name_from_a_greeting_or_a_lone_token():
    assert extract("Hello, born 1/2/1990").given_name is None
    assert extract("I'm Ana, born 1/2/1990").given_name is None


def test_every_extracted_field_grounds_through_the_gate_check():
    for text in (NEW_PATIENT_EN, NEW_PATIENT_ES, SOFIA_VARIANT):
        args = extract(text).search_args()
        assert demographics_grounded(SearchArgs.model_validate(args), [text])
        propose = extract(text).propose_args(Language.EN)
        assert demographics_grounded(ProposeArgs.model_validate(propose), [text])


# ---- reader steps (no database) -----------------------------------------------------------------


def _req(texts: list[str], turn_index: int = 0, step: int = 0, extra: tuple = (), lang=Language.EN) -> ModelRequest:
    messages = []
    for t in texts[:-1]:
        messages += [Message(role="user", text=t), Message(role="model", text="...")]
    messages.append(Message(role="user", text=texts[-1]))
    return ModelRequest(
        session_id=uuid4(),
        turn_index=turn_index,
        step_index=step,
        language=lang,
        prompt_version="fd-prompt/1",
        tool_schema_version=TOOL_SCHEMA_VERSION,
        system_instruction="",
        messages=tuple(messages) + extra,
        tools=(),
        user_text_folded=fold(texts[-1]),
        last_tool_result_sha256=None,
    )


@pytest.fixture
def wrapped() -> OffscriptReplayModel:
    inner = build_replay_model({"FRONTDESK_REPLAY_PACING": "0"})
    assert isinstance(inner, ReplayAgentModel)
    return OffscriptReplayModel(inner)


def test_missing_name_or_dob_asks_for_both(wrapped):
    step = wrapped.next_step(_req(["my phone is 555-123-4567"]))
    assert isinstance(step, TextStep)
    assert "name" in step.text and "date of birth" in step.text


def test_missing_phone_and_address_asks_for_one(wrapped):
    step = wrapped.next_step(_req(["My name is Ana Ruiz, born 1/2/1990"], lang=Language.ES))
    assert isinstance(step, TextStep)
    assert "teléfono" in step.text and "dirección" in step.text


def test_complete_text_calls_search_then_propose(wrapped):
    first = wrapped.next_step(_req([NEW_PATIENT_EN]))
    assert isinstance(first, ToolCallStep) and first.tool_name == "search_patients"
    assert first.mode == AgentMode.REPLAY
    result = Message(role="function", tool_call=first, tool_result={"status": "ALLOWED", "reasonCode": None})
    second = wrapped.next_step(_req([NEW_PATIENT_EN], step=1, extra=(Message(role="model", tool_call=first), result)))
    assert isinstance(second, ToolCallStep) and second.tool_name == "propose_new_chart"
    assert second.args["preferredLanguage"] == "EN" and second.args["sex"] == "UNKNOWN"


def test_reader_texts_pass_the_banned_phrase_check():
    from backend.frontdesk.offscript import REPLIES

    for lang in Language:
        for key, text in REPLIES[lang].items():
            assert banned_phrase(text.format(given="Ana"), new_chart_created=key == "started") is None


def test_scripted_steps_are_byte_for_byte_the_replay_adapter(wrapped):
    inner = wrapped.inner
    for scripted in inner.transcript.turns:
        for step in scripted.steps:
            req = _req([scripted.user_text], turn_index=scripted.turn_index, step=step.step_index)
            assert wrapped.next_step(req) == inner.next_step(req)


def test_a_real_divergence_inside_a_scripted_turn_still_degrades(wrapped):
    scripted = wrapped.inner.transcript.turns[0]
    req = dataclasses.replace(_req([scripted.user_text], step=1), last_tool_result_sha256="0" * 64)
    assert wrapped.next_step(req) == ErrorStep(kind="REPLAY_DIVERGED", retryable=False, mode=AgentMode.REPLAY)


# ---- setting and wiring -------------------------------------------------------------------------


def test_setting_defaults_off_and_reads_on(monkeypatch):
    monkeypatch.delenv("FRONTDESK_OFFSCRIPT_READER", raising=False)
    assert load_settings().frontdesk_offscript_reader is False
    monkeypatch.setenv("FRONTDESK_OFFSCRIPT_READER", "on")
    assert load_settings().frontdesk_offscript_reader is True
    monkeypatch.setenv("FRONTDESK_OFFSCRIPT_READER", "off")
    assert load_settings().frontdesk_offscript_reader is False


def _settings(on: bool) -> Settings:
    return dataclasses.replace(load_settings(), frontdesk_agent_mode="REPLAY", frontdesk_offscript_reader=on)


def test_make_model_wraps_replay_only_when_the_flag_is_on():
    assert isinstance(adapters.make_model(AgentMode.REPLAY, _settings(False)), ReplayAgentModel)
    assert isinstance(adapters.make_model(AgentMode.REPLAY, _settings(True)), OffscriptReplayModel)


# ---- through the real loop, executor, gate and database -----------------------------------------


@pytest.fixture
def reader_on(model_factory_override):
    model_factory_override(lambda mode, settings: adapters.make_model(mode, _settings(True)))


@pytest.fixture
def reader_off(model_factory_override):
    model_factory_override(lambda mode, settings: adapters.make_model(mode, _settings(False)))


def _turn(client, session_id: str, text: str) -> IntakeTurn:
    r = turn(client, session_id, text)
    assert r.status_code == 201, r.text
    return IntakeTurn.model_validate(r.json())


def test_flag_off_keeps_the_template_and_runs_no_tool(client, reader_off, intake_sessions):
    sid = create_session(client, "EN")["id"]
    intake_sessions.append(sid)
    t = _turn(client, sid, NEW_PATIENT_EN)
    assert t.assistant_text == TEMPLATE_LINE[Language.EN]
    assert t.tool_calls == [] and t.degraded == "REPLAY_INPUT_MISMATCH"


def test_a_new_made_up_patient_gets_a_new_chart(client, reader_on, intake_sessions):
    sid = create_session(client, "EN")["id"]
    intake_sessions.append(sid)
    t = _turn(client, sid, NEW_PATIENT_EN)
    assert [(c.tool_name, c.gate.outcome) for c in t.tool_calls] == [
        ("search_patients", PolicyOutcome.ALLOW),
        ("propose_new_chart", PolicyOutcome.ALLOW),
    ]
    assert t.registration.state == RegistrationState.NEW_CHART
    assert t.degraded is None
    assert t.assistant_text == (
        "Thank you, Zebulon. We have started your registration; a registrar will finish it with you in a moment."
    )


def test_a_spanish_new_patient_gets_the_spanish_reply(client, reader_on, intake_sessions):
    sid = create_session(client, "ES")["id"]
    intake_sessions.append(sid)
    t = _turn(client, sid, NEW_PATIENT_ES)
    assert t.registration.state == RegistrationState.NEW_CHART
    assert t.assistant_text.startswith("Gracias, Ximena. Hemos iniciado su registro")


def test_a_sofia_variant_is_held_for_a_registrar(client, reader_on, hero_records, intake_sessions):
    sid = create_session(client, "EN")["id"]
    intake_sessions.append(sid)
    t = _turn(client, sid, SOFIA_VARIANT)
    propose = t.tool_calls[-1]
    assert propose.tool_name == "propose_new_chart"
    assert (propose.gate.outcome, propose.gate.reason_code) == (
        PolicyOutcome.DENY,
        PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER,
    )
    assert propose.gate.handoff_required is True
    assert t.registration.state == RegistrationState.PENDING_REGISTRAR
    assert t.assistant_text == "Thank you, Sofia. A registrar will confirm your record in a moment."


def test_missing_dob_asks_and_a_second_message_completes_it(client, reader_on, intake_sessions):
    sid = create_session(client, "EN")["id"]
    intake_sessions.append(sid)
    first = _turn(client, sid, "My name is Zebulon Quarrington-Vance, my phone is (512) 555-0199.")
    assert first.tool_calls == [] and first.degraded is None
    assert first.assistant_text == "Please tell me your full name and date of birth."
    second = _turn(client, sid, "I was born on March 14, 1987")
    assert [c.tool_name for c in second.tool_calls] == ["search_patients", "propose_new_chart"]
    assert second.registration.state == RegistrationState.NEW_CHART


def test_scripted_line_still_replays_the_transcript_with_the_flag_on(client, reader_on, hero_records, intake_sessions):
    inner = build_replay_model({"FRONTDESK_REPLAY_PACING": "0"})
    scripted = next(t for t in inner.transcript.turns if t.user_text.startswith("My name is Sofia"))
    sid = create_session(client, "EN", inner.transcript.scenario_context_id)["id"]
    intake_sessions.append(sid)
    t = _turn(client, sid, scripted.user_text)
    assert [c.tool_name for c in t.tool_calls] == ["propose_new_chart"]  # the script, not the reader's search
    assert t.assistant_text == scripted.steps[-1].model.text
    assert t.tool_calls[0].gate.reason_code == PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER
