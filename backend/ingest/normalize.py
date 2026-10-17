"""The S1 -> S2 hand-off for ingest: the fielded identity a loader reads, normalized by backend.core.

Ingest keeps no folding, phone, ZIP or placeholder rules of its own (issue #10). The app, the
harness and ingest share ``backend.core.normalize``, so a stored ``normalized_record`` row and its
block keys are exactly what the FrontDesk gate and match runs recompute from that row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from backend.core.normalize import Normalized, normalize_record, parse_dob_parts


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


def normalize_identity(identity: Identity) -> Normalized:
    return normalize_record(identity_fields(identity))


def parse_date(text: str | None) -> date | None:
    """A full calendar date from core's DOB parser, or None when a part is missing or impossible.

    The renderers and the generator need a ``date`` to re-emit ISO (FHIR) or MM/DD/YYYY (clinic)
    and to shift or swap parts; parsing stays in one place.
    """
    year, month, day = parse_dob_parts(text)
    if year is None or month is None or day is None:
        return None
    return date(year, month, day)
