"""Block keys (architecture §3, ADR-001): Double Metaphone(surname) + birth year, exact DOB (which
also stores the day/month-swapped date under the same type), phone last 7, ZIP5 + first initial.

Placeholder names, dates and phones never form a key (hot-block rule). W2 reads KEY_TYPES and
the key_value formats from here; the pair expansion and the 100-record cap are W2's.
"""
from __future__ import annotations

from datetime import date

from backend.ingest.normalize import (
    NormalizedFields,
    is_placeholder_dob,
    is_placeholder_name,
    is_placeholder_phone,
    is_placeholder_zip,
)
from backend.ingest.phonetics import primary_code

KEY_METAPHONE_SURNAME_BIRTH_YEAR = "metaphone_surname_birth_year"
KEY_DOB_EXACT = "dob_exact"
KEY_PHONE_LAST7 = "phone_last7"
KEY_ZIP5_INITIAL = "zip5_initial"
KEY_TYPES = (KEY_METAPHONE_SURNAME_BIRTH_YEAR, KEY_DOB_EXACT, KEY_PHONE_LAST7, KEY_ZIP5_INITIAL)

# Leading surname particles carry no phonetic signal of their own ("de la Cruz" keys on "cruz").
SURNAME_PARTICLES = frozenset({"de", "del", "la", "las", "los", "y", "e", "van", "von", "der", "den", "di", "da", "du", "le", "st"})
PHONE_SUFFIX_LEN = 7


def surname_key_token(family_folded: str | None) -> str | None:
    """First non-particle token of the folded surname, so a dropped maternal surname (S3) or a
    hyphen change (S5) still lands in the same block."""
    if not family_folded:
        return None
    for token in family_folded.split():
        if token not in SURNAME_PARTICLES:
            return token
    return None


def swapped_day_month(value: date) -> date | None:
    """The MM/DD vs DD/MM confusion, defined only when the day could be a month and differs from it."""
    if value.day > 12 or value.day == value.month:
        return None
    return value.replace(month=value.day, day=value.month)


def block_keys(fields: NormalizedFields) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    name_ok = not is_placeholder_name(fields.family_name_folded)
    dob_ok = not is_placeholder_dob(fields.birth_date)

    if name_ok and dob_ok:
        token = surname_key_token(fields.family_name_folded)
        code = primary_code(token)
        if code:
            keys.append((KEY_METAPHONE_SURNAME_BIRTH_YEAR, f"{code}:{fields.birth_year}"))

    if dob_ok:
        keys.append((KEY_DOB_EXACT, fields.birth_date.isoformat()))
        swapped = swapped_day_month(fields.birth_date)
        if swapped is not None:
            keys.append((KEY_DOB_EXACT, swapped.isoformat()))

    if not is_placeholder_phone(fields.phone_e164):
        keys.append((KEY_PHONE_LAST7, fields.phone_e164[-PHONE_SUFFIX_LEN:]))

    if not is_placeholder_zip(fields.zip5) and not is_placeholder_name(fields.given_name_folded):
        keys.append((KEY_ZIP5_INITIAL, f"{fields.zip5}:{fields.given_name_folded[0]}"))

    return keys
