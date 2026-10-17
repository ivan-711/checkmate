"""Codex finding 4: an oversized block is counted and skipped without ever enumerating its pairs."""

from __future__ import annotations

import uuid

from backend.api import match_runs
from contracts.version import BLOCK_MAX_RECORDS


def test_oversized_block_is_counted_without_materializing_pairs(monkeypatch):
    big = [uuid.uuid4() for _ in range(1_000)]
    small = [uuid.uuid4() for _ in range(3)]
    blocks = {("dob", "1970-01-01"): big, ("phone7", "5550100"): small}
    calls: list[int] = []

    real = match_runs.block_pairs

    def spy(ids):
        calls.append(len(ids))
        assert len(ids) <= BLOCK_MAX_RECORDS, "the pair generator ran on an oversized block"
        return real(ids)

    monkeypatch.setattr(match_runs, "block_pairs", spy)
    pairs, oversized, skipped = match_runs.candidate_pairs(blocks, set())
    assert calls == [3]
    assert len(pairs) == 3
    assert [(o.key_type, o.size) for o in oversized] == [("dob", 1_000)]
    assert skipped == 1_000 * 999 // 2


def test_pairs_also_reachable_through_a_small_block_are_not_counted_as_skipped():
    shared = [uuid.uuid4() for _ in range(2)]
    big = shared + [uuid.uuid4() for _ in range(BLOCK_MAX_RECORDS)]
    blocks = {("dob", "1970-01-01"): big, ("phone7", "5550100"): shared}
    pairs, oversized, skipped = match_runs.candidate_pairs(blocks, set())
    assert len(pairs) == 1
    assert oversized[0].size == BLOCK_MAX_RECORDS + 2
    assert skipped == len(big) * (len(big) - 1) // 2 - 1


def test_suppressed_pairs_are_dropped_from_small_blocks():
    a, b, c = sorted(uuid.uuid4() for _ in range(3))
    pairs, _, _ = match_runs.candidate_pairs({("dob", "x"): [a, b, c]}, {(a, b)})
    assert set(pairs) == {(a, c), (b, c)}
