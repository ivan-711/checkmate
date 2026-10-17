"""Enums match the glossary; wire format is camelCase; tool args reject unknown keys."""
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from contracts.models.common import ActorType, Band, DecisionStatus, EventType, NegativeRule, ReasonCode
from contracts.models.policy import (
    AgentAction,
    AttachArgs,
    EvidenceKind,
    EvidenceRef,
    PolicyDecision,
    PolicyOutcome,
    PolicyReason,
    ProposeArgs,
    SearchArgs,
    SessionFacts,
    ToolName,
)
from contracts.models.reviews import ApproveRequest, RejectRequest, ReviewRequest
from contracts.models.whatifs import WhatIfButton

GLOSSARY_EVENTS = {
    "RECORD_INGESTED", "MATCH_RUN_COMPLETED", "PAIR_SCORED", "LINK_APPROVED", "LINK_REJECTED", "LINK_REVOKED",
    "ENTITY_MERGED", "ENTITY_SPLIT", "ALERT_RAISED", "ALERT_RETRACTED", "WHATIF_APPLIED", "DEMO_RESET",
    "DEMO_RESTORED", "EXPLANATION_GENERATED", "EXTERNAL_CALL", "EVAL_RUN_STARTED", "EVAL_RUN_FINISHED",
    "INTAKE_STARTED", "AGENT_TOOL_CALLED", "INTAKE_HANDOFF_CREATED", "AGENT_TURN_DEGRADED",
}
GLOSSARY_REASONS = {
    "UNKNOWN_TOOL", "SESSION_CLOSED", "INVALID_ARGUMENTS", "UNGROUNDED_FIELD", "LOOP_GUARD",
    "INCOMPLETE_DEMOGRAPHICS", "INTAKE_ALREADY_RECORDED", "ALREADY_LINKED", "CANDIDATE_IN_REVIEW_OR_HIGHER",
    "NO_INTAKE_RECORD",
}
MIGRATION = Path(__file__).parents[1] / "migrations" / "0001_initial.sql"


def test_glossary_enums():
    assert {e.value for e in Band} == {"AUTO_LINK", "REVIEW", "KEEP_SEPARATE"}
    assert {e.value for e in DecisionStatus} == {"PROPOSED", "LINKED", "REJECTED", "REVOKED"}
    assert {e.value for e in ReasonCode} == {"DIFFERENT_PERSON", "INSUFFICIENT_EVIDENCE"}
    assert {e.value for e in ActorType} == {"AGENT", "REGISTRAR", "PATIENT", "SYSTEM"}
    assert {e.value for e in EventType} == GLOSSARY_EVENTS
    assert {e.value for e in PolicyReason} == GLOSSARY_REASONS
    assert {e.value for e in WhatIfButton} == {"REMOVE_ADDRESS", "CHANGE_BIRTH_YEAR", "SWAP_DOB_DAY_MONTH", "ACCENT_HYPHEN_SURNAME"}
    assert {e.value for e in ToolName} == {"search_patients", "propose_new_chart", "attach_history"}
    assert "STRONG_ID_CONFLICT" in {e.value for e in NegativeRule}


def test_migration_check_list_matches_event_enum():
    sql = MIGRATION.read_text()
    for value in GLOSSARY_EVENTS:
        assert f"'{value}'" in sql, value
    assert "event_type         text NOT NULL CHECK" in sql  # TEXT + CHECK, not an enum


def test_wire_format_is_camel_case():
    req = RejectRequest(action="REJECT", actor="registrar:Registrar A", reason_code="DIFFERENT_PERSON", note="ok")
    dumped = req.model_dump(by_alias=True)
    assert "reasonCode" in dumped and "reason_code" not in dumped
    adapter = TypeAdapter(ReviewRequest)
    assert isinstance(adapter.validate_python({"action": "APPROVE", "actor": "registrar:Registrar A"}), ApproveRequest)


def test_review_reject_requires_reason():
    adapter = TypeAdapter(ReviewRequest)
    with pytest.raises(ValidationError):
        adapter.validate_python({"action": "REJECT", "actor": "registrar:Registrar A"})
    with pytest.raises(ValidationError):
        adapter.validate_python({"action": "REJECT", "actor": "registrar:Registrar A", "reasonCode": None})
    with pytest.raises(ValidationError):
        adapter.validate_python({"action": "TOGGLE", "actor": "registrar:Registrar A"})


def test_tool_args_forbid_extra_and_ids():
    ev = {"givenName": "me llamo María"}
    ProposeArgs.model_validate({"givenName": "María", "familyName": "González Rivera", "birthDate": "1985-07-03",
                                "sex": "FEMALE", "preferredLanguage": "ES", "evidence": ev})
    for bad in ({"recordId": "x"}, {"score": 0.9}, {"band": "KEEP_SEPARATE"}, {"override": True}):
        with pytest.raises(ValidationError):
            ProposeArgs.model_validate({"givenName": "M", "familyName": "G", "birthDate": "1985-07-03", "sex": "FEMALE",
                                        "preferredLanguage": "ES", "evidence": ev, **bad})
    with pytest.raises(ValidationError):
        AttachArgs.model_validate({"items": [{"kind": "ALLERGY", "text": "x", "evidenceQuote": "x"}], "targetRecordId": "y"})
    with pytest.raises(ValidationError):
        SearchArgs.model_validate({"givenName": "María", "evidence": ev})  # needs family name or DOB


def test_policy_decision_invariants():
    PolicyDecision(outcome=PolicyOutcome.ALLOW, handoff_required=False, message_key="gate.allow")
    PolicyDecision(outcome=PolicyOutcome.DENY, reason_code=PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER,
                   handoff_required=True, message_key="gate.review",
                   evidence_ids=[EvidenceRef(kind=EvidenceKind.CANDIDATE_RECORD, id="00000000-0000-4000-8000-000000000001")])
    with pytest.raises(ValidationError):
        PolicyDecision(outcome=PolicyOutcome.DENY, handoff_required=False, message_key="x")
    with pytest.raises(ValidationError):
        PolicyDecision(outcome=PolicyOutcome.DENY, reason_code=PolicyReason.UNKNOWN_TOOL, handoff_required=True, message_key="x")


def test_decide_is_declared_not_implemented():
    from contracts.models.policy import decide
    action = AgentAction(tool="search_patients", args=SearchArgs(birth_date="1985-07-03", evidence={}),
                         args_sha256="0" * 64, grounding_ok=True,
                         session=SessionFacts(tool_calls_this_turn=1, identical_call_count=0))
    with pytest.raises(NotImplementedError):
        decide(action, [])
