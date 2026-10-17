"""S2 normalize: the one place names, dates, phones and addresses are folded (architecture §3, §4).

Everything downstream (block keys, W2 features) reads the folded forms produced here, so the
rules live in one module: strip Synthea's appended name digits first, keep the accented
original next to an NFKD + casefold copy, split the DOB into parts, phone to E.164, ZIP to 5.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

# Synthea appends a run of digits to every name token ("Ahmed109", "O'Reilly797").
_TRAILING_DIGITS = re.compile(r"\d+$")
_NON_DIGITS = re.compile(r"\D")
_WHITESPACE = re.compile(r"\s+")
# Punctuation that registration desks drop or keep at random; folded away so "O'Reilly" == "OReilly".
_DROPPED_PUNCT = re.compile(r"[\'’.,]")
_HYPHENS = re.compile(r"[-‐‑‒–—/]")

# Hot-block rule (architecture §3): these values never form a block key and trip the
# PLACEHOLDER_* negative rules downstream.
PLACEHOLDER_NAMES = frozenset({
    "unknown", "unk", "test", "patient", "baby", "babyboy", "babygirl", "boy", "girl", "doe",
    "none", "null", "n a", "na", "xxx", "zzz", "temp", "noname", "no name",
})
PLACEHOLDER_DOBS = frozenset({date(1900, 1, 1), date(1901, 1, 1), date(1800, 1, 1), date(1, 1, 1), date(1111, 11, 11)})
# Fictional NANP numbers are NXX-555-01XX; Synthea's own numbers are 555-NNN-NNNN, so only the
# 555-01XX local part and one-repeated-digit numbers count as placeholders.
_FICTIONAL_LOCAL_PREFIX = "55501"

SEX_BY_RAW = {"male": "MALE", "m": "MALE", "female": "FEMALE", "f": "FEMALE"}

ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
US_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


@dataclass(frozen=True)
class Identity:
    """The demographic fields a source record carries, before any folding. Strings are raw
    (digits already stripped by the loader); None means the source has no value."""

    given: str | None = None
    middle: str | None = None
    family: str | None = None
    prefix: str | None = None
    suffix: str | None = None
    maiden: str | None = None
    birth_date: str | None = None  # ISO yyyy-mm-dd or clinic mm/dd/yyyy
    sex: str | None = None  # source spelling: male/female or M/F
    phone: str | None = None
    address_line: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    language: str | None = None  # BCP-47 code from FHIR communication; None for CSV
    mother_maiden: str | None = None


@dataclass(frozen=True)
class NormalizedFields:
    """Exactly the columns of normalized_record (migration 0001)."""

    given_name: str | None
    family_name: str | None
    given_name_folded: str | None
    family_name_folded: str | None
    birth_date: date | None
    birth_year: int | None
    birth_month: int | None
    birth_day: int | None
    sex: str | None
    phone_e164: str | None
    address_line: str | None
    zip5: str | None


def strip_synthea_digits(text: str | None) -> str | None:
    """'Ahmed109' -> 'Ahmed'; "O'Reilly797" -> "O'Reilly"; 'Isabela97 Vásquez905' -> 'Isabela Vásquez'."""
    if text is None:
        return None
    tokens = [_TRAILING_DIGITS.sub("", t) for t in text.split()]
    cleaned = " ".join(t for t in tokens if t)
    return cleaned or None


def clean_text(text: str | None) -> str | None:
    """Collapse whitespace; empty becomes None so SQL NULL means 'absent' everywhere."""
    if text is None:
        return None
    cleaned = _WHITESPACE.sub(" ", text).strip()
    return cleaned or None


def strip_accents(text: str) -> str:
    """NFKD decomposition with the combining marks removed: 'Núñez' -> 'Nunez'."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def fold(text: str | None) -> str | None:
    """Accent-fold, casefold, hyphen to space, apostrophes and periods dropped."""
    if text is None:
        return None
    stripped = _DROPPED_PUNCT.sub("", strip_accents(text))
    stripped = _HYPHENS.sub(" ", stripped)
    return clean_text(stripped.casefold())


def parse_date(text: str | None) -> date | None:
    """ISO (Synthea) or MM/DD/YYYY (clinic export). Impossible dates give None rather than raising:
    a corrupted record is still a record."""
    if not text:
        return None
    text = text.strip()
    if m := ISO_DATE.match(text):
        y, mo, d = (int(g) for g in m.groups())
    elif m := US_DATE.match(text):
        mo, d, y = (int(g) for g in m.groups())
    else:
        return None
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def phone_to_e164(phone: str | None) -> str | None:
    """US numbers only: 10 digits, or 11 starting with 1. Anything else is not a phone."""
    if not phone:
        return None
    digits = _NON_DIGITS.sub("", phone)
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits[0] == "1":
        return "+" + digits
    return None


def zip5(postal_code: str | None) -> str | None:
    if not postal_code:
        return None
    digits = _NON_DIGITS.sub("", postal_code)
    return digits[:5] if len(digits) >= 5 else None


def normalize_sex(sex: str | None) -> str | None:
    if not sex:
        return None
    return SEX_BY_RAW.get(sex.strip().lower())


def is_placeholder_name(folded: str | None) -> bool:
    return folded is None or folded in PLACEHOLDER_NAMES


def is_placeholder_dob(value: date | None) -> bool:
    return value is None or value in PLACEHOLDER_DOBS


def is_placeholder_phone(e164: str | None) -> bool:
    if e164 is None:
        return True
    local = e164[-10:]
    return len(set(local)) == 1 or local[3:].startswith(_FICTIONAL_LOCAL_PREFIX)


def normalize_identity(identity: Identity) -> NormalizedFields:
    given = clean_text(strip_synthea_digits(identity.given))
    family = clean_text(strip_synthea_digits(identity.family))
    dob = parse_date(identity.birth_date)
    return NormalizedFields(
        given_name=given,
        family_name=family,
        given_name_folded=fold(given),
        family_name_folded=fold(family),
        birth_date=dob,
        birth_year=dob.year if dob else None,
        birth_month=dob.month if dob else None,
        birth_day=dob.day if dob else None,
        sex=normalize_sex(identity.sex),
        phone_e164=phone_to_e164(identity.phone),
        address_line=clean_text(identity.address_line),
        zip5=zip5(identity.postal_code),
    )
