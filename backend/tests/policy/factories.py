"""Builders for the policy tests: one well-formed action and candidate, overridable per field."""

from __future__ import annotations

from uuid import uuid4

from contracts.models.common import Band, DecisionStatus
from contracts.models.policy import (
    AgentAction,
    AttachArgs,
    Evidence,
    HistoryItem,
    HistoryKind,
    Language,
    ProposeArgs,
    ScoredCandidate,
    SearchArgs,
    SessionFacts,
    Sex,
    ToolName,
)

USER_TEXT = "Soy María José González Rivera, nací el 3 de julio de 1985, mujer, teléfono 555 010 0100"
EVIDENCE = Evidence(
    given_name="María José",
    family_name="González Rivera",
    birth_date="3 de julio de 1985",
    sex="mujer",
    phone="555 010 0100",
)


def propose_args(**overrides) -> ProposeArgs:
    base = {
        "given_name": "Maria Jose",
        "family_name": "Gonzalez Rivera",
        "birth_date": "1985-07-03",
        "sex": Sex.FEMALE,
        "phone": "5550100100",
        "preferred_language": Language.ES,
        "evidence": EVIDENCE,
    }
    base.update(overrides)
    return ProposeArgs(**base)


def search_args(**overrides) -> SearchArgs:
    base = {"given_name": "Maria Jose", "family_name": "Gonzalez Rivera", "evidence": EVIDENCE}
    base.update(overrides)
    return SearchArgs(**base)


def attach_args() -> AttachArgs:
    return AttachArgs(
        items=[HistoryItem(kind=HistoryKind.ALLERGY, text="amoxicillin", evidence_quote="alergia a la amoxicilina")]
    )


def session(**overrides) -> SessionFacts:
    base = {"tool_calls_this_turn": 1, "identical_call_count": 0}
    base.update(overrides)
    return SessionFacts(**base)


def action(tool: str = ToolName.PROPOSE_NEW_CHART.value, args=None, **overrides) -> AgentAction:
    if args is None:
        args = {
            ToolName.PROPOSE_NEW_CHART.value: propose_args,
            ToolName.SEARCH_PATIENTS.value: search_args,
            ToolName.ATTACH_HISTORY.value: attach_args,
        }.get(tool, propose_args)()
    base = {"tool": tool, "args": args, "args_sha256": "a" * 64, "grounding_ok": True, "session": session()}
    base.update(overrides)
    return AgentAction(**base)


def candidate(
    band: Band = Band.REVIEW,
    s: float = 1.0,
    human_status: DecisionStatus | None = None,
    **overrides,
) -> ScoredCandidate:
    base = {
        "record_id": uuid4(),
        "source_system": "ER_FHIR",
        "s": s,
        "p": 0.5,
        "band": band,
        "human_status": human_status,
        "pair_id": uuid4() if human_status else None,
        "decision_id": uuid4() if human_status else None,
        "evidence_snapshot_sha256": "0" * 64,
    }
    base.update(overrides)
    return ScoredCandidate(**base)
