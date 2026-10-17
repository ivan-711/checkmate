"""Shared harness types: records, truth rows, the match callable and its result.

The harness never imports the backend. It takes records and a truth table (from W1's loader,
or from the in-repo synthetic fixture until W1 lands) and a ``match(a, b, weights, thresholds)``
callable (W2's signature; ``eval.harness.standin`` until W2 lands). Bands are read from the
raw score through ``c_low``/``c_high`` only; ``p`` is display-only (architecture section 6).
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

Record = dict[str, Any]
"""A record is a plain dict so W1's loader output and the fixture share one shape.

Keys the harness reads: ``record_id``, ``person_id`` (Synthea source person; the dependency-graph
node), ``source_system``, ``given_name``, ``family_name``, ``birth_date`` (ISO ``YYYY-MM-DD`` or
None), ``sex``, ``phone``, ``address_line``, ``zip5``, ``language`` (``EN``/``ES``), ``categories``
(corruption ids applied), ``donor_person_ids`` (persons whose fields this record borrowed).
"""

BAND_AUTO_LINK = "AUTO_LINK"
BAND_REVIEW = "REVIEW"
BAND_KEEP_SEPARATE = "KEEP_SEPARATE"
BANDS = (BAND_AUTO_LINK, BAND_REVIEW, BAND_KEEP_SEPARATE)

PARTITION_SHOWCASE = "showcase"
PARTITION_DEVELOPMENT = "development"
PARTITION_TEST = "test"


@dataclass(frozen=True)
class TruthRow:
    """One row of ``truth.csv`` (eval plan section 3)."""

    entity_id: str
    record_id: str
    source_system: str
    synthea_patient_id: str


@dataclass(frozen=True)
class MatchResult:
    """What ``match(a, b, weights, thresholds)`` returns (architecture section 12)."""

    raw_score: float
    p: float
    band: str
    contributions: tuple[tuple[str, float], ...] = ()
    negative_rules_fired: tuple[str, ...] = ()
    features: tuple[tuple[str, float | None], ...] = ()
    """Feature values in [0, 1], None when missing; optional (the evidence rail reads them)."""


MatchFn = Callable[[Record, Record, Mapping[str, float], Mapping[str, float]], MatchResult]
"""W2's signature. ``thresholds`` carries ``c_low`` and ``c_high`` (raw-score cutoffs)."""

FitFn = Callable[[Sequence[Record], Sequence[TruthRow]], Mapping[str, float]]
"""Fits weights on a training partition only (split step 6). Returns the weights ``match`` takes."""

BlockFn = Callable[[Sequence[Record]], set[tuple[str, str]]]
"""Blocking: record list to the set of candidate pairs as sorted ``(record_id, record_id)``."""


@dataclass
class Corpus:
    """Records plus truth plus the dependency edges the generator produced."""

    records: list[Record]
    truth: list[TruthRow]
    dependency_edges: list[tuple[str, str]] = field(default_factory=list)
    person_language: dict[str, str] = field(default_factory=dict)

    def record_by_id(self) -> dict[str, Record]:
        return {r["record_id"]: r for r in self.records}

    def entity_of(self) -> dict[str, str]:
        return {t.record_id: t.entity_id for t in self.truth}


def band_for(raw_score: float, c_low: float, c_high: float, negative_rules_fired: Sequence[str] = ()) -> str:
    """The one decision rule (architecture section 6): raw cutoffs, then negative rules demote."""
    if raw_score < c_low:
        return BAND_KEEP_SEPARATE
    if raw_score < c_high:
        return BAND_REVIEW
    return BAND_REVIEW if negative_rules_fired else BAND_AUTO_LINK


def pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)
