"""S2 normalize: one folding rule set for every lane (architecture section 3, ADR-001).

Case-fold happens here, before any feature sees a value, because the benchmark's casing is
a tell that would otherwise leak into similarity. Two forms of each name are kept: the
``accented`` form (case-folded, diacritics intact) and the ``folded`` form (NFKD with the
combining marks dropped, punctuation turned into spaces). Features compare both, so an
accent or hyphen variant stays close to the unchanged name without pretending the
accented spelling carries no information.

W1 (ingest) should import ``normalize_record`` / ``fold_text`` from here rather than keep a
second copy of the rules; a drift between the two would silently change every score.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

# Generation suffixes carried as a separate field so "Jr" vs "Sr" can fire a negative rule
# and a dropped suffix (taxonomy T5) does not disturb the surname comparison.
GENERATION_SUFFIXES: dict[str, str] = {
    "jr": "JR",
    "jnr": "JR",
    "junior": "JR",
    "sr": "SR",
    "snr": "SR",
    "senior": "SR",
    "ii": "II",
    "iii": "III",
    "iv": "IV",
    "v": "V",
    "2nd": "II",
    "3rd": "III",
    "4th": "IV",
}
_TITLES: frozenset[str] = frozenset({"mr", "mrs", "ms", "miss", "dr", "sra", "sr.", "srta", "don", "dona"})

# Street-type abbreviations expanded so "Main St" and "Main Street" share tokens (taxonomy L2).
_ADDRESS_ABBREVIATIONS: dict[str, str] = {
    "st": "street",
    "str": "street",
    "ave": "avenue",
    "av": "avenue",
    "rd": "road",
    "dr": "drive",
    "ln": "lane",
    "blvd": "boulevard",
    "ct": "court",
    "cir": "circle",
    "pl": "place",
    "ter": "terrace",
    "hwy": "highway",
    "pkwy": "parkway",
    "apt": "apartment",
    "unit": "apartment",
    "ste": "suite",
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
    "ne": "northeast",
    "nw": "northwest",
    "se": "southeast",
    "sw": "southwest",
    "fl": "floor",
    "bldg": "building",
    "po": "po",
    "box": "box",
}

_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION_TO_SPACE = re.compile(r"[\-‐-―'`’.,/_]+")
_NON_WORD = re.compile(r"[^\w\s]+")
_DIGITS = re.compile(r"\d")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")
_US_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_COMPACT_DATE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_YEAR_ONLY = re.compile(r"^(\d{4})$")
_ZIP = re.compile(r"^\s*(\d{5})(?:-\d{4})?\s*$")


@dataclass(frozen=True)
class Normalized:
    """One record after S2. Every field is ``None`` when the source had nothing usable."""

    record_id: str | None = None
    given_name: str | None = None  # case-folded, accents kept
    family_name: str | None = None
    given_name_folded: str | None = None  # accents stripped, punctuation to spaces
    family_name_folded: str | None = None
    given_tokens: tuple[str, ...] = ()
    family_tokens: tuple[str, ...] = ()
    suffix: str | None = None  # JR, SR, II, III, IV, V
    birth_year: int | None = None
    birth_month: int | None = None
    birth_day: int | None = None
    sex: str | None = None  # "M", "F" or None
    phone_e164: str | None = None
    phone_digits: str | None = None  # national number, placeholder checks and last-7 keys
    address_line: str | None = None
    address_tokens: tuple[str, ...] = ()
    zip5: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict, compare=False)

    @property
    def birth_date(self) -> date | None:
        if self.birth_year is None or self.birth_month is None or self.birth_day is None:
            return None
        return date(self.birth_year, self.birth_month, self.birth_day)

    @property
    def has_full_dob(self) -> bool:
        return self.birth_date is not None

    def to_contract_dict(self) -> dict[str, Any]:
        """The ``normalized_record`` row / contract ``NormalizedRecord`` fields."""
        return {
            "record_id": self.record_id,
            "given_name": self.given_name,
            "family_name": self.family_name,
            "given_name_folded": self.given_name_folded,
            "family_name_folded": self.family_name_folded,
            "birth_date": self.birth_date,
            "birth_year": self.birth_year,
            "birth_month": self.birth_month,
            "birth_day": self.birth_day,
            "sex": self.sex,
            "phone_e164": self.phone_e164,
            "address_line": self.address_line,
            "zip5": self.zip5,
        }


# --- text folding -----------------------------------------------------------------------


def casefold_text(text: str | None) -> str | None:
    """NFKC + casefold + whitespace collapse; diacritics and punctuation kept."""
    if text is None:
        return None
    out = _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", str(text)).casefold()).strip()
    return out or None


def fold_text(text: str | None) -> str | None:
    """Diacritics dropped (NFKD), casefolded, punctuation to spaces: the comparison form."""
    if text is None:
        return None
    decomposed = unicodedata.normalize("NFKD", str(text))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    spaced = _PUNCTUATION_TO_SPACE.sub(" ", stripped.casefold())
    cleaned = _NON_WORD.sub("", spaced)
    out = _WHITESPACE.sub(" ", cleaned).strip()
    return out or None


def strip_synthea_digits(text: str | None) -> str | None:
    """Synthea appends digits to names (``Ahmed109``); S1 strips them before anything else."""
    if text is None:
        return None
    return _DIGITS.sub("", str(text)) or None


def _split_suffix(tokens: list[str]) -> tuple[list[str], str | None]:
    suffix = None
    kept: list[str] = []
    for tok in tokens:
        if tok in GENERATION_SUFFIXES and len(tokens) > 1:
            suffix = GENERATION_SUFFIXES[tok]
        elif tok in _TITLES and len(tokens) > 1:
            continue
        else:
            kept.append(tok)
    return kept, suffix


# --- field parsers ----------------------------------------------------------------------


def parse_dob_parts(value: Any) -> tuple[int | None, int | None, int | None]:
    """Year, month, day with ``None`` for any part the source lacks or that is impossible.

    Accepts ``date``/``datetime``, ISO ``YYYY-MM-DD``, US ``MM/DD/YYYY``, ``YYYYMMDD`` and a
    bare ``YYYY`` (taxonomy D4, year only). Impossible days become ``None`` rather than raising,
    because one bad field must not drop the record.
    """
    if value is None:
        return None, None, None
    if isinstance(value, date):
        return value.year, value.month, value.day
    text = str(value).strip()
    if not text:
        return None, None, None
    year = month = day = None
    if m := _ISO_DATE.match(text):
        year, month, day = (int(g) for g in m.groups())
    elif m := _US_DATE.match(text):
        month, day, year = (int(g) for g in m.groups())
    elif m := _COMPACT_DATE.match(text):
        year, month, day = (int(g) for g in m.groups())
    elif m := _YEAR_ONLY.match(text):
        year = int(m.group(1))
    else:
        return None, None, None
    if month is not None and not 1 <= month <= 12:
        month = None
    if day is not None and not 1 <= day <= 31:
        day = None
    if year is not None and month is not None and day is not None:
        try:
            date(year, month, day)
        except ValueError:
            day = None
    return year, month, day


def normalize_sex(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().casefold()
    if text in {"m", "male", "man", "masculino", "hombre"}:
        return "M"
    if text in {"f", "female", "woman", "femenino", "mujer"}:
        return "F"
    return None


def normalize_phone(value: Any) -> tuple[str | None, str | None]:
    """(E.164, national digits) for a US number; anything else is treated as missing.

    The synthetic corpus is US-only, so a 10-digit number or an 11-digit number starting with
    the country code are the only shapes we trust. Extensions and letters are dropped.
    """
    if value is None:
        return None, None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None, None
    return "+1" + digits, digits


def normalize_zip5(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if m := _ZIP.match(text):
        return m.group(1)
    if text.isdigit() and len(text) == 4:
        # A leading zero lost by a spreadsheet (02139 -> 2139) is the common CSV damage.
        return "0" + text
    return None


def normalize_address(value: Any) -> tuple[str | None, tuple[str, ...]]:
    folded = fold_text(None if value is None else str(value).replace("#", " apartment "))
    if not folded:
        return None, ()
    tokens = tuple(_ADDRESS_ABBREVIATIONS.get(tok, tok) for tok in folded.split())
    return " ".join(tokens), tokens


def normalize_name_part(value: Any) -> tuple[str | None, str | None, tuple[str, ...], str | None]:
    """(accented, folded, tokens, suffix) for one name field."""
    text = strip_synthea_digits(None if value is None else str(value))
    accented = casefold_text(text)
    folded = fold_text(text)
    if not folded:
        return accented, None, (), None
    tokens, suffix = _split_suffix(folded.split())
    folded_clean = " ".join(tokens) or None
    return accented, folded_clean, tuple(tokens), suffix


# --- record ------------------------------------------------------------------------------

_ALIASES: dict[str, tuple[str, ...]] = {
    "record_id": ("record_id", "id"),
    "given_name": ("given_name", "given", "first_name", "first"),
    "family_name": ("family_name", "family", "last_name", "last", "surname"),
    "suffix": ("suffix", "name_suffix"),
    "birth_date": ("birth_date", "birthdate", "dob", "date_of_birth"),
    "sex": ("sex", "gender"),
    "phone": ("phone", "phone_e164", "telephone", "phone_number"),
    "address_line": ("address_line", "address", "street", "address1"),
    "zip": ("zip5", "zip", "zipcode", "postal_code", "postalcode"),
}


def _get(raw: Mapping[str, Any], key: str) -> Any:
    for alias in _ALIASES[key]:
        if alias in raw and raw[alias] not in ("", None):
            return raw[alias]
    return None


def normalize_record(raw: Mapping[str, Any]) -> Normalized:
    """Fielded source values (any of the aliases above) to one ``Normalized`` record."""
    given, given_folded, given_tokens, given_suffix = normalize_name_part(_get(raw, "given_name"))
    family, family_folded, family_tokens, family_suffix = normalize_name_part(_get(raw, "family_name"))
    explicit_suffix = fold_text(_get(raw, "suffix"))
    suffix = GENERATION_SUFFIXES.get(explicit_suffix or "", None) or family_suffix or given_suffix
    year, month, day = parse_dob_parts(_get(raw, "birth_date"))
    phone_e164, phone_digits = normalize_phone(_get(raw, "phone"))
    address_line, address_tokens = normalize_address(_get(raw, "address_line"))
    record_id = _get(raw, "record_id")
    return Normalized(
        record_id=None if record_id is None else str(record_id),
        given_name=given,
        family_name=family,
        given_name_folded=given_folded,
        family_name_folded=family_folded,
        given_tokens=given_tokens,
        family_tokens=family_tokens,
        suffix=suffix,
        birth_year=year,
        birth_month=month,
        birth_day=day,
        sex=normalize_sex(_get(raw, "sex")),
        phone_e164=phone_e164,
        phone_digits=phone_digits,
        address_line=address_line,
        address_tokens=address_tokens,
        zip5=normalize_zip5(_get(raw, "zip")),
    )


def coerce_normalized(value: Any) -> Normalized:
    """Accept a ``Normalized``, a contract ``NormalizedRecord`` or a plain mapping.

    The API stores the contract shape; re-normalizing it is idempotent because every field
    is already in its canonical form, so one entry point serves the gate and the executors.
    """
    if isinstance(value, Normalized):
        return value
    if hasattr(value, "model_dump"):
        return normalize_record(value.model_dump())
    return normalize_record(value)
