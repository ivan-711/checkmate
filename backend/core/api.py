"""W2's matching core behind W3a's match seam (``backend.match.seam.MatchCore``).

``backend.match.seam.resolve_core`` imports ``CORE`` from here and falls back to W3a's stand-in
scorer while this module is absent. The API sees only the frozen ``EvidenceSnapshot``, the band
and the display-only ``p``; features, weights and blocking stay in ``backend.core``.

Duck-typed on purpose: ``core/`` imports nothing from ``backend.match``, ``backend.api`` or
``frontdesk``. The seam imports this module, so importing the seam back would make a cycle and
would break this module on any branch where W3a has not merged. The returned objects carry
exactly the attributes the seam's ``BlockKey`` and ``MatchResult`` declare.

First written by the integration helper (967fce2); made duck-typed in lane W2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from backend.core.band import evidence_snapshot
from backend.core.band import match as core_match
from backend.core.block import BlockKey
from backend.core.block import block_keys as core_block_keys
from backend.core.normalize import coerce_normalized
from backend.core.score import HANDSET_WEIGHTS, Weights
from contracts.models.common import Band
from contracts.models.pairs import EvidenceSnapshot
from contracts.models.thresholds import ThresholdSet


class ThresholdsLike(Protocol):
    """What this module reads from the seam's ``Thresholds`` row: ``c_low``/``c_high`` decide."""

    threshold_set_id: str
    c_low: float
    c_high: float


@dataclass(frozen=True)
class CoreMatch:
    """Same fields as the seam's ``MatchResult``; the band is after the negative rules."""

    evidence: EvidenceSnapshot
    logit: float
    p: float  # display-only
    band: Band


def to_threshold_set(thresholds: ThresholdsLike) -> ThresholdSet:
    """The seam's threshold row as the contract model ``backend.core.band`` takes.

    The display fields are optional on the seam's row, so they are read with a default.
    """
    return ThresholdSet(
        thresholds_id=thresholds.threshold_set_id,
        c_low=thresholds.c_low,
        c_high=thresholds.c_high,
        t_low_display=getattr(thresholds, "t_low_display", None),
        t_high_display=getattr(thresholds, "t_high_display", None),
    )


class Core:
    """``MatchCore`` over a weights object; ``handset-0`` until a trained set replaces it."""

    def __init__(self, weights: Weights = HANDSET_WEIGHTS) -> None:
        self.weights = weights
        self.scorer_version = weights.scorer_version

    def block_keys(self, record: Any) -> list[BlockKey]:
        """S3 keys for one record (``NormalizedRecord``, row or ``Normalized``); placeholders never key."""
        return core_block_keys(coerce_normalized(record))

    def match(self, a: Any, b: Any, thresholds: ThresholdsLike) -> CoreMatch:
        """S4-S6 for one pair through ``backend.core.band.match``; pure."""
        ts = to_threshold_set(thresholds)
        result = core_match(a, b, self.weights, ts)
        return CoreMatch(
            evidence=evidence_snapshot(result, self.weights, ts),
            logit=result.raw_score,
            p=result.p,
            band=result.band,
        )


CORE = Core()
