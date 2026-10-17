"""The S1 -> S2 hand-off for ingest: the fielded identity a loader reads, normalized by backend.core.

Ingest keeps no folding, phone, ZIP or placeholder rules of its own (issue #10). The app, the
harness and ingest share ``backend.core.normalize``: ``normalized_row`` is the one row both the CLI
store and the corpus-mode scenario loader write, and its block keys are computed from that row
exactly as the FrontDesk gate and match runs recompute them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from backend.core.normalize import Normalized, coerce_normalized, normalize_record, parse_dob_parts


@dataclass(frozen=True)
class Identity:
    """The demographic fields a source record carries, before any folding. Strings are raw
    (Synthea digits already stripped by the loader); None means the source has no value."""

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


def identity_fields(identity: Identity) -> dict[str, str | None]:
    """The identity under the field names ``backend.core.normalize.normalize_record`` reads.

    Middle name, prefix, maiden name and language have no normalized column; the suffix goes in
    so a generation suffix ("Jr.") reaches the GENERATION_SUFFIX_MISMATCH rule.
    """
    return {
        "given_name": identity.given,
        "family_name": identity.family,
        "suffix": identity.suffix,
        "birth_date": identity.birth_date,
        "sex": identity.sex,
        "phone": identity.phone,
        "address_line": identity.address_line,
        "zip": identity.postal_code,
    }


# Display spelling of core's sex codes. The source card, the golden record's MAJORITY rule and the
# frozen fixtures all use MALE/FEMALE; core reads either form back to M/F.
DISPLAY_SEX = {"M": "MALE", "F": "FEMALE"}


def _as_registered(text: str | None) -> str | None:
    """The value as the registration typed it (Synthea digits already stripped), whitespace collapsed."""
    if text is None:
        return None
    return " ".join(text.split()) or None


def normalized_row(identity: Identity) -> dict[str, Any]:
    """The ``normalized_record`` row (without ``record_id``) for one source record.

    Display columns keep the registration's spelling (given_name, family_name, address_line; sex as
    MALE/FEMALE), as before issue #10, because the source card and the golden record render them;
    switching them to core's case-folded form would change what a judge sees (fork issue #13).
    Every other column is backend.core's normalization of those same values, so core reads this row
    back to exactly the record ``normalize_identity`` returns, and keys computed from it match the gate.
    """
    given = _as_registered(identity.given)
    family = _as_registered(identity.family)
    if family and identity.suffix and normalize_record(identity_fields(identity)).suffix:
        # A generation suffix ("Jr.") rides on the surname, where core splits it off again, so the
        # GENERATION_SUFFIX_MISMATCH rule still sees it; a professional suffix ("MD") is not carried.
        family = f"{family} {_as_registered(identity.suffix)}"
    address = _as_registered(identity.address_line)
    core = normalize_record(
        {
            "given_name": given,
            "family_name": family,
            "birth_date": identity.birth_date,
            "sex": identity.sex,
            "phone": identity.phone,
            "address_line": address,
            "zip": identity.postal_code,
        }
    )
    return {
        "given_name": given,
        "family_name": family,
        "given_name_folded": core.given_name_folded,
        "family_name_folded": core.family_name_folded,
        "birth_date": core.birth_date,
        "birth_year": core.birth_year,
        "birth_month": core.birth_month,
        "birth_day": core.birth_day,
        "sex": DISPLAY_SEX.get(core.sex or ""),
        "phone_e164": core.phone_e164,
        "address_line": address,
        "zip5": core.zip5,
    }


def normalize_identity(identity: Identity) -> Normalized:
    """The record as backend.core reads the stored row: what blocking, features and the gate see."""
    return coerce_normalized(normalized_row(identity))


def parse_date(text: str | None) -> date | None:
    """A full calendar date from core's DOB parser, or None when a part is missing or impossible.

    The renderers and the generator need a ``date`` to re-emit ISO (FHIR) or MM/DD/YYYY (clinic)
    and to shift or swap parts; parsing stays in one place.
    """
    year, month, day = parse_dob_parts(text)
    if year is None or month is None or day is None:
        return None
    return date(year, month, day)
