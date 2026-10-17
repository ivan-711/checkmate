"""Placeholder detection shared by blocking (never block on one) and the negative rules.

Registration desks fill unknown values with conventions (1900-01-01, "UNKNOWN", 555-0100).
Two records that share a placeholder share nothing, so a placeholder must neither form a
block key nor earn match evidence; it only ever demotes AUTO_LINK to REVIEW (section 6).
"""

from __future__ import annotations

import re

# Dates desks use for "unknown"; epoch and century starts dominate real data exports.
PLACEHOLDER_DOB_PARTS: frozenset[tuple[int, int, int]] = frozenset(
    {
        (1900, 1, 1),
        (1901, 1, 1),
        (1800, 1, 1),
        (1, 1, 1),
        (1111, 11, 11),
        (1970, 1, 1),  # Unix epoch, the default of many integrations
        (9999, 9, 9),
        (9999, 12, 31),
    }
)

# Folded (accent-stripped, case-folded) tokens that mean "no real name was captured".
PLACEHOLDER_NAME_TOKENS: frozenset[str] = frozenset(
    {
        "unknown",
        "unk",
        "unkn",
        "test",
        "testpatient",
        "patient",
        "doe",
        "baby",
        "babyboy",
        "babygirl",
        "infant",
        "newborn",
        "twin",
        "noname",
        "none",
        "null",
        "na",
        "nil",
        "anonymous",
        "anon",
        "temp",
        "temporary",
        "trauma",
        "emergency",
        "zzz",
        "xxx",
        "dummy",
        "sample",
    }
)
_PLACEHOLDER_FULL_NAMES: frozenset[str] = frozenset(
    {"john doe", "jane doe", "baby doe", "baby boy", "baby girl", "test patient", "no name", "not available"}
)

# One repeated digit (5555555555) or the fictional 555-01xx exchange are never a real line.
_REPEATED_DIGIT = re.compile(r"^(\d)\1+$")
_FICTIONAL_555 = re.compile(r"55501\d{2}$")
_SEQUENTIAL_PHONES: frozenset[str] = frozenset({"1234567890", "0123456789", "9876543210"})
PLACEHOLDER_ZIPS: frozenset[str] = frozenset({"00000", "99999", "11111", "12345"})


def is_placeholder_dob(year: int | None, month: int | None, day: int | None) -> bool:
    if year is None or month is None or day is None:
        return False
    return (year, month, day) in PLACEHOLDER_DOB_PARTS


def _is_repeated_char(token: str) -> bool:
    return len(token) >= 2 and len(set(token)) == 1


def is_placeholder_name(given_folded: str | None, family_folded: str | None) -> bool:
    """True when either name part is a known filler or a repeated character (``xxxx``)."""
    full = " ".join(part for part in (given_folded, family_folded) if part).strip()
    if full in _PLACEHOLDER_FULL_NAMES:
        return True
    for part in (given_folded, family_folded):
        if not part:
            continue
        compact = part.replace(" ", "")
        if compact in PLACEHOLDER_NAME_TOKENS or _is_repeated_char(compact):
            return True
        if all(tok in PLACEHOLDER_NAME_TOKENS for tok in part.split()):
            return True
    return False


def is_placeholder_phone(digits: str | None) -> bool:
    """``digits`` is the national number without country code (10 digits in the US)."""
    if not digits:
        return False
    return bool(_REPEATED_DIGIT.match(digits)) or bool(_FICTIONAL_555.search(digits)) or digits in _SEQUENTIAL_PHONES


def is_placeholder_zip(zip5: str | None) -> bool:
    return not zip5 or zip5 in PLACEHOLDER_ZIPS
