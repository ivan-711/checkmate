"""Regression cases through the engine the app uses, at the app's current threshold row (explicit outcomes).

The engine is W2's ``backend.core``. Where it is not importable the cases skip with the reason, except when
``CHECKMATE_REQUIRE_ENGINE=1`` (CI on main), where its absence fails: a product regression must never pass
silently. Truth (``expected``) stays apart from the scorer inputs; no hero identity appears in the cases.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from eval.harness.current_thresholds import from_migrations
from eval.harness.product import ProductUnavailable, engine_input, load_engine

CASES_PATH = Path(__file__).resolve().parents[1] / "regression_cases.json"
CASES = json.loads(CASES_PATH.read_text())["cases"]
HERO_PATH = Path(__file__).resolve().parents[3] / "data" / "scenarios" / "hero" / "hero.json"
INPUT_FIELDS = {"given_name", "family_name", "birth_date", "sex", "phone", "address_line", "zip5"}


@pytest.fixture(scope="module")
def engine():
    try:
        return load_engine()
    except ProductUnavailable as exc:
        if os.environ.get("CHECKMATE_REQUIRE_ENGINE") == "1":
            pytest.fail(f"the app's engine is required here: {exc}")
        pytest.skip(f"the app's engine is not importable on this branch: {exc}")


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case_outcome(case, engine):
    op = from_migrations()
    a, b = case["inputs"]["a"], case["inputs"]["b"]
    result = engine.match(a, b, engine.shipped_weights, {"c_low": op.c_low, "c_high": op.c_high})
    expected = case["expected"]
    detail = f"{case['id']}: raw {result.raw_score:.3f}, band {result.band} at {op.thresholds_id}; {case['why']}"
    if "band_in" in expected:
        assert result.band in expected["band_in"], detail
    if "band_not" in expected:
        assert result.band not in expected["band_not"], detail


def test_cases_hold_scorer_inputs_only_and_no_showcase_identity():
    hero = json.loads(HERO_PATH.read_text())
    hero_names = {(r["given_name"], r["family_name"]) for r in hero["records"].values()}
    kinds = {c["kind"] for c in CASES}
    assert {"same_person", "different_people", "thin_record"} <= kinds
    assert sum(1 for c in CASES if c.get("nickname")) >= 3, "nickname outcomes are reported explicitly (R2)"
    for case in CASES:
        for side in ("a", "b"):
            record = case["inputs"][side]
            assert set(record) <= INPUT_FIELDS, (case["id"], set(record) - INPUT_FIELDS)
            assert set(engine_input(record)) >= set(record) - {"zip5"} | {"zip"}
            assert (record["given_name"], record["family_name"]) not in hero_names, case["id"]
