"""R5: bootstrap, n, zero-event rule, never-say words, protected hashes, tolerance values (eval plan 5, 7, 9)."""
from __future__ import annotations

import hashlib
import json

from eval.harness.metrics import ScoredPair, bootstrap_ci, rate
from eval.harness.run import EXPECTATIONS_DIR, REPO_ROOT
from eval.harness.summary import render
from eval.harness.testing import fast_run

NEVER_SAY = ("certified", "guaranteed", "bounded", "calibrated")
RATE_PREFIXES = ("band.", "recall.", "false_merge", "review", "category.", "button.", "hard_negative.", "blocking.recall")


def _rate_cells(numbers: dict) -> dict:
    return {k: v for k, v in numbers.items()
            if k.startswith(RATE_PREFIXES) and not k.endswith((".kind", ".count")) and "items_per_1000" not in k}


def test_every_rate_carries_n_as_pairs_entities_components_ci_and_support_flag():
    numbers = fast_run().numbers
    missing = {k: sorted({"n_pairs", "n_entities", "n_components", "ci95", "low_support"} - set(v))
               for k, v in _rate_cells(numbers).items()}
    missing = {k: v for k, v in missing.items() if v}
    assert missing == {}, f"rates without full n/interval/support: {missing}"


def test_bootstrap_uses_1000_seeded_resamples_in_every_published_run():
    """Eval plan section 5: 1,000 seeded resamples is the one interval method, stated once."""
    manifest = fast_run().manifest
    assert manifest["bootstrapResamples"] == 1000, manifest["bootstrapResamples"]


def test_bootstrap_resampling_unit_is_the_component_and_is_seeded():
    rows = [ScoredPair(f"a{i}", f"b{i}", f"E{i}", f"E{i}", "C0", "C0", 1.0, 0.5, ()) for i in range(40)]
    ci = bootstrap_ci(rows[:10], rows, seed=3, resamples=200)
    assert ci == [0.25, 0.25], "one component resampled with replacement must give a degenerate interval"
    many = [ScoredPair(f"a{i}", f"b{i}", f"E{i}", f"E{i}", f"C{i}", f"C{i}", 1.0, 0.5, ()) for i in range(60)]
    a, b = bootstrap_ci(many[:30], many, 11, 300), bootstrap_ci(many[:30], many, 11, 300)
    assert a == b and a[0] <= 0.5 <= a[1]


def test_zero_event_cell_prints_no_upper_bound_and_states_support():
    rows = [ScoredPair(f"a{i}", f"b{i}", f"E{i}", f"E{i}", f"C{i}", f"C{i}", 3.0, 0.9, ()) for i in range(70)]
    cell = rate([], rows, seed=1, resamples=50)
    assert cell["ci95"] is None and cell["zero_events"] and cell["n_pairs"] == 70 and cell["n_components"] == 70
    assert "zero observed" in cell["note"]
    assert cell["low_support"] is False


def test_support_floor_flags_under_50_components():
    rows = [ScoredPair(f"a{i}", f"b{i}", f"E{i}", f"E{i}", f"C{i % 49}", f"C{i % 49}", 3.0, 0.9, ()) for i in range(200)]
    cell = rate(rows[:100], rows, seed=1, resamples=20)
    assert cell["n_components"] == 49 and cell["low_support"] is True


def test_no_never_say_word_in_any_run_output_or_hero_caption():
    result = fast_run()
    texts = [p.read_text().lower() for p in result.run_dir.iterdir()]
    texts.append(render(result.numbers, result.manifest).lower())
    hero_dir = REPO_ROOT / "data" / "scenarios" / "hero"
    texts += [(hero_dir / n).read_text().lower() for n in ("scenario.json", "hero.json", "selection.json")]
    for text in texts:
        for word in NEVER_SAY:
            assert word not in text.replace("iscalibrated", "").replace("is_calibrated", ""), word


def test_run_json_records_sha256_of_every_protected_expectation_file():
    result = fast_run()
    recorded = json.loads((result.run_dir / "run.json").read_text())["expectations"]
    for path in EXPECTATIONS_DIR.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            rel = path.relative_to(EXPECTATIONS_DIR).as_posix()
            assert recorded.get(rel) == hashlib.sha256(path.read_bytes()).hexdigest(), rel


def test_run_json_also_hashes_the_protected_acceptance_script():
    """Section 9: eval/acceptance is protected alongside eval/expectations; its sha256 belongs in run.json too."""
    result = fast_run()
    run_doc = json.loads((result.run_dir / "run.json").read_text())
    hashed = json.dumps(run_doc)
    spec = REPO_ROOT / "eval" / "acceptance" / "g16.spec.ts"
    assert hashlib.sha256(spec.read_bytes()).hexdigest() in hashed, "g16.spec.ts sha256 not recorded"


def test_tolerance_values_match_the_plan_exactly():
    t = json.loads((EXPECTATIONS_DIR / "tolerance.json").read_text())
    assert t["blockingRecallDropPp"] == 1
    assert t["lenientOutOfFoldEndToEndRecallDropPp"] == 2
    assert t["gateSuiteDuplicatesDeniedDropPp"] == 2
    assert t["reviewBurdenRisePp"] == 3
    assert t["alphaTargetMustStayReachable"] is True
    c = json.loads((EXPECTATIONS_DIR / "config.json").read_text())
    assert (c["alpha"], c["beta"], c["minComponents"], c["reviewBurdenMax"], c["bootstrapResamples"]) == (0.01, 0.02, 50, 0.2, 1000)


def test_end_to_end_denominator_counts_the_real_entities_of_blocking_missed_pairs():
    """Section 5: n_entities and n_components beside every pair n must be the real ones. A true pair that
    blocking missed belongs to a known entity and component; it must not borrow a neighbour's."""
    result = fast_run()
    entity_of = result.corpus.entity_of()
    dev = {r["record_id"] for r in result.corpus.records
           if result.assignment.partition_of_person(r["person_id"]) == "development"}
    true_entities = {e for rid, e in entity_of.items() if rid in dev
                     and sum(1 for r2, e2 in entity_of.items() if e2 == e and r2 in dev) >= 2}
    cell = result.numbers["recall.lenient.end_to_end"]
    assert cell["n_entities"] == len(true_entities), (cell["n_entities"], len(true_entities))


def test_compare_notes_when_baseline_and_candidate_data_differ():
    """tolerance.json: 'against the last green main run with the same seed and data, so any difference comes
    from the merge'. When the fixture hashes differ the comparison is not like for like and must say so."""
    from eval.compare import compare

    result = fast_run()
    tolerance = json.loads((EXPECTATIONS_DIR / "tolerance.json").read_text())
    metrics_a = {**result.metrics, "scorerVersion": "trained-1"}
    metrics_b = {**result.metrics, "scorerVersion": "trained-1", "fixtureHashes": {"records": "x", "truth": "y"}}
    worse = json.loads(json.dumps(result.numbers))
    worse["recall.lenient.end_to_end"]["value"] -= 0.5
    breaches, notes = compare(result.numbers, worse, tolerance, metrics_a, metrics_b)
    assert any("data" in n.lower() or "fixture" in n.lower() for n in notes + breaches), (breaches, notes)
