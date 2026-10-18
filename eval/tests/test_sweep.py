"""Q13 sweep (ADR-012): an immutable manifest with a stable hash, the local process pool as the
executor when no Modal token is configured, and identical numbers when the same manifest runs twice.

Everything here runs locally on the in-repo fixture tier; nothing touches Modal's cloud."""

from __future__ import annotations

import dataclasses
import importlib
import json
import math
import statistics
from pathlib import Path

import pytest

from eval.harness import standin
from eval.sweep import __main__ as cli
from eval.sweep import results as results_module
from eval.sweep.evaluate import ScorerVersionMismatch, evaluate_manifest
from eval.sweep.executors import (
    EXECUTOR_AUTO,
    EXECUTOR_LOCAL,
    EXECUTOR_MODAL,
    LocalPoolExecutor,
    ModalExecutor,
    ModalTokenMissing,
    RemoteRunFailed,
    executor_ran,
    modal_token_present,
    select_executor,
)
from eval.sweep.manifest import TIER_FIXTURE, TIER_SYNTHEA, ManifestEntry, SweepManifest, build_manifest, split_id
from eval.sweep.results import NOT_REPORTED, aggregate, interval_95, render_table, t_critical_95

TWO_SEEDS = (20261017, 99)
NO_TOKEN = (False, "no Modal token: run `uvx modal token new`")
TOKEN = (True, "Modal token found")


def fixture_manifest(seeds: tuple[int, ...] = TWO_SEEDS) -> SweepManifest:
    return SweepManifest(
        seeds=seeds,
        scorer_versions=(standin.SCORER_VERSION,),
        tiers=(TIER_FIXTURE,),
        split_id="heldout-test",
        git_sha="deadbeef",
    )


# --- manifest ---------------------------------------------------------------------------------------


def test_manifest_hash_is_stable_across_seed_order_and_a_json_round_trip():
    a = fixture_manifest((99, 20261017))
    b = fixture_manifest((20261017, 99))
    assert a == b and a.sha256 == b.sha256
    assert len(a.sha256) == 64 and int(a.sha256, 16)
    again = SweepManifest.from_json(a.to_json())
    assert again == a and again.sha256 == a.sha256
    assert json.loads(a.to_json())["sweepSha256"] == a.sha256


def test_manifest_hash_changes_with_every_field():
    base = fixture_manifest()
    variants = (
        dataclasses.replace(base, seeds=(20261017,)),
        dataclasses.replace(base, scorer_versions=("other-1",)),
        dataclasses.replace(base, tiers=(TIER_FIXTURE, TIER_SYNTHEA)),
        dataclasses.replace(base, split_id="heldout-other"),
        dataclasses.replace(base, git_sha="cafebabe"),
        dataclasses.replace(base, config="development"),
    )
    hashes = {m.sha256 for m in variants} | {base.sha256}
    assert len(hashes) == len(variants) + 1


def test_manifest_is_immutable_and_validated():
    m = fixture_manifest()
    with pytest.raises(dataclasses.FrozenInstanceError):
        m.seeds = (1,)  # type: ignore[misc]
    with pytest.raises(ValueError, match="tier"):
        dataclasses.replace(m, tiers=("onc-tier-9",))
    with pytest.raises(ValueError, match="seed"):
        dataclasses.replace(m, seeds=())
    with pytest.raises(ValueError, match="seed"):
        dataclasses.replace(m, seeds=(1, 1))
    with pytest.raises(ValueError, match="config"):
        dataclasses.replace(m, config="overnight")


def test_entries_are_the_product_of_seeds_scorers_and_tiers_and_carry_the_sweep_hash():
    m = dataclasses.replace(fixture_manifest(), tiers=(TIER_FIXTURE, TIER_SYNTHEA))
    entries = m.entries()
    assert len(entries) == 2 * 1 * 2
    assert {(e.seed, e.scorer_version, e.tier) for e in entries} == {
        (s, standin.SCORER_VERSION, t) for s in TWO_SEEDS for t in (TIER_FIXTURE, TIER_SYNTHEA)
    }
    assert all(isinstance(e, ManifestEntry) and e.sweep_sha256 == m.sha256 for e in entries)
    assert all(e.split_id == m.split_id and e.git_sha == m.git_sha and e.config == m.config for e in entries)
    assert len({e.sha256 for e in entries}) == len(entries)
    assert ManifestEntry.from_json(entries[0].to_json()) == entries[0]


def test_split_id_comes_from_the_protected_split_and_held_out_families(tmp_path: Path):
    real = split_id()
    assert real.startswith("heldout-") and real == split_id()
    expectations = Path(__file__).parents[1] / "expectations"
    (tmp_path / "splits.json").write_bytes((expectations / "splits.json").read_bytes())
    cfg = json.loads((expectations / "config.json").read_text())
    cfg["heldOutFamilies"]["drawn"] = ["S7"]
    (tmp_path / "config.json").write_text(json.dumps(cfg))
    assert split_id(tmp_path) != real


def test_build_manifest_records_the_commit_and_the_split():
    m = build_manifest(seeds=TWO_SEEDS, scorer_versions=(standin.SCORER_VERSION,), tiers=(TIER_FIXTURE,))
    assert m.split_id == split_id()
    assert len(m.git_sha) == 40 and int(m.git_sha, 16)
    assert m.config == "fast" and m.seeds == tuple(sorted(TWO_SEEDS))


# --- executor choice --------------------------------------------------------------------------------


def test_executor_picks_the_local_pool_with_no_token():
    executor, reason = select_executor(EXECUTOR_AUTO, token_present=lambda: NO_TOKEN)
    assert isinstance(executor, LocalPoolExecutor) and executor.name == EXECUTOR_LOCAL
    assert "no Modal token" in reason
    executor, _ = select_executor(EXECUTOR_LOCAL, token_present=lambda: TOKEN)
    assert isinstance(executor, LocalPoolExecutor)


def test_explicit_modal_without_a_token_is_a_clear_error():
    with pytest.raises(ModalTokenMissing, match="uvx modal token new"):
        select_executor(EXECUTOR_MODAL, token_present=lambda: NO_TOKEN)
    with pytest.raises(ValueError, match="executor"):
        select_executor("cloud", token_present=lambda: TOKEN)


def test_real_token_check_reads_modal_credentials_without_printing_them(monkeypatch: pytest.MonkeyPatch):
    import modal.config

    monkeypatch.setenv("MODAL_TOKEN_ID", "ak-test-only")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "as-test-only")
    present, reason = modal_token_present()
    assert present is True and "ak-test-only" not in reason and "as-test-only" not in reason
    monkeypatch.delenv("MODAL_TOKEN_ID")
    monkeypatch.delenv("MODAL_TOKEN_SECRET")
    if Path(modal.config.user_config_path).exists():
        pytest.skip("a Modal profile file exists on this machine; the no-token path is covered by injection")
    present, reason = modal_token_present()
    assert present is False and "uvx modal token new" in reason
    executor, _ = select_executor(EXECUTOR_AUTO)
    assert isinstance(executor, LocalPoolExecutor)


# --- evaluation ------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def two_seed_runs(tmp_path_factory: pytest.TempPathFactory) -> tuple[list[dict], list[dict], Path]:
    out = tmp_path_factory.mktemp("sweep")
    executor = LocalPoolExecutor(workers=2)
    manifest = fixture_manifest()
    first = executor.run(manifest.entries(), out_dir=out / "first")
    second = executor.run(manifest.entries(), out_dir=out / "second")
    return first, second, out


def test_two_seed_local_run_gives_two_run_dirs_and_identical_numbers_run_twice(two_seed_runs):
    first, second, out = two_seed_runs
    assert len(first) == len(second) == 2
    assert [r["entry"]["seed"] for r in first] == sorted(TWO_SEEDS)
    run_dirs = {Path(r["runDir"]) for r in first}
    assert len(run_dirs) == 2 and all((d / "manifest.json").exists() and d.parent == out / "first" for d in run_dirs)
    assert [r["numbers"] for r in first] == [r["numbers"] for r in second]
    assert first[0]["numbers"] != first[1]["numbers"]
    assert first[0]["runId"] != second[0]["runId"]


def test_entry_results_separate_latency_and_record_the_sweep_on_the_harness_manifest(two_seed_runs):
    first, _, _ = two_seed_runs
    for r in first:
        assert not any(k.startswith("latency.") for k in r["numbers"])
        assert {"latency.match.p50_ms", "latency.match.p95_ms"} <= set(r["latency"])
        assert r["invariants"]["idempotent_ingest"] is True
        assert r["thresholds"]["cLow"] <= r["thresholds"]["cHigh"]
        assert r["elapsedSeconds"] > 0 and r["executor"] == EXECUTOR_LOCAL
        written = json.loads((Path(r["runDir"]) / "manifest.json").read_text())
        assert written["sweep"] == {
            "sweepSha256": r["sweepSha256"],
            "entrySha256": r["entrySha256"],
            "tier": TIER_FIXTURE,
            "splitId": "heldout-test",
        }
        assert r["entrySha256"] == ManifestEntry.from_json(json.dumps(r["entry"])).sha256
        assert r["sweepSha256"] == fixture_manifest().sha256


def test_evaluate_manifest_refuses_a_scorer_version_the_engine_does_not_report(tmp_path: Path):
    entry = dataclasses.replace(fixture_manifest().entries()[0], scorer_version="someone-else-1")
    with pytest.raises(ScorerVersionMismatch, match="someone-else-1"):
        evaluate_manifest(entry, out_dir=tmp_path)


# --- results table ---------------------------------------------------------------------------------


T_975_DF1 = 12.706204736174694  # the exact two-sided 95% Student t value for one degree of freedom


def test_interval_95_is_a_t_interval_across_seeds():
    cell = interval_95([0.5, 0.7])
    half = T_975_DF1 * statistics.stdev([0.5, 0.7]) / math.sqrt(2)
    assert cell["n"] == 2 and cell["mean"] == pytest.approx(0.6)
    assert cell["ci95"] == pytest.approx([0.6 - half, 0.6 + half])
    assert cell["values"] == [0.5, 0.7]
    single = interval_95([0.5])
    assert single["n"] == 1 and single["mean"] == 0.5 and single["sd"] is None and single["ci95"] is None


def test_results_table_has_mean_and_interval_per_metric_across_seeds(two_seed_runs):
    first, _, _ = two_seed_runs
    table = aggregate(first)
    assert len(table["cells"]) == 1
    cell = table["cells"][0]
    assert cell["scorerVersion"] == standin.SCORER_VERSION and cell["tier"] == TIER_FIXTURE
    assert cell["seeds"] == sorted(TWO_SEEDS)
    recall = cell["metrics"]["recall.lenient.end_to_end"]
    assert recall["n"] == 2 and len(recall["values"]) == 2 and recall["ci95"] is not None
    assert recall["ci95"][0] <= recall["mean"] <= recall["ci95"][1]
    assert "thresholds.operating_point" not in cell["metrics"]  # not numeric
    assert not any(k.startswith("latency.") for k in cell["metrics"])
    text = render_table(table)
    assert "LENIENT recall" in text and "n seeds" in text and standin.SCORER_VERSION in text
    assert "clipped to [0, 1]" in text and "clipped to [0, 1]" in table["note"]


# --- the t critical value -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("degrees_of_freedom", "published"),
    [(1, 12.706), (2, 4.303), (4, 2.776), (10, 2.228), (30, 2.042), (60, 2.000)],
)
def test_t_critical_95_matches_the_published_table_to_three_decimals(degrees_of_freedom: int, published: float):
    assert t_critical_95(degrees_of_freedom) == pytest.approx(published, abs=5e-4)
    with pytest.raises(ValueError, match="degree"):
        t_critical_95(0)


def test_the_hand_typed_t_table_is_gone_and_scipy_supplies_the_value():
    assert not hasattr(results_module, "T_CRITICAL_95")
    from scipy.stats import t

    assert t_critical_95(7) == pytest.approx(float(t.ppf(0.975, 7)), abs=0)


# --- what the table may print --------------------------------------------------------------------------


def rate_cell(value: float, *, n_pairs: int = 400, n_components: int = 250, do_not_read: bool = False) -> dict:
    """A harness ``rate()`` cell: value, support, the harness's own interval and flags."""
    return {
        "value": value,
        "n_pairs": n_pairs,
        "n_entities": n_components,
        "n_components": n_components,
        "ci95": [max(0.0, value - 0.01), min(1.0, value + 0.01)],
        "low_support": n_components < 50,
        "do_not_read": do_not_read,
        "zero_events": False,
    }


def fake_result(seed: int, numbers: dict, *, executor: str = EXECUTOR_LOCAL, **extra) -> dict:
    return {
        "entry": {"seed": seed, "scorerVersion": "handset-1", "tier": TIER_SYNTHEA},
        "numbers": numbers,
        "runId": f"run-{seed}",
        "elapsedSeconds": 1.0,
        "executor": executor,
        **extra,
    }


FIVE_SEEDS = (20261017, 20261018, 20261019, 20261020, 20261021)
# the per-seed values of the five-seed development pass published in the README (scorer handset-1)
PUBLISHED_FIVE_SEED = {
    "band.review.precision": ([0.883991, 0.947507, 0.892421, 0.869976, 0.912195], 0.901, (0.864, 0.939)),
    "recall.lenient.end_to_end": ([0.883065, 0.875274, 0.903297, 0.884368, 0.899142], 0.889, (0.874, 0.904)),
    "review_burden": ([0.728041, 0.7666, 0.756007, 0.759425, 0.723104], 0.747, (0.722, 0.771)),
    "blocking.recall": ([0.929435, 0.910284, 0.936264, 0.922912, 0.927039], 0.925, (0.913, 0.937)),
}


def test_the_five_seed_table_reproduces_the_published_numbers():
    results = [
        fake_result(seed, {key: rate_cell(values[i]) for key, (values, _, _) in PUBLISHED_FIVE_SEED.items()})
        for i, seed in enumerate(FIVE_SEEDS)
    ]
    metrics = aggregate(results)["cells"][0]["metrics"]
    for key, (_, mean, (low, high)) in PUBLISHED_FIVE_SEED.items():
        assert metrics[key]["reported"] is True and metrics[key]["n"] == 5
        assert round(metrics[key]["mean"], 3) == mean, key
        assert [round(x, 3) for x in metrics[key]["ci95"]] == [low, high], key
    # the first run of this table, which used the hand-typed t value 2.776: unrounded, within 1e-4
    assert metrics["band.review.precision"]["mean"] == pytest.approx(0.9012180000000001, abs=1e-4)
    assert metrics["band.review.precision"]["ci95"] == pytest.approx([0.8639048766528894, 0.9385311233471108], abs=1e-4)
    text = render_table(aggregate(results))
    assert "| REVIEW precision | 0.901 | [0.864, 0.939] |" in text
    assert "| Blocking recall | 0.925 | [0.913, 0.937] |" in text


def test_a_metric_flagged_do_not_read_on_any_seed_is_not_reported():
    flagged_on_some = [False, True, True, True, False]  # KEEP_SEPARATE precision in the five-seed pass
    results = [
        fake_result(
            seed,
            {
                "band.auto_link.precision": rate_cell(1.0, n_pairs=45, n_components=40, do_not_read=True),
                "band.keep_separate.precision": rate_cell(0.314159, do_not_read=flagged_on_some[i]),
                "band.review.precision": rate_cell(0.9),
            },
        )
        for i, seed in enumerate(FIVE_SEEDS)
    ]
    table = aggregate(results)
    metrics = table["cells"][0]["metrics"]
    for key in ("band.auto_link.precision", "band.keep_separate.precision"):
        assert metrics[key]["reported"] is False and metrics[key]["reason"] == NOT_REPORTED
        assert not {"mean", "sd", "ci95", "values", "n"} & set(metrics[key]), key
    assert metrics["band.keep_separate.precision"]["seedsBelowFloor"] == [FIVE_SEEDS[i] for i in (1, 2, 3)]
    assert metrics["band.review.precision"]["reported"] is True
    text = render_table(table)
    assert f"| AUTO_LINK precision | {NOT_REPORTED} | n/a | n/a |" in text
    assert f"| KEEP_SEPARATE precision | {NOT_REPORTED} | n/a | n/a |" in text
    assert "0.314" not in text and "0.314159" not in json.dumps(table)


@pytest.mark.parametrize(
    ("n_pairs", "n_components", "reported"),
    [(100, 30, True), (99, 30, False), (100, 29, False), (57, 44, False)],
)
def test_a_cell_below_the_harness_floor_is_not_reported_even_without_a_flag(
    n_pairs: int, n_components: int, reported: bool
):
    """Count cells (``band.auto_link.count``) carry support but not the flag; the floor is the harness's own."""
    count = {"value": float(n_pairs), "n_pairs": n_pairs, "n_entities": n_components, "n_components": n_components}
    metrics = aggregate([fake_result(seed, {"band.auto_link.count": dict(count)}) for seed in (1, 2)])["cells"][0][
        "metrics"
    ]
    assert metrics["band.auto_link.count"]["reported"] is reported


def test_rate_intervals_are_clipped_to_the_unit_range_and_other_numbers_are_not():
    seeds = (1, 2)
    per_seed = {
        "recall.lenient.end_to_end": [0.9, 1.0],  # the t interval runs above 1
        "review_burden": [0.0, 0.1],  # and below 0
        "blocking.reduction_ratio": [0.9996, 0.9998],  # a ratio with no ci95 of its own
    }
    results = []
    for i, seed in enumerate(seeds):
        numbers = {key: rate_cell(values[i]) for key, values in per_seed.items() if key != "blocking.reduction_ratio"}
        numbers["blocking.reduction_ratio"] = {"value": per_seed["blocking.reduction_ratio"][i], "n_blocked": 1, "N": 9}
        numbers["thresholds.c_high"] = {"value": 4.0 + i, "thresholds_id": "x"}
        results.append(fake_result(seed, numbers))
    table = aggregate(results)
    metrics = table["cells"][0]["metrics"]
    assert metrics["recall.lenient.end_to_end"]["ci95"][1] == 1.0 and metrics["recall.lenient.end_to_end"]["clipped"]
    assert metrics["recall.lenient.end_to_end"]["ci95"][0] == pytest.approx(0.95 - 0.635, abs=1e-3)
    assert metrics["review_burden"]["ci95"][0] == 0.0 and metrics["review_burden"]["clipped"]
    assert metrics["blocking.reduction_ratio"]["ci95"][1] == 1.0 and metrics["blocking.reduction_ratio"]["rate"]
    for key in per_seed:
        low, high = metrics[key]["ci95"]
        assert 0.0 <= low <= metrics[key]["mean"] <= high <= 1.0, key
    unclipped = metrics["thresholds.c_high"]  # a raw-score cutoff, not a rate
    assert unclipped["rate"] is False and unclipped["clipped"] is False and unclipped["ci95"][1] > 1.0
    assert "clipped to [0, 1]" in table["note"] and "clipped to [0, 1]" in render_table(table)


def test_the_caption_states_the_floor_the_harness_uses():
    from eval.harness.metrics import DO_NOT_READ_COMPONENTS, DO_NOT_READ_PAIRS

    text = render_table(aggregate([fake_result(1, {"band.review.precision": rate_cell(0.9)})]))
    assert f"{DO_NOT_READ_COMPONENTS} components" in text and f"{DO_NOT_READ_PAIRS} pairs" in text
    assert "not reported" in text


# --- Modal executor fallback (no cloud) --------------------------------------------------------------


def test_modal_executor_reruns_failed_entries_on_the_local_pool(tmp_path: Path):
    entries = fixture_manifest().entries()

    def remote_map(batch, *, raw_dir):
        return [
            RuntimeError("container stalled"),
            {**evaluate_manifest(batch[1], out_dir=tmp_path / "remote"), "executor": EXECUTOR_MODAL},
        ]

    executor = ModalExecutor(remote_map=remote_map, fallback=LocalPoolExecutor(workers=1))
    results = executor.run(entries, out_dir=tmp_path / "local")
    assert [r["entry"]["seed"] for r in results] == [e.seed for e in entries]
    assert results[0]["executor"] == EXECUTOR_LOCAL and "container stalled" in results[0]["fallbackReason"]
    assert results[1]["executor"] == EXECUTOR_MODAL and "fallbackReason" not in results[1]


def test_modal_executor_reruns_everything_locally_when_the_app_fails(tmp_path: Path):
    entries = fixture_manifest().entries()

    def remote_map(batch, *, raw_dir):
        raise RemoteRunFailed("no route to modal")

    executor = ModalExecutor(remote_map=remote_map, fallback=LocalPoolExecutor(workers=1))
    results = executor.run(entries, out_dir=tmp_path)
    assert len(results) == 2 and all(r["executor"] == EXECUTOR_LOCAL for r in results)
    assert all("no route to modal" in r["fallbackReason"] for r in results)


def test_modal_app_defines_the_remote_function_without_touching_the_cloud():
    modal_app = pytest.importorskip("eval.sweep.modal_app")
    assert modal_app.app.name == modal_app.APP_NAME == "checkmate-eval-sweep"
    assert callable(modal_app.remote_map) and modal_app.evaluate_manifest_remote is not None
    assert modal_app.FUNCTION_TIMEOUT_SECONDS >= 600  # a fast pass is ~93 s; a development pass can take 10 min


def test_modal_image_installs_the_lock_without_image_uv_sync(monkeypatch: pytest.MonkeyPatch):
    # Image.uv_sync parses pyproject.toml with the legacy `toml` package at app start, which raises IndexError on
    # the dev group's `{ include-group = "train" }`; the first real Modal run failed there before any container.
    modal = pytest.importorskip("modal")
    modal_app = pytest.importorskip("eval.sweep.modal_app")

    def refuse(*args, **kwargs):
        raise AssertionError("Image.uv_sync cannot parse this pyproject.toml")

    monkeypatch.setattr(modal.Image, "uv_sync", refuse)
    modal_app = importlib.reload(modal_app)
    assert "--frozen" in modal_app.UV_SYNC_COMMAND and "--no-install-workspace" in modal_app.UV_SYNC_COMMAND
    assert all((modal_app.REPO_ROOT / name).is_file() for name in modal_app.UV_PROJECT_FILES)


# --- command line -----------------------------------------------------------------------------------


def test_cli_dry_run_prints_the_manifest_and_its_hash(capsys: pytest.CaptureFixture[str]):
    code = cli.main(
        ["--seeds", "99", "20261017", "--tiers", TIER_FIXTURE, "--scorer-versions", standin.SCORER_VERSION, "--dry-run"]
    )
    assert code == 0
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert doc["manifest"]["seeds"] == [99, 20261017] and len(doc["sweepSha256"]) == 64
    assert len(doc["entries"]) == 2


def test_cli_local_two_seed_sweep_writes_the_sweep_file_and_the_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    code = cli.main(
        [
            "--seeds",
            "99",
            "20261017",
            "--tiers",
            TIER_FIXTURE,
            "--scorer-versions",
            standin.SCORER_VERSION,
            "--executor",
            EXECUTOR_LOCAL,
            "--out",
            str(tmp_path),
            "--workers",
            "2",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "LENIENT recall" in out and "executor: local" in out
    sweeps = list((tmp_path / "sweeps").glob("*/sweep.json"))
    assert len(sweeps) == 1
    doc = json.loads(sweeps[0].read_text())
    assert doc["sweepSha256"] == doc["manifest"]["sweepSha256"] and doc["executor"] == EXECUTOR_LOCAL
    assert len(doc["entries"]) == 2 and doc["table"]["cells"][0]["seeds"] == [99, 20261017]
    assert doc["elapsedSeconds"] > 0


def test_cli_modal_without_a_token_exits_with_a_clear_message(capsys: pytest.CaptureFixture[str]):
    code = cli.main(
        [
            "--seeds",
            "99",
            "--tiers",
            TIER_FIXTURE,
            "--scorer-versions",
            standin.SCORER_VERSION,
            "--executor",
            EXECUTOR_MODAL,
        ],
        token_present=lambda: NO_TOKEN,
    )
    assert code == cli.EXIT_TOKEN_MISSING
    assert "uvx modal token new" in capsys.readouterr().err


def test_sweep_modules_never_load_the_env_file():
    sources = list((Path(__file__).parents[1] / "sweep").rglob("*.py"))
    assert sources and not any("dotenv" in p.read_text() for p in sources)


def test_remote_raw_dir_extracts_the_volume_archives_once_and_checks_their_hashes(tmp_path: Path):
    import hashlib
    import zipfile

    modal_app = pytest.importorskip("eval.sweep.modal_app")
    zips = tmp_path / "volume" / "zips"
    zips.mkdir(parents=True)
    archive = zips / "sample.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("fhir/a.json", "{}")
        zf.writestr("csv/patients.csv", "Id\n")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    scratch = tmp_path / "scratch"
    raw = modal_app.prepare_raw_dir(tmp_path / "volume", scratch, {"sample.zip": digest})
    assert raw == scratch and (scratch / "fhir" / "a.json").exists() and (scratch / "csv" / "patients.csv").exists()
    assert modal_app.prepare_raw_dir(tmp_path / "volume", scratch, {"sample.zip": digest}) == scratch
    with pytest.raises(modal_app.SampleUnavailable, match="sample.zip"):
        modal_app.prepare_raw_dir(tmp_path / "volume", tmp_path / "other", {"sample.zip": "0" * 64})
    with pytest.raises(modal_app.SampleUnavailable, match="missing.zip"):
        modal_app.prepare_raw_dir(tmp_path / "volume", tmp_path / "other", {"missing.zip": digest})
    assert not (tmp_path / "volume" / "fhir").exists()  # the Volume is never written


# --- the executor that actually ran ----------------------------------------------------------------


def test_executor_ran_names_the_executor_that_produced_the_results():
    local = fake_result(1, {})
    remote = fake_result(2, {}, executor=EXECUTOR_MODAL)
    fell_back = fake_result(3, {}, fallbackFrom=EXECUTOR_MODAL, fallbackReason="RuntimeError: stalled")
    assert executor_ran([local, local]) == "local"
    assert executor_ran([remote, remote]) == "modal"
    assert executor_ran([fell_back, fell_back]) == "local (fallback from modal)"
    assert executor_ran([remote, fell_back]) == "local + modal (1 of 2 entries fell back from modal)"


def stub_executor(name: str, results: list[dict]):
    class Stub:
        def run(self, entries, *, out_dir=None, raw_dir=None):
            return results

    stub = Stub()
    stub.name = name  # type: ignore[attr-defined]
    return stub


def test_cli_records_the_executor_that_ran_when_every_seed_fell_back(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    def remote_map(batch, *, raw_dir):
        raise RemoteRunFailed("no route to modal")

    modal_with_fallback = ModalExecutor(remote_map=remote_map, fallback=LocalPoolExecutor(workers=2))
    monkeypatch.setattr(cli, "select_executor", lambda name, **kwargs: (modal_with_fallback, "Modal: test token"))
    code = cli.main(
        ["--seeds", "99", "20261017", "--tiers", TIER_FIXTURE, "--scorer-versions", standin.SCORER_VERSION]
        + ["--executor", EXECUTOR_MODAL, "--out", str(tmp_path)]
    )
    assert code == 0
    out = capsys.readouterr().out
    doc = json.loads(next((tmp_path / "sweeps").glob("*/sweep.json")).read_text())
    assert doc["executor"] == "local (fallback from modal)" and doc["executorRequested"] == EXECUTOR_MODAL
    assert all(e["executor"] == EXECUTOR_LOCAL and e["fallbackFrom"] == EXECUTOR_MODAL for e in doc["entries"])
    assert "ran on: local (fallback from modal)" in out


def test_cli_never_prints_or_tabulates_a_flagged_metric_but_keeps_the_per_seed_entries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    flagged = 0.987654
    results = [
        fake_result(
            seed,
            {
                "band.auto_link.precision": rate_cell(flagged, n_pairs=45, n_components=40, do_not_read=True),
                "band.review.precision": rate_cell(0.7),
            },
        )
        for seed in (1, 2)
    ]
    monkeypatch.setattr(cli, "select_executor", lambda name, **kwargs: (stub_executor("local", results), "stub"))
    code = cli.main(
        ["--seeds", "1", "2", "--tiers", TIER_FIXTURE, "--scorer-versions", standin.SCORER_VERSION]
        + ["--executor", EXECUTOR_LOCAL, "--out", str(tmp_path)]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert f"| AUTO_LINK precision | {NOT_REPORTED} | n/a | n/a |" in out and "0.988" not in out
    doc = json.loads(next((tmp_path / "sweeps").glob("*/sweep.json")).read_text())
    assert "0.987654" not in json.dumps(doc["table"])
    stored = [e["numbers"]["band.auto_link.precision"] for e in doc["entries"]]  # as the harness itself stores them
    assert [c["value"] for c in stored] == [flagged, flagged] and all(c["do_not_read"] for c in stored)
