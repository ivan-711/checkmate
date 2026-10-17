"""``backend.core.api.CORE`` must agree with ``match()`` and stay independent of W3a's seam."""

import subprocess
import sys
from dataclasses import dataclass
from uuid import uuid4

from backend.core.api import CORE, CoreMatch
from backend.core.band import DEMO_THRESHOLDS, match
from backend.core.block import block_keys
from backend.core.normalize import normalize_record
from backend.core.score import HANDSET_WEIGHTS
from contracts.models.common import Band
from contracts.models.pairs import EvidenceSnapshot
from contracts.models.records import NormalizedRecord


@dataclass(frozen=True)
class SeamThresholds:
    """Same fields as ``backend.match.seam.Thresholds``, declared here so the test needs no W3a code."""

    threshold_set_id: str
    c_low: float
    c_high: float
    platt_a: float | None = None
    platt_b: float | None = None
    t_low_display: float | None = None
    t_high_display: float | None = None


SEAM_DEMO = SeamThresholds(
    threshold_set_id=DEMO_THRESHOLDS.thresholds_id, c_low=DEMO_THRESHOLDS.c_low, c_high=DEMO_THRESHOLDS.c_high
)

A = {
    "given_name": "Robert",
    "family_name": "Smith",
    "dob": "1990-03-07",
    "sex": "M",
    "phone": "617-555-2368",
    "address": "12 Main St",
    "zip": "02139",
}
B = {**A, "dob": "1990-07-03", "address": "12 Main Street"}


def contract_record(raw: dict) -> NormalizedRecord:
    """The shape the seam passes: the frozen contract model built from W2's normalizer."""
    return NormalizedRecord(**normalize_record({"record_id": str(uuid4()), **raw}).to_contract_dict())


def test_core_scores_a_handset_pair_exactly_like_match():
    a, b = contract_record(A), contract_record(B)
    direct = match(a, b, HANDSET_WEIGHTS, DEMO_THRESHOLDS)
    via_core = CORE.match(a, b, SEAM_DEMO)
    assert isinstance(via_core, CoreMatch)
    assert via_core.logit == direct.raw_score
    assert via_core.band is direct.band is Band.AUTO_LINK
    assert via_core.p == direct.p
    assert CORE.scorer_version == "handset-0"


def test_core_evidence_is_the_frozen_contract_snapshot():
    via_core = CORE.match(contract_record(A), contract_record(B), SEAM_DEMO)
    assert isinstance(via_core.evidence, EvidenceSnapshot)
    assert via_core.evidence.raw_score == via_core.logit
    assert via_core.evidence.threshold_set_id == DEMO_THRESHOLDS.thresholds_id
    assert via_core.evidence.c_high == DEMO_THRESHOLDS.c_high
    assert via_core.evidence.scorer_version == "handset-0"


def test_core_block_keys_match_the_blocking_stage_and_carry_the_seam_fields():
    record = contract_record(A)
    keys = CORE.block_keys(record)
    assert keys == block_keys(normalize_record(record.model_dump()))
    assert keys and all(isinstance(k.key_type, str) and isinstance(k.key_value, str) for k in keys)


def test_thresholds_without_display_fields_are_accepted():
    @dataclass(frozen=True)
    class Minimal:
        threshold_set_id: str
        c_low: float
        c_high: float

    result = CORE.match(contract_record(A), contract_record(B), Minimal("t", 0.0, 4.0))
    assert result.band is Band.AUTO_LINK


def test_core_api_imports_no_seam_api_or_frontdesk_module():
    """Fresh interpreter so other tests' imports cannot hide a dependency."""
    probe = (
        "import sys, backend.core.api; "
        "bad = sorted(m for m in sys.modules if m.startswith(('backend.match', 'backend.api', 'backend.frontdesk'))); "
        "print(','.join(bad))"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == ""


def test_row_platt_map_and_display_thresholds_win_and_weights_are_the_fallback():
    from backend.core.score import display_probability

    a, b = contract_record(A), contract_record(B)
    row = SeamThresholds("q5", 0.0, 4.0, platt_a=-0.5, platt_b=0.2, t_low_display=0.45, t_high_display=0.86)
    with_map = CORE.match(a, b, row)
    assert (with_map.evidence.platt_a, with_map.evidence.platt_b) == (-0.5, 0.2)
    assert (with_map.evidence.t_low_display, with_map.evidence.t_high_display) == (0.45, 0.86)
    assert with_map.logit == CORE.match(a, b, SEAM_DEMO).logit  # Platt never moves the raw score
    assert with_map.band is CORE.match(a, b, SEAM_DEMO).band
    fallback = CORE.match(a, b, SEAM_DEMO)
    assert fallback.evidence.platt_a is None
    assert fallback.evidence.t_high_display == display_probability(DEMO_THRESHOLDS.c_high, HANDSET_WEIGHTS)
    assert CORE.weights is HANDSET_WEIGHTS  # the row's map is applied per call, never stored


def test_a_row_platt_map_that_would_decrease_p_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        CORE.match(contract_record(A), contract_record(B), SeamThresholds("bad", 0.0, 4.0, platt_a=0.5, platt_b=0.0))
