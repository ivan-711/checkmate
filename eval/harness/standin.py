"""Stand-in blocking, features and scorer with W2's ``match(a, b, weights, thresholds)`` signature.

Used until W2 merges. It is a logistic scorer over named features with per-feature
contributions, negative rules that demote AUTO_LINK to REVIEW, and a display-only sigmoid
``p``. ``fit`` returns the fixed weights and records which rows it saw, so the split
assertion (eval plan section 3 step 6) can be exercised. Nothing here is a claim about W2's
features; the harness only needs the contract shape.
"""
from __future__ import annotations

import difflib
import math
import unicodedata
from collections.abc import Mapping, Sequence

from contracts.version import BLOCK_MAX_RECORDS
from eval.harness.types import MatchResult, Record, TruthRow, band_for, pair_key

SCORER_VERSION = "standin-logistic-0"

FEATURES = ("given_name_jw", "family_name_jw", "family_metaphone", "dob_exact", "dob_day_month_swap",
            "dob_one_digit_edit", "sex_match", "phone_match", "address_jaccard", "zip_match")

DEFAULT_WEIGHTS: dict[str, float] = {
    # Stand-in weights only (W2 fits the real ones). Address and exact DOB carry the most weight so
    # that a REVIEW pair can lose the band when the address goes or the birth year changes; the
    # day/month swap feature sits just under exact DOB so the swap barely moves the score.
    "intercept": -4.5,
    "given_name_jw": 1.4,
    "family_name_jw": 1.6,
    "family_metaphone": 0.5,
    "dob_exact": 3.0,
    "dob_day_month_swap": 2.9,
    "dob_one_digit_edit": 0.2,
    "sex_match": 0.3,
    "phone_match": 1.2,
    "address_jaccard": 3.0,
    "zip_match": 0.8,
}

PLACEHOLDER_DOBS = frozenset({"1900-01-01", "1800-01-01", "0001-01-01"})
PLACEHOLDER_PHONES = frozenset({"+15555555555", "5555555555"})
PLACEHOLDER_NAMES = frozenset({"unknown", "test", "patient", "baby", "doe"})
PARENT_CHILD_YEARS = 18
TWIN_GIVEN_NAME_MAX_SIM = 0.6     # same DOB, surname and address with clearly different given names
BIRTH_YEAR_GAP_MAX = 2


def fold(text: str | None) -> str:
    if not text:
        return ""
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)).lower().strip()


def _skeleton(text: str) -> str:
    """Consonant skeleton of the first surname token: a crude stand-in for Double Metaphone."""
    first = fold(text).replace("-", " ").split()
    if not first:
        return ""
    token = first[0]
    return token[0] + "".join(ch for ch in token[1:] if ch not in "aeiouhwy")


def _sim(a: str | None, b: str | None) -> float | None:
    fa, fb = fold(a), fold(b)
    if not fa or not fb:
        return None
    return difflib.SequenceMatcher(None, fa, fb).ratio()


def _jaccard(a: str | None, b: str | None) -> float | None:
    sa, sb = set(fold(a).split()), set(fold(b).split())
    if not sa or not sb:
        return None
    return len(sa & sb) / len(sa | sb)


def _dob_parts(dob: str | None) -> tuple[str, str, str] | None:
    if not dob or dob in PLACEHOLDER_DOBS:
        return None
    parts = dob.split("-")
    return (parts[0], parts[1], parts[2]) if len(parts) == 3 else None


def features(a: Record, b: Record) -> dict[str, float | None]:
    da, db = _dob_parts(a.get("birth_date")), _dob_parts(b.get("birth_date"))
    out: dict[str, float | None] = {
        "given_name_jw": _sim(a.get("given_name"), b.get("given_name")),
        "family_name_jw": _sim(a.get("family_name"), b.get("family_name")),
        "family_metaphone": None if not (a.get("family_name") and b.get("family_name"))
        else float(_skeleton(a["family_name"]) == _skeleton(b["family_name"])),
        "sex_match": None if not (a.get("sex") and b.get("sex")) else float(a["sex"] == b["sex"]),
        "phone_match": None if not (a.get("phone") and b.get("phone")) or a["phone"] in PLACEHOLDER_PHONES
        else float(a["phone"] == b["phone"]),
        "address_jaccard": _jaccard(a.get("address_line"), b.get("address_line")),
        "zip_match": None if not (a.get("zip5") and b.get("zip5")) else float(a["zip5"] == b["zip5"]),
    }
    if da is None or db is None:
        out.update(dob_exact=None, dob_day_month_swap=None, dob_one_digit_edit=None)
    else:
        exact = da == db
        swap = (not exact) and da[0] == db[0] and da[1] == db[2] and da[2] == db[1]
        sa, sb = "".join(da), "".join(db)
        one_digit = (not exact) and (not swap) and sum(x != y for x, y in zip(sa, sb)) == 1
        out.update(dob_exact=float(exact), dob_day_month_swap=float(swap), dob_one_digit_edit=float(one_digit))
    return out


def negative_rules(a: Record, b: Record) -> tuple[str, ...]:
    fired: list[str] = []
    if a.get("sex") and b.get("sex") and a["sex"] != b["sex"]:
        fired.append("SEX_CONFLICT")
    da, db = _dob_parts(a.get("birth_date")), _dob_parts(b.get("birth_date"))
    if da and db:
        gap = abs(int(da[0]) - int(db[0]))
        same_name = fold(a.get("given_name")) == fold(b.get("given_name")) and \
            fold(a.get("family_name")) == fold(b.get("family_name"))
        same_address = fold(a.get("address_line")) and fold(a.get("address_line")) == fold(b.get("address_line"))
        if gap > BIRTH_YEAR_GAP_MAX:
            fired.append("BIRTH_YEAR_GAP_GT_2")
        if gap >= PARENT_CHILD_YEARS and same_name and same_address:
            fired.append("PARENT_CHILD")
        given_sim = _sim(a.get("given_name"), b.get("given_name"))
        if da == db and same_address and fold(a.get("family_name")) == fold(b.get("family_name")) \
                and given_sim is not None and given_sim < TWIN_GIVEN_NAME_MAX_SIM:
            fired.append("TWIN")
    for rec in (a, b):
        placeholder_name = (fold(rec.get("given_name")) in PLACEHOLDER_NAMES
                            or fold(rec.get("family_name")) in PLACEHOLDER_NAMES)
        if placeholder_name and "PLACEHOLDER_NAME" not in fired:
            fired.append("PLACEHOLDER_NAME")
        if rec.get("birth_date") in PLACEHOLDER_DOBS and "PLACEHOLDER_DOB" not in fired:
            fired.append("PLACEHOLDER_DOB")
    return tuple(fired)


def display_p(raw_score: float, thresholds: Mapping[str, float]) -> float:
    """Display-only sigmoid; a Platt map (``platt_a`` < 0, ``platt_b``) overrides it when present."""
    a = thresholds.get("platt_a")
    b = thresholds.get("platt_b")
    z = -(a * raw_score + b) if a is not None and b is not None else raw_score
    return 1.0 / (1.0 + math.exp(-z)) if z > -700 else 0.0


def match(a: Record, b: Record, weights: Mapping[str, float], thresholds: Mapping[str, float]) -> MatchResult:
    """W2's signature. Decisions come from the raw score through ``c_low``/``c_high`` only."""
    feats = features(a, b)
    contributions: list[tuple[str, float]] = []
    raw = float(weights.get("intercept", 0.0))
    for name in FEATURES:
        value = feats[name]
        logit = 0.0 if value is None else float(weights.get(name, 0.0)) * value
        contributions.append((name, logit))
        raw += logit
    rules = negative_rules(a, b)
    band = band_for(raw, thresholds["c_low"], thresholds["c_high"], rules)
    return MatchResult(raw_score=raw, p=display_p(raw, thresholds), band=band,
                       contributions=tuple(contributions), negative_rules_fired=rules,
                       features=tuple((name, feats[name]) for name in FEATURES))


class FitRecorder:
    """Remembers which record ids every fit saw, so the partition assertion has something to check."""

    def __init__(self) -> None:
        self.seen: list[set[str]] = []

    def fit(self, records: Sequence[Record], truth: Sequence[TruthRow]) -> Mapping[str, float]:
        self.seen.append({r["record_id"] for r in records})
        return dict(DEFAULT_WEIGHTS)


def fit(records: Sequence[Record], truth: Sequence[TruthRow]) -> Mapping[str, float]:
    """The stand-in has no learned parameters: the fixed weights are returned unchanged."""
    return dict(DEFAULT_WEIGHTS)


def block_keys(rec: Record) -> list[str]:
    """Blocking keys per CLAUDE.md W2: surname skeleton + birth year, exact DOB, swapped DOB,
    phone last 7, ZIP5 + given initial. Placeholder values never block."""
    keys: list[str] = []
    dob = _dob_parts(rec.get("birth_date"))
    family, given = fold(rec.get("family_name")), fold(rec.get("given_name"))
    if family and family not in PLACEHOLDER_NAMES and dob:
        keys.append(f"metaphone_surname_birth_year:{_skeleton(family)}:{dob[0]}")
    if dob:  # one prefix: the swapped rendering must share a bucket with the partner's literal DOB
        keys.append(f"dob:{'-'.join(dob)}")
        keys.append(f"dob:{dob[0]}-{dob[2]}-{dob[1]}")
    phone = rec.get("phone")
    if phone and phone not in PLACEHOLDER_PHONES:
        keys.append(f"phone_last7:{phone[-7:]}")
    if rec.get("zip5") and given and given not in PLACEHOLDER_NAMES:
        keys.append(f"zip5_initial:{rec['zip5']}:{given[0]}")
    return keys


def block(records: Sequence[Record], max_block: int = BLOCK_MAX_RECORDS) -> set[tuple[str, str]]:
    """Candidate pairs from the union of blocks; blocks over ``max_block`` records are skipped."""
    buckets: dict[str, list[str]] = {}
    for rec in records:
        for key in block_keys(rec):
            buckets.setdefault(key, []).append(rec["record_id"])
    pairs: set[tuple[str, str]] = set()
    for members in buckets.values():
        if len(members) > max_block:
            continue
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                if a != b:
                    pairs.add(pair_key(a, b))
    return pairs
