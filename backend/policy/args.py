"""Validate the model's tool arguments and check that every filled field is grounded in the
patient's own words (ADR-016 §4). Deterministic; no I/O.

A field is grounded when its evidence quote occurs, after case and accent folding, in this
session's user text, and the value agrees with the quote: names by folded tokens, the birth
date by year, day and month (number or EN/ES name), phone and postal code by digits only.
A value with no quote is ungrounded: the model may not invent what the patient never typed.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Sequence
from datetime import date

from pydantic import ValidationError

from contracts.models.policy import (
    AgentAction,
    AttachArgs,
    Evidence,
    InvalidArgs,
    ProposeArgs,
    SearchArgs,
    SessionFacts,
    ToolName,
)

_WHITESPACE = re.compile(r"\s+")
_NON_DIGIT = re.compile(r"\D")
_TOKEN = re.compile(r"[^\W_]+")

# 24-entry EN/ES month table (folded forms; accents already stripped by ``fold``).
MONTH_NAMES: dict[int, tuple[str, ...]] = {
    1: ("january", "enero"),
    2: ("february", "febrero"),
    3: ("march", "marzo"),
    4: ("april", "abril"),
    5: ("may", "mayo"),
    6: ("june", "junio"),
    7: ("july", "julio"),
    8: ("august", "agosto"),
    9: ("september", "septiembre"),
    10: ("october", "octubre"),
    11: ("november", "noviembre"),
    12: ("december", "diciembre"),
}
assert sum(len(v) for v in MONTH_NAMES.values()) == 24

_ARGS_MODELS: dict[str, type[SearchArgs | ProposeArgs | AttachArgs]] = {
    ToolName.SEARCH_PATIENTS.value: SearchArgs,
    ToolName.PROPOSE_NEW_CHART.value: ProposeArgs,
    ToolName.ATTACH_HISTORY.value: AttachArgs,
}


def fold(text: str) -> str:
    """NFKD, strip combining marks, casefold, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WHITESPACE.sub(" ", stripped.casefold()).strip()


def canonical_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    ).hexdigest()


def _digits(text: str) -> str:
    return _NON_DIGIT.sub("", text)


def _name_grounded(value: str, quote: str) -> bool:
    quote_tokens = set(_TOKEN.findall(fold(quote)))
    value_tokens = _TOKEN.findall(fold(value))
    return bool(value_tokens) and all(tok in quote_tokens for tok in value_tokens)


def _birth_date_grounded(value: str, quote: str) -> bool:
    year, month, day = value.split("-")
    folded = fold(quote)
    tokens = set(_TOKEN.findall(folded))
    if year not in tokens:
        return False
    day_forms = {day, str(int(day))}
    if not (tokens & day_forms):
        return False
    month_forms = {month, str(int(month)), *MONTH_NAMES[int(month)]}
    return bool(tokens & month_forms)


def _digits_grounded(value: str, quote: str) -> bool:
    return _digits(value) != "" and _digits(value) == _digits(quote)


def _text_grounded(value: str, quote: str) -> bool:
    return fold(value) != "" and fold(value) in fold(quote)


# field -> how the value is compared with its quote
_FIELD_CHECKS = {
    "given_name": _name_grounded,
    "family_name": _name_grounded,
    "birth_date": _birth_date_grounded,
    "sex": lambda value, quote: True,  # the quote alone grounds it; stated sex has no canonical word form
    "phone": _digits_grounded,
    "address_line": _text_grounded,
    "postal_code": _digits_grounded,
}


def _quote_in_text(quote: str, folded_texts: Sequence[str]) -> bool:
    folded_quote = fold(quote)
    return folded_quote != "" and any(folded_quote in t for t in folded_texts)


def demographics_grounded(args: SearchArgs | ProposeArgs, user_texts: Sequence[str]) -> bool:
    folded_texts = [fold(t) for t in user_texts]
    evidence: Evidence = args.evidence
    for field_name, check in _FIELD_CHECKS.items():
        value = getattr(args, field_name)
        if value is None:
            continue
        quote = getattr(evidence, field_name)
        if not quote or not _quote_in_text(quote, folded_texts):
            return False
        if not check(str(value.value if hasattr(value, "value") else value), quote):
            return False
    return True


def history_grounded(args: AttachArgs, user_texts: Sequence[str]) -> bool:
    folded_texts = [fold(t) for t in user_texts]
    return all(_quote_in_text(item.evidence_quote, folded_texts) for item in args.items)


def _invalid(tool_name: str, raw_args: object, errors: list[str], session: SessionFacts) -> AgentAction:
    raw = raw_args if isinstance(raw_args, dict) else {"_raw": repr(raw_args)}
    return AgentAction(
        tool=tool_name,
        args=InvalidArgs(raw=raw, errors=errors),
        args_sha256=canonical_sha256(raw),
        grounding_ok=False,
        session=session,
    )


def _check_calendar_date(args: SearchArgs | ProposeArgs) -> None:
    """The frozen pattern only shapes the string; month 13 or 31 February must still be INVALID_ARGUMENTS."""
    if args.birth_date is not None:
        try:
            date.fromisoformat(args.birth_date)
        except ValueError:
            raise ValueError("birthDate: not a calendar date") from None


def parse_action(tool_name: str, raw_args: object, *, user_texts: Sequence[str], session: SessionFacts) -> AgentAction:
    """Validate camelCase arguments into the tool's model (else ``InvalidArgs``) and ground them.

    Never raises: the model writes these values, and ADR-016 §4 says a schema failure is DENY
    INVALID_ARGUMENTS, never an exception that skips the audit row.
    """
    try:
        return _parse_action(tool_name, raw_args, user_texts=user_texts, session=session)
    except Exception as exc:  # anything unexpected in the model's input is an invalid argument
        return _invalid(tool_name, raw_args, [f"{type(exc).__name__}: {exc}"], session)


def _parse_action(tool_name: str, raw_args: object, *, user_texts: Sequence[str], session: SessionFacts) -> AgentAction:
    if not isinstance(raw_args, dict):
        return _invalid(tool_name, raw_args, ["arguments must be an object"], session)
    model = _ARGS_MODELS.get(tool_name)
    if model is None:
        return _invalid(tool_name, raw_args, ["unknown tool"], session)
    try:
        args = model.model_validate(raw_args)
        if isinstance(args, (SearchArgs, ProposeArgs)):
            _check_calendar_date(args)
    except ValidationError as exc:
        errors = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        return _invalid(tool_name, raw_args, errors, session)
    except ValueError as exc:
        return _invalid(tool_name, raw_args, [str(exc)], session)
    if isinstance(args, AttachArgs):
        grounded = history_grounded(args, user_texts)
    else:
        grounded = demographics_grounded(args, user_texts)
    return AgentAction(
        tool=tool_name,
        args=args,
        args_sha256=canonical_sha256(args.model_dump(mode="json", by_alias=True, exclude_none=True)),
        grounding_ok=grounded,
        session=session,
    )
