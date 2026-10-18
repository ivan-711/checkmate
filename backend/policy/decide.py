"""``decide``: the 13-row decision table of ADR-016 §3. Pure: no I/O, clock or randomness.

Row order is the order in the contract stub's docstring; the first matching row wins. Bands are
read from the candidate (already cut on the raw score ``s``); ``p`` is never consulted here.
"""

from __future__ import annotations

from collections.abc import Sequence

from backend.policy.tokens import PolicyAllow, PolicyHandoff
from contracts.models.common import Band, DecisionStatus
from contracts.models.policy import (
    HANDOFF_REASONS,
    AgentAction,
    EvidenceKind,
    EvidenceRef,
    InvalidArgs,
    PolicyDecision,
    PolicyOutcome,
    PolicyReason,
    ProposeArgs,
    ScoredCandidate,
    ToolName,
)
from contracts.version import MAX_IDENTICAL_CALLS_PER_SESSION, MAX_TOOL_CALLS_PER_TURN

BLOCKING_BANDS: frozenset[Band] = frozenset({Band.REVIEW, Band.AUTO_LINK})
# A pair with no human decision yet, or only the gate's own proposal, is still unresolved.
UNRESOLVED_STATUSES: frozenset[DecisionStatus | None] = frozenset({None, DecisionStatus.PROPOSED})

MESSAGE_KEYS: dict[PolicyReason | None, str] = {
    None: "gate.allow",
    **{reason: f"gate.deny.{reason.value.lower()}" for reason in PolicyReason},
}
ALLOW_MESSAGE_KEYS: dict[ToolName, str] = {
    ToolName.SEARCH_PATIENTS: "gate.allow.search",
    ToolName.PROPOSE_NEW_CHART: "gate.allow.propose",
    ToolName.ATTACH_HISTORY: "gate.allow.attach",
}


def _deny(reason: PolicyReason, evidence: Sequence[EvidenceRef] = ()) -> PolicyDecision:
    return PolicyDecision(
        outcome=PolicyOutcome.DENY,
        reason_code=reason,
        handoff_required=reason in HANDOFF_REASONS,
        evidence_ids=list(evidence),
        message_key=MESSAGE_KEYS[reason],
    )


def _allow(tool: ToolName, evidence: Sequence[EvidenceRef] = ()) -> PolicyDecision:
    return PolicyDecision(
        outcome=PolicyOutcome.ALLOW,
        reason_code=None,
        handoff_required=False,
        evidence_ids=list(evidence),
        message_key=ALLOW_MESSAGE_KEYS[tool],
    )


def _record_ref(c: ScoredCandidate) -> EvidenceRef:
    return EvidenceRef(kind=EvidenceKind.CANDIDATE_RECORD, id=c.record_id)


def _ordered(candidates: Sequence[ScoredCandidate]) -> list[ScoredCandidate]:
    """A fixed order so the evidence list does not depend on how the caller sorted the input."""
    return sorted(candidates, key=lambda c: (-c.s, str(c.record_id)))


def incomplete_demographics(args: ProposeArgs) -> bool:
    """Row 7: the four identity fields plus either a phone or (address line and postal code)."""
    if not (args.given_name and args.family_name and args.birth_date and args.sex):
        return True
    return not (args.phone or (args.address_line and args.postal_code))


def decide(action: AgentAction, candidates: Sequence[ScoredCandidate]) -> PolicyDecision:
    session = action.session
    if action.tool not in {t.value for t in ToolName}:
        return _deny(PolicyReason.UNKNOWN_TOOL)
    tool = ToolName(action.tool)
    if session.session_closed:
        return _deny(PolicyReason.SESSION_CLOSED)
    if (
        session.tool_calls_this_turn > MAX_TOOL_CALLS_PER_TURN
        or session.identical_call_count >= MAX_IDENTICAL_CALLS_PER_SESSION
    ):
        return _deny(PolicyReason.LOOP_GUARD)
    if isinstance(action.args, InvalidArgs):
        return _deny(PolicyReason.INVALID_ARGUMENTS)
    if not action.grounding_ok:
        return _deny(PolicyReason.UNGROUNDED_FIELD)

    ordered = _ordered(candidates)
    if tool == ToolName.SEARCH_PATIENTS:
        return _allow(tool, [_record_ref(c) for c in ordered])

    if tool == ToolName.PROPOSE_NEW_CHART:
        if not isinstance(action.args, ProposeArgs) or incomplete_demographics(action.args):
            return _deny(PolicyReason.INCOMPLETE_DEMOGRAPHICS)
        if session.intake_record_id is not None and action.args_sha256 != session.intake_args_sha256:
            return _deny(PolicyReason.INTAKE_ALREADY_RECORDED)
        linked = [c for c in ordered if c.human_status == DecisionStatus.LINKED]
        if linked:
            evidence: list[EvidenceRef] = []
            for c in linked:
                if c.decision_id is not None:
                    evidence.append(EvidenceRef(kind=EvidenceKind.MATCH_DECISION, id=c.decision_id))
                evidence.append(_record_ref(c))
            return _deny(PolicyReason.ALREADY_LINKED, evidence)
        blocking = [c for c in ordered if c.human_status in UNRESOLVED_STATUSES and c.band in BLOCKING_BANDS]
        if blocking:
            return _deny(PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER, [_record_ref(c) for c in blocking])
        return _allow(tool, [_record_ref(c) for c in ordered])

    # attach_history
    if session.intake_record_id is None:
        return _deny(PolicyReason.NO_INTAKE_RECORD)
    return _allow(tool, [EvidenceRef(kind=EvidenceKind.INTAKE_RECORD, id=session.intake_record_id)])


def allow_token(decision: PolicyDecision) -> PolicyAllow:
    """The capability an ALLOW write needs; raises ``TokenMismatch`` for any other decision."""
    return PolicyAllow(decision)


def handoff_token(decision: PolicyDecision) -> PolicyHandoff:
    """The capability the handoff writes need; raises unless DENY CANDIDATE_IN_REVIEW_OR_HIGHER."""
    return PolicyHandoff(decision)
