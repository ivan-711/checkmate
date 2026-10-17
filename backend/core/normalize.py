"""S2 normalize: one folding rule set for every lane (architecture section 3, ADR-001).

Case-fold happens here, before any feature sees a value, because the benchmark's casing is
a tell that would otherwise leak into similarity. Two forms of each name are kept: the
``accented`` form (case-folded, diacritics intact) and the ``folded`` form (NFKD with the
combining marks dropped, punctuation turned into spaces). Features compare both, so an
accent or hyphen variant stays close to the unchanged name without pretending the
accented spelling carries no information.

Per-record facts the pair stages need many times (placeholder status, phonetic codes) are
computed once here so blocking, features and the negative rules cannot drift apart.

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

from backend.core.phonetics import double_metaphone
from backend.core.placeholders import PLACEHOLDER_DOB_PARTS, is_placeholder_name

# Generation suffixes carried as a separate field so "Jr" vs "Sr" can fire a negative rule
# and a dropped suffix (taxonomy T5) does not disturb the surname comparison. Only the last
# token of the family name (or an explicit suffix field) counts: a middle initial "V" is not one.
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
# Titles are dropped from both name forms. "sr" here is the Spanish "Señor" when it is not
# the last family token; as the last token it is the generation suffix.
_TITLES: frozenset[str] = frozenset({"mr", "mrs", "ms", "miss", "dr", "sr", "sra", "srta", "don", "dona"})
# Surname particles never stand for the family on their own ("de la Cruz" is Cruz).
# "le", "van", "da", "di" are left out on purpose: they are common surnames on their own.
_PARTICLES: frozenset[str] = frozenset(
    {"de", "del", "la", "las", "los", "du", "von", "der", "den", "st", "san", "y", "e"}
)

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
}

# Years outside this window are not birth dates the corpus can contain; they are dropped.
MIN_BIRTH_YEAR = 1800
MAX_BIRTH_YEAR = 2100

_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION_TO_SPACE = re.compile(r"[\-‐-―'`’.,/_]+")
_NON_WORD = re.compile(r"[^\w\s]+")
_DIGITS = re.compile(r"\d")
# Inline ordinal suffixes ("Smith 3rd") are read before Synthea digit stripping would eat them.
_ORDINAL_SUFFIX = re.compile(r"(?i)(?<!\w)(2nd|3rd|4th)(?!\w)")
_ORDINAL_WORDS = {"2nd": "ii", "3rd": "iii", "4th": "iv"}
_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?$")
_US_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_COMPACT_DATE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_YEAR_ONLY = re.compile(r"^(\d{4})$")
_ZIP = re.compile(r"^\s*(\d{5})(?:-\d{4})?\s*$")
_PHONE_EXTENSION = re.compile(r"(?i)\s*(?:x|ext\.?|extension)\s*\d+\s*$")


@dataclass(frozen=True)
class Normalized:
    """One record after S2. Every field is ``None`` when the source had nothing usable."""

    record_id: str | None = None
    given_name: str | None = None  # case-folded, accents kept, titles and suffix removed
    family_name: str | None = None
    given_name_folded: str | None = None  # accents stripped, punctuation to spaces
    family_name_folded: str | None = None
    given_tokens: tuple[str, ...] = ()
    family_tokens: tuple[str, ...] = ()
    suffix: str | None = None  # JR, SR, II, III, IV, V
    # Derived in __post_init__ from the folded tokens, whichever constructor built the record;
    # init=False so nobody can pass a stale value and dataclasses.replace recomputes them.
    family_codes: tuple[str, ...] = field(init=False, default=())  # DM codes of the non-particle family tokens
    name_is_placeholder: bool = field(init=False, default=False)
    birth_year: int | None = None
    birth_month: int | None = None
    birth_day: int | None = None
    sex: str | None = None  # "M", "F" or None
    phone_e164: str | None = None
    phone_digits: str | None = None  # national number, placeholder checks and last-7 keys
    address_line: str | None = None
    address_tokens: tuple[str, ...] = ()
    zip5: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "family_codes", surname_codes(self.family_tokens))
        object.__setattr__(
            self, "name_is_placeholder", is_placeholder_name(self.given_name_folded, self.family_name_folded)
        )

    @property
    def birth_date(self) -> date | None:
        if self.birth_year is None or self.birth_month is None or self.birth_day is None:
            return None
        return date(self.birth_year, self.birth_month, self.birth_day)

    @property
    def has_full_dob(self) -> bool:
        return self.birth_date is not None

    def to_contract_dict(self) -> dict[str, Any]:
        """Exactly the contract ``NormalizedRecord`` fields (``extra="forbid"`` there).

        The contract has no year/month/day parts, so a year-only DOB does not survive this
        shape; store and pass ``to_row_dict()`` (the ``normalized_record`` row) when it must.
        The generation suffix has no field either, so it rides at the end of ``family_name``
        (``smith jr``) where re-normalizing splits it off again.
        """
        family = self.family_name
        if self.suffix and family:
            # A suffix with no family name has nowhere to ride and is dropped rather than
            # becoming a surname.
            family = f"{family} {self.suffix.lower()}"
        return {
            "record_id": self.record_id,
            "given_name": self.given_name,
            "family_name": family,
            "given_name_folded": self.given_name_folded,
            "family_name_folded": self.family_name_folded,
            "birth_date": self.birth_date,
            "sex": self.sex,
            "phone_e164": self.phone_e164,
            "address_line": self.address_line,
            "zip5": self.zip5,
        }

    def to_row_dict(self) -> dict[str, Any]:
        """The ``normalized_record`` table row: the contract fields plus the DOB parts."""
        return {
            **self.to_contract_dict(),
            "birth_year": self.birth_year,
            "birth_month": self.birth_month,
            "birth_day": self.birth_day,
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


def _name_tokens(text: str) -> list[tuple[str, str]]:
    """(accented token, folded token) pairs from one split, so both forms always align."""
    accented = casefold_text(text) or ""
    pairs = []
    for word in _PUNCTUATION_TO_SPACE.sub(" ", accented).split():
        folded = fold_text(word)
        if folded:
            pairs.append((word.strip(",. "), folded.replace(" ", "")))
    return [(a, f) for a, f in pairs if a and f]


def _strip_titles_and_suffix(
    pairs: list[tuple[str, str]], suffix_allowed: bool
) -> tuple[list[tuple[str, str]], str | None]:
    """Strip trailing titles and the generation suffix until stable, then titles anywhere.

    Working from the tail makes the stored row (``family_name = "smith jr"``) normalize back to
    the same tokens and suffix, which ``coerce_normalized`` relies on.
    """
    suffix = None
    pairs = list(pairs)
    while len(pairs) > 1:
        tail = pairs[-1][1]
        if suffix_allowed and suffix is None and tail in GENERATION_SUFFIXES:
            suffix = GENERATION_SUFFIXES[tail]
            pairs.pop()
        elif tail in _TITLES:
            pairs.pop()
        else:
            break
    if len(pairs) > 1:
        pairs = [pf for pf in pairs if pf[1] not in _TITLES]
    return pairs, suffix


def surname_codes(tokens: tuple[str, ...]) -> tuple[str, ...]:
    """Double Metaphone codes of the family tokens that can stand for the family.

    Particles ("de", "la", "van") share codes across unrelated families, so they are left out
    unless the name is nothing but particles.
    """
    meaningful = [tok for tok in tokens if tok not in _PARTICLES] or list(tokens)
    return tuple(sorted({code for tok in meaningful for code in double_metaphone(tok) if code}))


# --- field parsers ----------------------------------------------------------------------


def parse_dob_parts(value: Any) -> tuple[int | None, int | None, int | None]:
    """Year, month, day with ``None`` for any part the source lacks or that is impossible.

    Accepts ``date``/``datetime``, ISO ``YYYY-MM-DD`` (a time suffix is ignored), US
    ``MM/DD/YYYY``, ``YYYYMMDD`` and a bare ``YYYY`` (taxonomy D4, year only). Impossible
    parts become ``None`` rather than raising, because one bad field must not drop the record.
    """
    if value is None:
        return None, None, None
    if isinstance(value, date):
        return parse_dob_parts_from_components(value.year, value.month, value.day)
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
    return parse_dob_parts_from_components(year, month, day)


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
    the country code are the only shapes we trust. A trailing extension (``x123``, ``ext 4``)
    is removed first; letters are dropped.
    """
    if value is None:
        return None, None
    text = _PHONE_EXTENSION.sub("", str(value))
    digits = "".join(ch for ch in text if ch.isdigit())
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


def normalize_name_part(
    value: Any, *, suffix_allowed: bool
) -> tuple[str | None, str | None, tuple[str, ...], str | None]:
    """(accented, folded, tokens, suffix) for one name field.

    Both forms are built from the same token split, so ``fold_text(accented) == folded`` always
    holds and the features never compare text the folded form dropped.
    """
    if value is None:
        return None, None, (), None
    text = _ORDINAL_SUFFIX.sub(lambda m: _ORDINAL_WORDS[m.group(1).lower()], str(value))
    text = strip_synthea_digits(text)
    if not text:
        return None, None, (), None
    pairs, suffix = _strip_titles_and_suffix(_name_tokens(text), suffix_allowed)
    if not pairs:
        return None, None, (), suffix
    accented = " ".join(a for a, _ in pairs)
    tokens = tuple(f for _, f in pairs)
    return accented, " ".join(tokens), tokens, suffix


# --- record ------------------------------------------------------------------------------

_ALIASES: dict[str, tuple[str, ...]] = {
    "record_id": ("record_id", "id"),
    "given_name": ("given_name", "given", "first_name", "first"),
    "family_name": ("family_name", "family", "last_name", "last", "surname"),
    "suffix": ("suffix", "name_suffix"),
    "birth_date": ("birth_date", "birthdate", "dob", "date_of_birth"),
    "birth_year": ("birth_year",),
    "birth_month": ("birth_month",),
    "birth_day": ("birth_day",),
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
    """Fielded source values (any of the aliases above) to one ``Normalized`` record.

    Explicit ``birth_year`` / ``birth_month`` / ``birth_day`` parts (the table row) are used
    when ``birth_date`` is absent, so a year-only DOB survives a trip through the database.
    """
    given, given_folded, given_tokens, _ = normalize_name_part(_get(raw, "given_name"), suffix_allowed=False)
    family, family_folded, family_tokens, family_suffix = normalize_name_part(
        _get(raw, "family_name"), suffix_allowed=True
    )
    explicit_suffix = fold_text(_get(raw, "suffix"))
    suffix = GENERATION_SUFFIXES.get(explicit_suffix or "", None) or family_suffix
    year, month, day = parse_dob_parts(_get(raw, "birth_date"))
    if year is None and month is None and day is None:
        year, month, day = parse_dob_parts_from_components(
            _int_or_none(_get(raw, "birth_year")),
            _int_or_none(_get(raw, "birth_month")),
            _int_or_none(_get(raw, "birth_day")),
        )
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


def parse_dob_parts_from_components(
    year: int | None, month: int | None, day: int | None
) -> tuple[int | None, int | None, int | None]:
    """Validate split parts: a known placeholder date is kept whole so the rules can see it;
    an out-of-window year drops the whole date (orphan month/day parts mean nothing)."""
    if (year, month, day) in PLACEHOLDER_DOB_PARTS:
        return year, month, day
    if year is not None and not MIN_BIRTH_YEAR <= year <= MAX_BIRTH_YEAR:
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


def coerce_normalized(value: Any) -> Normalized:
    """Accept a ``Normalized``, a contract ``NormalizedRecord``, a table row or a plain mapping.

    Re-normalizing canonical values is idempotent, so one entry point serves the gate and the
    executors. Prefer the row shape (with DOB parts) over the contract shape for year-only DOBs.
    """
    if isinstance(value, Normalized):
        return value
    if hasattr(value, "model_dump"):
        return normalize_record(value.model_dump())
    return normalize_record(value)
