"""The seam between the API lane (W3a) and the matching core (W2): blocking keys and one
``match(a, b, thresholds)`` call (architecture §3 S3-S6, §12).

W2 implements ``MatchCore`` in ``backend/core`` and exposes an instance as
``backend.core.api.CORE``. Until that merges, ``resolve_core`` falls back to the stand-in
in ``backend/match/standin.py`` and logs that it did. The API never imports feature or
scorer code directly; it only sees ``EvidenceSnapshot`` (the frozen contract model), the
band and the display-only ``p``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from contracts.models.common import Band
from contracts.models.pairs import EvidenceSnapshot
from contracts.models.records import NormalizedRecord

log = logging.getLogger("checkmate.match")

# The only absences that mean "W2 has not merged yet"; anything else is a real failure.
W2_MODULES = frozenset({"backend.core", "backend.core.api"})


@dataclass(frozen=True)
class BlockKey:
    key_type: str  # one per architecture §3 blocking key; stored in block_key.key_type
    key_value: str


@dataclass(frozen=True)
class Thresholds:
    """The current ``threshold_set`` row. ``c_low``/``c_high`` decide; the rest is display-only."""

    threshold_set_id: str
    c_low: float
    c_high: float
    platt_a: float | None = None
    platt_b: float | None = None
    t_low_display: float | None = None
    t_high_display: float | None = None


@dataclass(frozen=True)
class MatchResult:
    """S5 + S6 for one pair: the immutable evidence, the logit, the display-only ``p`` and the band
    after negative rules (``evidence.negative_rules_fired`` lists them)."""

    evidence: EvidenceSnapshot
    logit: float
    p: float
    band: Band


class MatchCore(Protocol):
    scorer_version: str

    def block_keys(self, record: NormalizedRecord) -> list[BlockKey]:
        """S3: the keys this record blocks on. Placeholder values never form a key."""

    def match(self, a: NormalizedRecord, b: NormalizedRecord, thresholds: Thresholds) -> MatchResult:
        """S4-S6 for one pair, pure: no DB, clock or randomness."""


def resolve_core() -> MatchCore:
    try:
        from backend.core.api import CORE  # W2's instance; absent until lane W2 merges
    except ModuleNotFoundError as exc:
        if exc.name not in W2_MODULES:
            raise  # a dependency missing inside W2's code: never substitute different scoring
        from backend.match.standin import StandInCore

        log.warning("backend.core.api not found: using the W3a stand-in scorer (replace when W2 merges)")
        return StandInCore()
    return CORE
