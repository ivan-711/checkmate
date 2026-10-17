"""Same inputs, same outputs: the gate, the API and the evaluation runner must agree."""

import random

from backend.core.band import DEMO_THRESHOLDS, match
from backend.core.block import candidate_pairs
from backend.core.normalize import normalize_record
from backend.core.score import HANDSET_WEIGHTS

A = {
    "record_id": "a",
    "given_name": "José",
    "family_name": "García-López",
    "dob": "1990-03-07",
    "sex": "M",
    "phone": "617-555-2368",
    "address": "12 Main St",
    "zip": "02139",
}
B = {
    "record_id": "b",
    "given_name": "Jose",
    "family_name": "Garcia Lopez",
    "dob": "1990-07-03",
    "sex": "M",
    "phone": "617-555-2368",
    "address": "12 Main Street",
    "zip": "02139",
}


def test_match_is_deterministic_across_repeated_calls():
    first = match(A, B, HANDSET_WEIGHTS, DEMO_THRESHOLDS)
    for _ in range(25):
        assert match(A, B, HANDSET_WEIGHTS, DEMO_THRESHOLDS) == first
    assert first.as_dict() == match(A, B, HANDSET_WEIGHTS, DEMO_THRESHOLDS).as_dict()


def test_blocking_is_independent_of_record_insertion_order():
    rng = random.Random(7)
    records = {
        f"r{i:02d}": normalize_record(
            {
                "given_name": rng.choice(["Ana", "Luis", "Maria"]),
                "family_name": rng.choice(["Perez", "Lopez", "Diaz"]),
                "dob": f"19{rng.randint(50, 99)}-0{rng.randint(1, 9)}-{rng.randint(10, 28)}",
                "zip": rng.choice(["02139", "10001"]),
            }
        )
        for i in range(40)
    }
    baseline = candidate_pairs(records)
    for seed in range(5):
        items = list(records.items())
        random.Random(seed).shuffle(items)
        assert candidate_pairs(dict(items)) == baseline
