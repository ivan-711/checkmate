"""S3 block: candidate pairs a<b from five block keys (architecture section 3, ADR-001).

Keys: Double Metaphone of the family name + birth year; exact DOB; day/month-swapped DOB;
phone last 7; ZIP5 + first initial. Placeholder values never form a key. In match runs and
the evaluation runner a block over ``BLOCK_MAX_RECORDS`` is not expanded into pairs; its key,
size and the pairs reachable only through it are returned so nothing disappears silently.
The FrontDesk gate's one-record lookup (``candidates_for_record``) is never capped, because a
skipped block there would fail open toward a new chart.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Hashable, Iterable, Mapping
from dataclasses import dataclass, field
from itertools import combinations

from backend.core.normalize import Normalized
from backend.core.placeholders import is_placeholder_dob, is_placeholder_phone, is_placeholder_zip
from contracts.version import BLOCK_MAX_RECORDS

KEY_DMETA_FAMILY_YEAR = "DMETA_FAMILY_BIRTH_YEAR"
KEY_DOB_EXACT = "DOB_EXACT"
KEY_DOB_DAY_MONTH_SWAP = "DOB_DAY_MONTH_SWAP"
KEY_PHONE_LAST7 = "PHONE_LAST7"
KEY_ZIP5_INITIAL = "ZIP5_FIRST_INITIAL"
KEY_TYPES: tuple[str, ...] = (
    KEY_DMETA_FAMILY_YEAR,
    KEY_DOB_EXACT,
    KEY_DOB_DAY_MONTH_SWAP,
    KEY_PHONE_LAST7,
    KEY_ZIP5_INITIAL,
)
PHONE_LAST_DIGITS = 7
# Inclusion-exclusion over hot blocks is exact up to this many; beyond it the sum is reported as a bound.
MAX_EXACT_HOT_BLOCKS = 8

RecordId = Hashable
PairKey = tuple[str, str]  # (str(a), str(b)) with a < b, the contract's ordering


@dataclass(frozen=True, order=True)
class BlockKey:
    key_type: str
    key_value: str

    def __str__(self) -> str:
        return f"{self.key_type}:{self.key_value}"


@dataclass(frozen=True)
class CandidatePair:
    record_a_id: str
    record_b_id: str
    block_keys: tuple[str, ...]


@dataclass(frozen=True)
class OversizedBlock:
    key: str
    size: int
    pairs_in_block: int
    pairs_skipped: int  # reachable only through this block (never dropped silently)


@dataclass(frozen=True)
class BlockingResult:
    pairs: tuple[CandidatePair, ...]
    n_records: int
    n_total_pairs: int  # N = n(n-1)/2, the reduction-ratio denominator
    n_candidate_pairs: int
    reduction_ratio: float  # 1 - |B| / N (evaluation plan section 5)
    n_excluded_not_a_match: int
    oversized_blocks: tuple[OversizedBlock, ...] = ()
    pairs_skipped_oversized: int = 0
    # True when there are more than MAX_EXACT_HOT_BLOCKS hot blocks: the total is then the sum of
    # the per-block counts, which double-counts a pair inside two of them. Per-block counts stay exact.
    pairs_skipped_is_upper_bound: bool = False
    block_sizes: Mapping[str, int] = field(default_factory=dict)


def _dob_keys(n: Normalized) -> list[BlockKey]:
    y, m, d = n.birth_year, n.birth_month, n.birth_day
    if y is None or m is None or d is None or is_placeholder_dob(y, m, d):
        return []
    keys = [BlockKey(KEY_DOB_EXACT, f"{y:04d}-{m:02d}-{d:02d}")]
    # The swap key is the unordered (month, day) pair, so 03-07 and 07-03 land in one block.
    # Only a day that could be a month can have been swapped, and equal parts need no key.
    if d <= 12 and d != m:
        lo, hi = sorted((m, d))
        keys.append(BlockKey(KEY_DOB_DAY_MONTH_SWAP, f"{y:04d}-{lo:02d}-{hi:02d}"))
    return keys


def block_keys(n: Normalized) -> list[BlockKey]:
    """Every block key one record contributes; placeholders contribute nothing.

    One surname key per Double Metaphone code of each non-particle family token (see
    ``normalize.surname_codes``), so a dropped maternal surname (S3) or a swapped surname
    order (S4) still shares a block with the full name.
    """
    keys: list[BlockKey] = []
    dob_is_placeholder = is_placeholder_dob(n.birth_year, n.birth_month, n.birth_day)
    if n.family_codes and n.birth_year is not None and not n.name_is_placeholder and not dob_is_placeholder:
        keys.extend(BlockKey(KEY_DMETA_FAMILY_YEAR, f"{code}|{n.birth_year:04d}") for code in n.family_codes)
    keys.extend(_dob_keys(n))
    if n.phone_digits and not is_placeholder_phone(n.phone_digits):
        keys.append(BlockKey(KEY_PHONE_LAST7, n.phone_digits[-PHONE_LAST_DIGITS:]))
    if not is_placeholder_zip(n.zip5) and n.given_name_folded and not n.name_is_placeholder:
        keys.append(BlockKey(KEY_ZIP5_INITIAL, f"{n.zip5}|{n.given_name_folded[0]}"))
    return keys


def build_block_index(records: Mapping[RecordId, Normalized]) -> dict[BlockKey, list[RecordId]]:
    index: dict[BlockKey, list[RecordId]] = defaultdict(list)
    for record_id, norm in records.items():
        for key in block_keys(norm):
            index[key].append(record_id)
    return dict(index)


def _ordered(a: RecordId, b: RecordId) -> PairKey:
    sa, sb = str(a), str(b)
    return (sa, sb) if sa < sb else (sb, sa)


def normalize_exclusions(exclusions: Iterable[Iterable[RecordId]] | None) -> frozenset[PairKey]:
    """``not_a_match`` pairs in any order or container shape, as ordered string pairs."""
    if not exclusions:
        return frozenset()
    out = set()
    for pair in exclusions:
        a, b = tuple(pair)
        if str(a) == str(b):
            continue  # a self-pair is never a candidate, so it must not be subtracted anywhere
        out.add(_ordered(a, b))
    return frozenset(out)


def candidate_pairs(
    records: Mapping[RecordId, Normalized],
    exclusions: Iterable[Iterable[RecordId]] | None = None,
    max_block_records: int | None = BLOCK_MAX_RECORDS,
) -> BlockingResult:
    """All candidate pairs of a match run. ``max_block_records=None`` disables the hot-block cap."""
    index = build_block_index(records)
    excluded = normalize_exclusions(exclusions)
    keys_by_pair: dict[PairKey, list[str]] = defaultdict(list)
    excluded_seen: set[PairKey] = set()
    skipped: list[tuple[BlockKey, list[RecordId]]] = []
    for key in sorted(index):
        members = index[key]
        if len(members) < 2:
            continue
        if max_block_records is not None and len(members) > max_block_records:
            skipped.append((key, members))
            continue
        for a, b in combinations(sorted(members, key=str), 2):
            pair = _ordered(a, b)
            if pair in excluded:
                excluded_seen.add(pair)
                continue
            keys_by_pair[pair].append(str(key))
    # An oversized block is never expanded, not even to count. The candidate and exclusion sets
    # (both bounded) are scanned once, tagging each pair with the bitmask of hot blocks holding
    # it; everything else is arithmetic on member-set intersections, so the cost is O(|B| + n)
    # per run rather than O(n^2) per hot block.
    member_sets = [{str(m) for m in members} for _, members in skipped]

    def hot_mask(pair: PairKey) -> int:
        a, b = pair
        return sum(1 << i for i, ms in enumerate(member_sets) if a in ms and b in ms)

    produced_masks = Counter(hot_mask(pair) for pair in keys_by_pair)
    excluded_masks = Counter(hot_mask(pair) for pair in excluded)

    def pairs_in(member_set: set[str]) -> int:
        return len(member_set) * (len(member_set) - 1) // 2

    def removed_with_bit(bit: int) -> int:
        return sum(c for m, c in produced_masks.items() if m & bit) + sum(
            c for m, c in excluded_masks.items() if m & bit
        )

    oversized = [
        OversizedBlock(
            key=str(key),
            size=len(members),
            pairs_in_block=pairs_in(member_set),
            pairs_skipped=pairs_in(member_set) - removed_with_bit(1 << i),
        )
        for i, ((key, members), member_set) in enumerate(zip(skipped, member_sets, strict=True))
    ]
    is_upper_bound = len(member_sets) > MAX_EXACT_HOT_BLOCKS
    if is_upper_bound or len(member_sets) <= 1:
        total_skipped = sum(block.pairs_skipped for block in oversized)
    else:
        # Union of the hot blocks' pair sets by inclusion-exclusion on member-set intersections,
        # minus every produced or excluded pair that sits in at least one hot block.
        union_pairs = 0
        for size in range(1, len(member_sets) + 1):
            sign = 1 if size % 2 else -1
            for subset in combinations(member_sets, size):
                union_pairs += sign * pairs_in(set.intersection(*subset))
        removed_any = sum(c for m, c in produced_masks.items() if m) + sum(c for m, c in excluded_masks.items() if m)
        total_skipped = union_pairs - removed_any
    n = len(records)
    n_total = n * (n - 1) // 2
    pairs = tuple(
        CandidatePair(record_a_id=a, record_b_id=b, block_keys=tuple(sorted(keys)))
        for (a, b), keys in sorted(keys_by_pair.items())
    )
    return BlockingResult(
        pairs=pairs,
        n_records=n,
        n_total_pairs=n_total,
        n_candidate_pairs=len(pairs),
        reduction_ratio=(1.0 - len(pairs) / n_total) if n_total else 0.0,
        n_excluded_not_a_match=len(excluded_seen),
        oversized_blocks=tuple(oversized),
        pairs_skipped_oversized=total_skipped,
        pairs_skipped_is_upper_bound=is_upper_bound,
        block_sizes={str(k): len(v) for k, v in index.items()},
    )


def candidates_for_record(
    probe_id: RecordId,
    probe: Normalized,
    index: Mapping[BlockKey, list[RecordId]],
    exclusions: Iterable[Iterable[RecordId]] | None = None,
) -> list[CandidatePair]:
    """One record against the index, linear in block size, never capped (the gate's lookup)."""
    excluded = normalize_exclusions(exclusions)
    keys_by_other: dict[RecordId, list[str]] = defaultdict(list)
    for key in block_keys(probe):
        for other in index.get(key, ()):
            if other == probe_id or _ordered(probe_id, other) in excluded:
                continue
            keys_by_other[other].append(str(key))
    out = []
    for other, keys in keys_by_other.items():
        a, b = _ordered(probe_id, other)
        out.append(CandidatePair(record_a_id=a, record_b_id=b, block_keys=tuple(sorted(keys))))
    return sorted(out, key=lambda p: (p.record_a_id, p.record_b_id))
