"""Paired-reviewer probes for lane Q1.1 (review/q1-1). Independent of the builder's tests."""

from __future__ import annotations

import random
from uuid import uuid4

import pytest

from backend.policy import decide as decide_mod
from backend.policy.args import parse_action
from backend.policy.decide import decide
from backend.tests.policy.factories import EVIDENCE, USER_TEXT, action, attach_args, candidate, propose_args, session
from contracts.models.common import Band, DecisionStatus
from contracts.models.policy import (
    EvidenceKind,
    InvalidArgs,
    PolicyOutcome,
    PolicyReason,
    SessionFacts,
)

FACTS = SessionFacts(tool_calls_this_turn=1, identical_call_count=0)


def deny(reason: PolicyReason, decision):
    assert decision.outcome == PolicyOutcome.DENY, decision
    assert decision.reason_code == reason, decision
    assert decision.policy_version == "frontdesk-gate/1"
    assert decision.handoff_required == (
        reason
        in {PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER, PolicyReason.LOOP_GUARD, PolicyReason.INTAKE_ALREADY_RECORDED}
    )


# --- 13-row table and ordering traps -------------------------------------------------------------

TABLE = [
    # (name, action kwargs, candidates, expected reason or None)
    ("r1 unknown tool", dict(tool="create_chart"), [], PolicyReason.UNKNOWN_TOOL),
    ("r1 beats closed", dict(tool="create_chart", session=session(session_closed=True)), [], PolicyReason.UNKNOWN_TOOL),
    ("r2 closed", dict(session=session(session_closed=True)), [], PolicyReason.SESSION_CLOSED),
    (
        "r2 beats loop",
        dict(session=session(session_closed=True, tool_calls_this_turn=9)),
        [],
        PolicyReason.SESSION_CLOSED,
    ),
    ("r3 calls 7", dict(session=session(tool_calls_this_turn=7)), [], PolicyReason.LOOP_GUARD),
    ("r3 identical 3", dict(session=session(identical_call_count=3)), [], PolicyReason.LOOP_GUARD),
    (
        "r3 beats invalid",
        dict(session=session(identical_call_count=3), args=InvalidArgs(raw={}, errors=["x"])),
        [],
        PolicyReason.LOOP_GUARD,
    ),
    ("r4 invalid", dict(args=InvalidArgs(raw={}, errors=["x"])), [], PolicyReason.INVALID_ARGUMENTS),
    (
        "r4 beats ungrounded",
        dict(args=InvalidArgs(raw={}, errors=["x"]), grounding_ok=False),
        [],
        PolicyReason.INVALID_ARGUMENTS,
    ),
    ("r5 ungrounded", dict(grounding_ok=False), [candidate(Band.AUTO_LINK)], PolicyReason.UNGROUNDED_FIELD),
    ("r6 search allowed even with AUTO_LINK", dict(tool="search_patients"), [candidate(Band.AUTO_LINK)], None),
    (
        "r7 no phone no address",
        dict(args=propose_args(phone=None)),
        [],
        PolicyReason.INCOMPLETE_DEMOGRAPHICS,
    ),
    (
        "r7 address without postal",
        dict(args=propose_args(phone=None, address_line="1 Main")),
        [],
        PolicyReason.INCOMPLETE_DEMOGRAPHICS,
    ),
    ("r7 address+postal ok", dict(args=propose_args(phone=None, address_line="1 Main", postal_code="54311")), [], None),
    (
        "r7 beats recorded",
        dict(args=propose_args(phone=None), session=session(intake_record_id=uuid4(), intake_args_sha256="b" * 64)),
        [candidate(Band.AUTO_LINK)],
        PolicyReason.INCOMPLETE_DEMOGRAPHICS,
    ),
    (
        "r8 sha differs",
        dict(session=session(intake_record_id=uuid4(), intake_args_sha256="b" * 64)),
        [],
        PolicyReason.INTAKE_ALREADY_RECORDED,
    ),
    (
        "r8 same sha passes to r11",
        dict(session=session(intake_record_id=uuid4(), intake_args_sha256="a" * 64)),
        [],
        None,
    ),
    (
        "r8 beats linked",
        dict(session=session(intake_record_id=uuid4(), intake_args_sha256="b" * 64)),
        [candidate(Band.AUTO_LINK, human_status=DecisionStatus.LINKED)],
        PolicyReason.INTAKE_ALREADY_RECORDED,
    ),
    (
        "r9 linked beats review",
        dict(),
        [candidate(Band.REVIEW), candidate(Band.KEEP_SEPARATE, human_status=DecisionStatus.LINKED)],
        PolicyReason.ALREADY_LINKED,
    ),
    ("r10 review", dict(), [candidate(Band.REVIEW)], PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER),
    ("r10 auto_link", dict(), [candidate(Band.AUTO_LINK)], PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER),
    (
        "r10 proposed still blocks",
        dict(),
        [candidate(Band.REVIEW, human_status=DecisionStatus.PROPOSED)],
        PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER,
    ),
    (
        "r11 rejected auto_link does not block",
        dict(),
        [candidate(Band.AUTO_LINK, human_status=DecisionStatus.REJECTED)],
        None,
    ),
    (
        "r11 proposed keep_separate does not block",
        dict(),
        [candidate(Band.KEEP_SEPARATE, human_status=DecisionStatus.PROPOSED)],
        None,
    ),
    ("r11 no candidates", dict(), [], None),
    ("r11 calls 6 allowed", dict(session=session(tool_calls_this_turn=6)), [], None),
    ("r11 identical 2 allowed", dict(session=session(identical_call_count=2)), [], None),
    ("r12 attach no intake", dict(tool="attach_history"), [], PolicyReason.NO_INTAKE_RECORD),
    (
        "r13 attach ok",
        dict(tool="attach_history", session=session(intake_record_id=uuid4(), intake_args_sha256="a" * 64)),
        [],
        None,
    ),
]


@pytest.mark.parametrize("name,kwargs,cands,expected", TABLE, ids=[t[0] for t in TABLE])
def test_table(name, kwargs, cands, expected):
    d = decide(action(**kwargs), cands)
    if expected is None:
        assert d.outcome == PolicyOutcome.ALLOW, d
        assert d.reason_code is None and not d.handoff_required
    else:
        deny(expected, d)


def test_evidence_per_row():
    c_rev, c_keep = candidate(Band.REVIEW), candidate(Band.KEEP_SEPARATE)
    d = decide(action(), [c_keep, c_rev])
    assert [e.id for e in d.evidence_ids] == [c_rev.record_id]  # only the blocking ones
    d = decide(action(), [c_keep])
    assert [e.id for e in d.evidence_ids] == [c_keep.record_id]  # ALLOW: all considered
    d = decide(action(tool="search_patients"), [c_keep, c_rev])
    assert {e.id for e in d.evidence_ids} == {c_keep.record_id, c_rev.record_id}
    rid = uuid4()
    d = decide(action(tool="attach_history", session=session(intake_record_id=rid, intake_args_sha256="a" * 64)), [])
    assert d.evidence_ids[0].kind == EvidenceKind.INTAKE_RECORD and d.evidence_ids[0].id == rid
    linked = candidate(Band.REVIEW, human_status=DecisionStatus.LINKED)
    d = decide(action(), [linked])
    assert {(e.kind, e.id) for e in d.evidence_ids} == {
        (EvidenceKind.MATCH_DECISION, linked.decision_id),
        (EvidenceKind.CANDIDATE_RECORD, linked.record_id),
    }
    assert d.message_key == "gate.deny.already_linked"


def test_decide_module_is_pure():
    import inspect

    src = inspect.getsource(decide_mod)
    for forbidden in ("import os", "import time", "import random", "datetime", "sqlalchemy", "httpx", "requests"):
        assert forbidden not in src, forbidden


# --- Property: the denial rule, order independence, determinism ----------------------------------


def _random_candidates(rng: random.Random):
    out = []
    for _ in range(rng.randint(0, 8)):
        out.append(
            candidate(
                band=rng.choice(list(Band)),
                s=rng.uniform(-5, 5),
                human_status=rng.choice([None, *list(DecisionStatus)]),
            )
        )
    return out


@pytest.mark.parametrize("seed", range(300))
def test_denial_rule_property(seed):
    rng = random.Random(seed)
    cands = _random_candidates(rng)
    d = decide(action(), cands)
    any_linked = any(c.human_status == DecisionStatus.LINKED for c in cands)
    any_blocking = any(
        c.human_status in (None, DecisionStatus.PROPOSED) and c.band in (Band.REVIEW, Band.AUTO_LINK) for c in cands
    )
    if any_linked:
        assert d.reason_code == PolicyReason.ALREADY_LINKED
    elif any_blocking:
        assert d.reason_code == PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER and d.handoff_required
    else:
        assert d.outcome == PolicyOutcome.ALLOW
    shuffled = list(cands)
    rng.shuffle(shuffled)
    assert decide(action(), shuffled) == d
    assert decide(action(), cands) == d


# --- Grounding ------------------------------------------------------------------------------------


def _propose_raw(**over):
    base = {
        "givenName": "Maria Jose",
        "familyName": "Gonzalez Rivera",
        "birthDate": "1985-07-03",
        "sex": "FEMALE",
        "phone": "5550100100",
        "preferredLanguage": "ES",
        "evidence": EVIDENCE.model_dump(mode="json", by_alias=True, exclude_none=True),
    }
    base.update(over)
    return base


def grounded(raw, texts=(USER_TEXT,)):
    return parse_action("propose_new_chart", raw, user_texts=texts, session=FACTS).grounding_ok


@pytest.mark.parametrize(
    "text,quote,value",
    [
        ("Soy GONZÁLEZ", "GONZÁLEZ", "gonzalez"),
        ("born July 3, 1985", "July 3, 1985", "1985-07-03"),
        ("born 3/7/1985", "3/7/1985", "1985-07-03"),
        ("nací el 3 de julio de 1985", "3 de julio de 1985", "1985-07-03"),
        ("nacido el 03-07-1985", "03-07-1985", "1985-07-03"),
    ],
)
def test_grounding_positive(text, quote, value):
    field = "familyName" if "-" not in value else "birthDate"
    ev = EVIDENCE.model_dump(mode="json", by_alias=True, exclude_none=True)
    ev[field] = quote
    full = USER_TEXT + " " + text
    assert grounded(_propose_raw(**{field: value}, evidence=ev), (full,))


def test_grounding_negative_cases():
    ev = EVIDENCE.model_dump(mode="json", by_alias=True, exclude_none=True)
    # value with no quote
    ev2 = {k: v for k, v in ev.items() if k != "phone"}
    assert not grounded(_propose_raw(evidence=ev2))
    # quote not in text
    ev3 = {**ev, "phone": "555 999 9999"}
    assert not grounded(_propose_raw(evidence=ev3))
    # value disagrees with quote (phone digits)
    assert not grounded(_propose_raw(phone="5550100199"))
    # day/month swapped in value vs quote
    assert not grounded(_propose_raw(birthDate="1985-03-07"))
    # name token not in quote
    assert not grounded(_propose_raw(familyName="Gonzalez Perez"))
    # postal digits mismatch
    ev4 = {**ev, "postalCode": "54311"}
    assert not grounded(_propose_raw(postalCode="54312", evidence=ev4), (USER_TEXT + " código postal 54311",))
    assert grounded(_propose_raw(postalCode="54311", evidence=ev4), (USER_TEXT + " código postal 54311",))


def test_invalid_month_is_invalid_arguments_not_an_exception():
    """A birthDate that passes the regex but is not a real date must become INVALID_ARGUMENTS or at
    least a DENY, never an uncaught exception that skips the audit row (ADR-016 §4)."""
    ev = EVIDENCE.model_dump(mode="json", by_alias=True, exclude_none=True)
    ev["birthDate"] = "13 de 13 de 1985"
    act = parse_action(
        "propose_new_chart",
        _propose_raw(birthDate="1985-13-03", evidence=ev),
        user_texts=(USER_TEXT + " 13 de 13 de 1985",),
        session=FACTS,
    )
    d = decide(act, [])
    assert d.outcome == PolicyOutcome.DENY


def test_non_dict_args_become_invalid_arguments():
    act = parse_action("search_patients", ["not", "a", "dict"], user_texts=(USER_TEXT,), session=FACTS)
    assert isinstance(act.args, InvalidArgs)


def test_attach_quote_must_be_in_text():
    act = parse_action(
        "attach_history",
        attach_args().model_dump(mode="json", by_alias=True),
        user_texts=("no allergies mentioned",),
        session=FACTS,
    )
    assert not act.grounding_ok
