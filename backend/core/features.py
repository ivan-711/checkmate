"""S4 features: every value in [0, 1] or ``None`` when missing, plus missing indicators.

A feature is ``None`` (not 0) when either side lacks the field so the scorer can separate
"different" from "unknown"; the ``missing`` flags, one per field group, become their own
weighted indicators in S5. Both the accented and the folded name forms are compared so an
accent or hyphen variant stays close to the unchanged spelling (what-if ACCENT_HYPHEN_SURNAME).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import jellyfish

from backend.core.nicknames import same_nickname_family
from backend.core.normalize import Normalized
from backend.core.phonetics import phonetic_codes_match
from backend.core.placeholders import is_placeholder_dob, is_placeholder_phone, is_placeholder_zip

FEATURE_NAMES: Final[tuple[str, ...]] = (
    "given_jw",
    "given_jw_folded",
    "given_dl",
    "given_dmeta",
    "given_nickname",
    "given_initial",
    "given_token_overlap",
    "family_jw",
    "family_jw_folded",
    "family_dl",
    "family_dmeta",
    "family_token_overlap",
    "dob_exact",
    "dob_day_month_swap",
    "dob_one_digit_edit",
    "dob_one_component_off",
    "dob_year_match",
    "sex_match",
    "phone_match",
    "address_jaccard",
    "zip_match",
)
MISSING_GROUPS: Final[tuple[str, ...]] = ("given_name", "family_name", "dob", "sex", "phone", "address", "zip")
MISSING_PREFIX: Final[str] = "missing_"
MISSING_NAMES: Final[tuple[str, ...]] = tuple(MISSING_PREFIX + g for g in MISSING_GROUPS)

# A phone with one wrong digit is probably the same line; with half the digits wrong it is not.
_PHONE_EDITS_TO_ZERO = 5
# A ZIP sharing its first three digits is the same sectional center: weak, not nothing.
_ZIP_PREFIX_CREDIT = 0.5


@dataclass(frozen=True)
class FeatureVector:
    values: dict[str, float | None]
    missing: dict[str, bool]


def _clip01(x: float) -> float:
    return 0.0 if x < 0.0 else min(x, 1.0)


def jaro_winkler(a: str, b: str) -> float:
    return _clip01(jellyfish.jaro_winkler_similarity(a, b))


def damerau_similarity(a: str, b: str) -> float:
    """1 - normalized Damerau-Levenshtein, on the compact (space-free) forms."""
    ca, cb = a.replace(" ", ""), b.replace(" ", "")
    longest = max(len(ca), len(cb))
    if longest == 0:
        return 1.0
    return _clip01(1.0 - jellyfish.damerau_levenshtein_distance(ca, cb) / longest)


def token_overlap(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    """Shared tokens over the shorter list, so a dropped maternal surname still scores 1."""
    if not a or not b:
        return 0.0
    return len(set(a) & set(b)) / min(len(set(a)), len(set(b)))


def jaccard(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    sa, sb = set(a), set(b)
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0


def _name_features(
    prefix: str,
    accented_a: str,
    accented_b: str,
    folded_a: str,
    folded_b: str,
    tokens_a: tuple[str, ...],
    tokens_b: tuple[str, ...],
) -> dict[str, float]:
    return {
        f"{prefix}_jw": jaro_winkler(accented_a, accented_b),
        f"{prefix}_jw_folded": jaro_winkler(folded_a, folded_b),
        f"{prefix}_dl": damerau_similarity(folded_a, folded_b),
        f"{prefix}_token_overlap": token_overlap(tokens_a, tokens_b),
    }


def dob_signals(a: Normalized, b: Normalized) -> dict[str, float | None]:
    """The named DOB signals of ADR-001, each 0/1, ``None`` when a side has no full date."""
    year_match: float | None = None
    if a.birth_year is not None and b.birth_year is not None:
        year_match = 1.0 if a.birth_year == b.birth_year else 0.0
    out: dict[str, float | None] = {
        "dob_exact": None,
        "dob_day_month_swap": None,
        "dob_one_digit_edit": None,
        "dob_one_component_off": None,
        "dob_year_match": year_match,
    }
    if not (a.has_full_dob and b.has_full_dob):
        return out
    ya, ma, da = a.birth_year, a.birth_month, a.birth_day
    yb, mb, db = b.birth_year, b.birth_month, b.birth_day
    exact = (ya, ma, da) == (yb, mb, db)
    swap = (not exact) and ya == yb and ma == db and da == mb
    digits_a, digits_b = f"{ya:04d}{ma:02d}{da:02d}", f"{yb:04d}{mb:02d}{db:02d}"
    hamming = sum(1 for x, y in zip(digits_a, digits_b, strict=True) if x != y)
    components_off = sum(1 for x, y in ((ya, yb), (ma, mb), (da, db)) if x != y)
    out.update(
        {
            "dob_exact": 1.0 if exact else 0.0,
            "dob_day_month_swap": 1.0 if swap else 0.0,
            "dob_one_digit_edit": 1.0 if hamming == 1 else 0.0,
            # Each named signal is exclusive: a swap is not a component change and a one-digit edit is
            # not also "one component off", so the scorer never earns the credit twice.
            "dob_one_component_off": 1.0 if (components_off == 1 and not swap and hamming != 1) else 0.0,
        }
    )
    return out


def phone_similarity(digits_a: str, digits_b: str) -> float:
    if digits_a == digits_b:
        return 1.0
    edits = jellyfish.damerau_levenshtein_distance(digits_a, digits_b)
    return _clip01(1.0 - edits / _PHONE_EDITS_TO_ZERO)


def zip_similarity(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return _ZIP_PREFIX_CREDIT if a[:3] == b[:3] else 0.0


def compute_features(a: Normalized, b: Normalized) -> FeatureVector:
    values: dict[str, float | None] = dict.fromkeys(FEATURE_NAMES, None)
    missing: dict[str, bool] = dict.fromkeys(MISSING_GROUPS, True)

    names_usable = not (a.name_is_placeholder or b.name_is_placeholder)

    if names_usable and a.given_name and b.given_name and a.given_tokens and b.given_tokens:
        missing["given_name"] = False
        values.update(
            _name_features(
                "given",
                a.given_name,
                b.given_name,
                a.given_name_folded or "",
                b.given_name_folded or "",
                a.given_tokens,
                b.given_tokens,
            )
        )
        values["given_dmeta"] = 1.0 if phonetic_codes_match(a.given_tokens[0], b.given_tokens[0]) else 0.0
        # Equal tokens count as their own nickname, so a nickname variant can never outscore the
        # unchanged name; the TWIN rule reads the tokens directly, not this feature.
        values["given_nickname"] = (
            1.0 if any(same_nickname_family(x, y) for x in a.given_tokens for y in b.given_tokens) else 0.0
        )
        values["given_initial"] = 1.0 if a.given_tokens[0][0] == b.given_tokens[0][0] else 0.0

    if names_usable and a.family_name and b.family_name and a.family_tokens and b.family_tokens:
        missing["family_name"] = False
        values.update(
            _name_features(
                "family",
                a.family_name,
                b.family_name,
                a.family_name_folded or "",
                b.family_name_folded or "",
                a.family_tokens,
                b.family_tokens,
            )
        )
        # Any shared code across all surname tokens, so a dropped or reordered surname still matches.
        values["family_dmeta"] = 1.0 if set(a.family_codes) & set(b.family_codes) else 0.0

    dob_usable = not (
        is_placeholder_dob(a.birth_year, a.birth_month, a.birth_day)
        or is_placeholder_dob(b.birth_year, b.birth_month, b.birth_day)
    )
    if dob_usable:
        signals = dob_signals(a, b)
        values.update(signals)
        # "dob" counts as present only with two full dates; a year-only side keeps year_match.
        missing["dob"] = signals["dob_exact"] is None

    if a.sex and b.sex:
        missing["sex"] = False
        values["sex_match"] = 1.0 if a.sex == b.sex else 0.0

    if (
        a.phone_digits
        and b.phone_digits
        and not is_placeholder_phone(a.phone_digits)
        and not is_placeholder_phone(b.phone_digits)
    ):
        missing["phone"] = False
        values["phone_match"] = phone_similarity(a.phone_digits, b.phone_digits)

    if a.address_tokens and b.address_tokens:
        missing["address"] = False
        values["address_jaccard"] = jaccard(a.address_tokens, b.address_tokens)

    if a.zip5 and b.zip5 and not is_placeholder_zip(a.zip5) and not is_placeholder_zip(b.zip5):
        missing["zip"] = False
        values["zip_match"] = zip_similarity(a.zip5, b.zip5)

    return FeatureVector(values=values, missing=missing)
