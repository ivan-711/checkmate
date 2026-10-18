"""The 13-row table of ADR-016 §3, one test per row, plus first-match-wins ordering."""

from __future__ import annotations

import random

import pytest

from backend.policy.decide import MESSAGE_KEYS, allow_token, decide, handoff_token
from backend.policy.tokens import TokenMismatch
from backend.tests.policy.factories import action, attach_args, candidate, propose_args, session
from contracts.models.common import Band, DecisionStatus
from contracts.models.policy import EvidenceKind, InvalidArgs, PolicyOutcome, PolicyReason, ToolName
from contracts.version import MAX_IDENTICAL_CALLS_PER_SESSION, MAX_TOOL_CALLS_PER_TURN, POLICY_VERSION

PROPOSE = ToolName.PROPOSE_NEW_CHART.value
SEARCH = ToolName.SEARCH_PATIENTS.value
ATTACH = ToolName.ATTACH_HISTORY.value


def deny(d, reason, handoff=False):
    assert d.outcome == PolicyOutcome.DENY
    assert d.reason_code == reason
    assert d.handoff_required is handoff
    assert d.message_key == MESSAGE_KEYS[reason] == f"gate.deny.{reason.value.lower()}"
    assert d.policy_version == POLICY_VERSION


def test_row_1_unknown_tool():
    deny(decide(action("create_patient", args=InvalidArgs(raw={}, errors=["x"])), []), PolicyReason.UNKNOWN_TOOL)


def test_row_2_session_closed():
    deny(decide(action(PROPOSE, session=session(session_closed=True)), []), PolicyReason.SESSION_CLOSED)


@pytest.mark.parametrize(
    "facts",
    [
        {"tool_calls_this_turn": MAX_TOOL_CALLS_PER_TURN + 1, "identical_call_count": 0},
        {"tool_calls_this_turn": 1, "identical_call_count": MAX_IDENTICAL_CALLS_PER_SESSION},
    ],
)
def test_row_3_loop_guard(facts):
    deny(decide(action(PROPOSE, session=session(**facts)), []), PolicyReason.LOOP_GUARD, handoff=True)


def test_row_3_boundary_is_not_a_loop():
    ok = session(tool_calls_this_turn=MAX_TOOL_CALLS_PER_TURN, identical_call_count=MAX_IDENTICAL_CALLS_PER_SESSION - 1)
    assert decide(action(PROPOSE, session=ok), []).outcome == PolicyOutcome.ALLOW


def test_row_4_invalid_arguments():
    deny(decide(action(PROPOSE, args=InvalidArgs(raw={}, errors=["bad"])), []), PolicyReason.INVALID_ARGUMENTS)


def test_row_5_ungrounded_field():
    deny(decide(action(PROPOSE, grounding_ok=False), []), PolicyReason.UNGROUNDED_FIELD)


def test_row_6_search_allows_with_candidate_evidence():
    cands = [candidate(Band.AUTO_LINK, s=3.0), candidate(Band.KEEP_SEPARATE, s=-1.0)]
    d = decide(action(SEARCH), cands)
    assert d.outcome == PolicyOutcome.ALLOW and d.reason_code is None and not d.handoff_required
    assert d.message_key == "gate.allow.search"
    assert [e.id for e in d.evidence_ids] == [c.record_id for c in cands]
    assert {e.kind for e in d.evidence_ids} == {EvidenceKind.CANDIDATE_RECORD}


@pytest.mark.parametrize(
    "overrides",
    [{"phone": None}, {"phone": None, "address_line": "1 Main St"}, {"phone": None, "postal_code": "54311"}],
)
def test_row_7_incomplete_demographics(overrides):
    deny(decide(action(PROPOSE, args=propose_args(**overrides)), []), PolicyReason.INCOMPLETE_DEMOGRAPHICS)


def test_row_7_address_and_postal_stand_in_for_phone():
    args = propose_args(phone=None, address_line="1 Main St", postal_code="54311")
    assert decide(action(PROPOSE, args=args), []).outcome == PolicyOutcome.ALLOW


def test_row_8_intake_already_recorded():
    facts = session(intake_record_id=candidate().record_id, intake_args_sha256="b" * 64)
    deny(decide(action(PROPOSE, session=facts), []), PolicyReason.INTAKE_ALREADY_RECORDED, handoff=True)


def test_row_8_same_args_pass_through():
    facts = session(intake_record_id=candidate().record_id, intake_args_sha256="a" * 64)
    assert decide(action(PROPOSE, session=facts), []).outcome == PolicyOutcome.ALLOW


def test_row_9_already_linked():
    linked = candidate(Band.KEEP_SEPARATE, human_status=DecisionStatus.LINKED)
    d = decide(action(PROPOSE), [candidate(Band.REVIEW), linked])
    deny(d, PolicyReason.ALREADY_LINKED)
    assert {(e.kind, e.id) for e in d.evidence_ids} == {
        (EvidenceKind.MATCH_DECISION, linked.decision_id),
        (EvidenceKind.CANDIDATE_RECORD, linked.record_id),
    }


@pytest.mark.parametrize("band", [Band.REVIEW, Band.AUTO_LINK])
@pytest.mark.parametrize("status", [None, DecisionStatus.PROPOSED])
def test_row_10_candidate_in_review_or_higher(band, status):
    blocking = candidate(band, s=2.0, human_status=status)
    d = decide(action(PROPOSE), [candidate(Band.KEEP_SEPARATE, s=-2.0), blocking])
    deny(d, PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER, handoff=True)
    assert [e.id for e in d.evidence_ids] == [blocking.record_id]


def test_row_11_propose_allows_with_all_candidates():
    cands = [
        candidate(Band.KEEP_SEPARATE, s=-1.0),
        candidate(Band.REVIEW, s=1.0, human_status=DecisionStatus.REJECTED),
        candidate(Band.KEEP_SEPARATE, s=-3.0, human_status=DecisionStatus.REVOKED),
    ]
    d = decide(action(PROPOSE), cands)
    assert d.outcome == PolicyOutcome.ALLOW and d.message_key == "gate.allow.propose"
    assert {e.id for e in d.evidence_ids} == {c.record_id for c in cands}


def test_row_12_no_intake_record():
    deny(decide(action(ATTACH), []), PolicyReason.NO_INTAKE_RECORD)


def test_row_13_attach_allows_with_intake_evidence():
    rid = candidate().record_id
    d = decide(action(ATTACH, session=session(intake_record_id=rid, intake_args_sha256="a" * 64)), [])
    assert d.outcome == PolicyOutcome.ALLOW and d.message_key == "gate.allow.attach"
    assert d.evidence_ids == [type(d.evidence_ids[0])(kind=EvidenceKind.INTAKE_RECORD, id=rid)]


def test_every_reason_has_a_message_key():
    assert set(MESSAGE_KEYS) == set(PolicyReason) | {None}


# --- first match wins -----------------------------------------------------------------


def test_unknown_tool_beats_closed_session_and_loop():
    facts = session(session_closed=True, tool_calls_this_turn=99, identical_call_count=99)
    deny(decide(action("nope", args=InvalidArgs(raw={}, errors=[]), session=facts), []), PolicyReason.UNKNOWN_TOOL)


def test_closed_session_beats_loop_guard():
    facts = session(session_closed=True, tool_calls_this_turn=99)
    deny(decide(action(PROPOSE, session=facts), []), PolicyReason.SESSION_CLOSED)


def test_loop_guard_beats_invalid_arguments():
    facts = session(identical_call_count=MAX_IDENTICAL_CALLS_PER_SESSION)
    d = decide(action(PROPOSE, args=InvalidArgs(raw={}, errors=[]), session=facts), [])
    deny(d, PolicyReason.LOOP_GUARD, handoff=True)


def test_invalid_beats_ungrounded():
    d = decide(action(PROPOSE, args=InvalidArgs(raw={}, errors=[]), grounding_ok=False), [])
    deny(d, PolicyReason.INVALID_ARGUMENTS)


def test_ungrounded_beats_candidates_for_search():
    deny(decide(action(SEARCH, grounding_ok=False), [candidate(Band.AUTO_LINK)]), PolicyReason.UNGROUNDED_FIELD)


def test_incomplete_beats_already_recorded_and_linked():
    facts = session(intake_record_id=candidate().record_id, intake_args_sha256="zzz")
    d = decide(
        action(PROPOSE, args=propose_args(phone=None), session=facts), [candidate(human_status=DecisionStatus.LINKED)]
    )
    deny(d, PolicyReason.INCOMPLETE_DEMOGRAPHICS)


def test_already_recorded_beats_linked():
    facts = session(intake_record_id=candidate().record_id, intake_args_sha256="zzz")
    d = decide(action(PROPOSE, session=facts), [candidate(human_status=DecisionStatus.LINKED)])
    deny(d, PolicyReason.INTAKE_ALREADY_RECORDED, handoff=True)


def test_linked_beats_review():
    d = decide(action(PROPOSE), [candidate(Band.AUTO_LINK), candidate(human_status=DecisionStatus.LINKED)])
    deny(d, PolicyReason.ALREADY_LINKED)


def test_attach_ignores_candidates():
    assert (
        decide(action(ATTACH, args=attach_args()), [candidate(Band.AUTO_LINK)]).reason_code
        == PolicyReason.NO_INTAKE_RECORD
    )


# --- invariants over random candidate lists --------------------------------------------


def random_candidates(rng: random.Random):
    out = []
    for _ in range(rng.randint(0, 8)):
        band = rng.choice(list(Band))
        status = rng.choice([None, *DecisionStatus])
        out.append(candidate(band, s=rng.uniform(-5, 5), human_status=status))
    return out


@pytest.mark.parametrize("seed", range(60))
def test_review_or_higher_iff_unresolved_blocking_candidate(seed):
    rng = random.Random(seed)
    cands = random_candidates(rng)
    linked = any(c.human_status == DecisionStatus.LINKED for c in cands)
    blocking = [
        c
        for c in cands
        if c.human_status in (None, DecisionStatus.PROPOSED, DecisionStatus.REVOKED)
        and c.band in (Band.REVIEW, Band.AUTO_LINK)
    ]
    d = decide(action(PROPOSE), cands)
    if linked:
        assert d.reason_code == PolicyReason.ALREADY_LINKED
    elif blocking:
        assert d.reason_code == PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER
        assert {e.id for e in d.evidence_ids} == {c.record_id for c in blocking}
    else:
        assert d.outcome == PolicyOutcome.ALLOW
    shuffled = list(cands)
    rng.shuffle(shuffled)
    again = decide(action(PROPOSE), shuffled)
    assert again == decide(action(PROPOSE), shuffled) == d


def test_rejected_candidate_never_blocks():
    cands = [candidate(Band.AUTO_LINK, s=4.0, human_status=DecisionStatus.REJECTED)]
    assert decide(action(PROPOSE), cands).outcome == PolicyOutcome.ALLOW


def test_revoked_link_is_unresolved_and_blocks_again():
    cands = [candidate(Band.REVIEW, s=1.0, human_status=DecisionStatus.REVOKED)]
    assert decide(action(PROPOSE), cands).reason_code == PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER


def test_keep_separate_never_blocks():
    cands = [
        candidate(Band.KEEP_SEPARATE, s=0.0),
        candidate(Band.KEEP_SEPARATE, s=0.0, human_status=DecisionStatus.PROPOSED),
    ]
    assert decide(action(PROPOSE), cands).outcome == PolicyOutcome.ALLOW


# --- tokens -------------------------------------------------------------------------------


def test_tokens_only_from_matching_decisions():
    allowed = decide(action(SEARCH), [])
    held = decide(action(PROPOSE), [candidate(Band.REVIEW)])
    assert allow_token(allowed).decision is allowed
    assert allow_token(allowed).tool == ToolName.SEARCH_PATIENTS
    assert allow_token(allowed, SEARCH).tool == ToolName.SEARCH_PATIENTS
    assert handoff_token(held).decision is held
    assert handoff_token(held, PROPOSE).tool == ToolName.PROPOSE_NEW_CHART
    with pytest.raises(TokenMismatch):
        allow_token(allowed, PROPOSE)  # a search ALLOW is never a propose capability
    with pytest.raises(TokenMismatch):
        handoff_token(held, ATTACH)
    with pytest.raises(TokenMismatch):
        allow_token(held)
    with pytest.raises(TokenMismatch):
        handoff_token(allowed)
    with pytest.raises(TokenMismatch):
        handoff_token(decide(action(PROPOSE, session=session(identical_call_count=9)), []))
