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
from eval.sweep.evaluate import ScorerVersionMismatch, evaluate_manifest
from eval.sweep.executors import (
    EXECUTOR_AUTO,
    EXECUTOR_LOCAL,
    EXECUTOR_MODAL,
    LocalPoolExecutor,
    ModalExecutor,
    ModalTokenMissing,
    RemoteRunFailed,
    modal_token_present,
    select_executor,
)
from eval.sweep.manifest import TIER_FIXTURE, TIER_SYNTHEA, ManifestEntry, SweepManifest, build_manifest, split_id
from eval.sweep.results import T_CRITICAL_95, aggregate, interval_95, render_table

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


def test_interval_95_is_a_t_interval_across_seeds():
    cell = interval_95([0.5, 0.7])
    half = T_CRITICAL_95[1] * statistics.stdev([0.5, 0.7]) / math.sqrt(2)
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
    assert "not clipped" in text and "not clipped" in table["note"]


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
