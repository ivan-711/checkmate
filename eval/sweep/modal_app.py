"""The Modal executor (ADR-012): the same ``evaluate_manifest`` mapped across containers.

Imported lazily by ``select_executor``, and only once a token is configured; nothing else loads the SDK.
The image installs from the lock file (``uv sync --frozen``) and carries the repo's four packages with the
data files the harness reads (expectations, weights, migrations, ``data/HASHES.json``). The Synthea sample
is a Volume Ivan fills once with the two archives ``data/download.py`` fetched (147 MB; the extracted sample
is 1.6 GB); the function mounts it read-only, checks each archive against ``data/HASHES.json`` and extracts
it once per container into scratch with ``download.py``'s own safe extraction. Results return as function
outputs; the Volume is never written. A container that fails or times out returns its exception, and the
executor reruns that entry on the local pool.

    uvx modal token new
    uv run modal volume create checkmate-synthea-raw
    uv run modal volume put checkmate-synthea-raw data/raw/zips /zips
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

import modal

from data.download import FILES, HASHES_PATH, extract, sha256_of
from eval.harness.run import REPO_ROOT
from eval.sweep.evaluate import evaluate_manifest
from eval.sweep.executors import EXECUTOR_MODAL, RemoteRunFailed
from eval.sweep.manifest import TIER_SYNTHEA, ManifestEntry

APP_NAME = "checkmate-eval-sweep"
PYTHON_VERSION = "3.12"
FUNCTION_TIMEOUT_SECONDS = 20 * 60  # a fast pass is ~93 s locally; a development pass can take 10 minutes
RAW_VOLUME_NAME = "checkmate-synthea-raw"
RAW_MOUNT = PurePosixPath("/data/raw")
ZIPS_SUBDIR = "zips"  # where data/download.py keeps the archives locally, mirrored on the Volume
REMOTE_RUNS_DIR = Path("/tmp/eval-runs")  # container scratch; the result record is the output, not the directory
REMOTE_RAW_DIR = Path("/tmp/raw")  # container scratch for the extracted sample
PACKAGES = ("contracts", "backend", "eval", "data")
UV_ROOT = "/.uv"
UV_IMAGE = "ghcr.io/astral-sh/uv:latest"
UV_PROJECT_FILES = ("pyproject.toml", "uv.lock")
UV_SYNC_COMMAND = f"{UV_ROOT}/uv sync --project={UV_ROOT} --no-install-workspace --compile-bytecode --frozen"
IGNORED_DIRS = frozenset(
    {
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "runs",
        "test-results",
        "playwright-report",
        "raw",
        "onc",
        "benchmark",
        "synthea",
        "captures",
    }
)


def _ignore(path: Path) -> bool:
    """Keep every source and data file the harness reads; drop installed packages, run outputs, raw data
    and anything named like an env file."""
    rel = path.relative_to(REPO_ROOT) if path.is_absolute() and path.is_relative_to(REPO_ROOT) else path
    return bool(IGNORED_DIRS & set(rel.parts)) or rel.name.startswith(".env")


class SampleUnavailable(RuntimeError):
    """The Volume does not hold the hash-checked Synthea archives; the entry falls back to the local pool."""


def prepare_raw_dir(volume_dir: Path, scratch_dir: Path, expected: Mapping[str, str]) -> Path:
    """The sample for this container: each archive on the Volume is checked against its recorded sha256 and
    extracted once (``download.py``'s marker makes a second call a no-op) into ``scratch_dir``."""
    for name, digest in expected.items():
        archive = volume_dir / ZIPS_SUBDIR / name
        if not archive.exists():
            raise SampleUnavailable(
                f"{name} is absent under {volume_dir / ZIPS_SUBDIR}; upload data/raw/zips with `modal volume put`"
            )
        actual = sha256_of(archive)
        if actual != digest:
            raise SampleUnavailable(f"{name}: sha256 {actual} differs from the recorded {digest}")
        extract(archive, scratch_dir)
    return scratch_dir


def _recorded_hashes() -> dict[str, str]:
    """``data/HASHES.json``: the sha256 ``data/download.py`` recorded for each archive it fetched."""
    hashes = json.loads(HASHES_PATH.read_text())
    return {name: hashes[name]["sha256"] for name in FILES}


def _with_locked_dependencies(base: modal.Image) -> modal.Image:
    """The same layers ``Image.uv_sync`` builds (uv binary, the project files, ``uv sync --frozen`` without the
    project, the venv first on PATH), minus its pre-build ``pyproject.toml`` check: that check uses the legacy
    ``toml`` package, which cannot parse the dev group's ``{ include-group = "train" }`` and raises IndexError."""
    image = base.dockerfile_commands(f"COPY --from={UV_IMAGE} /uv {UV_ROOT}/uv")
    for name in UV_PROJECT_FILES:
        image = image.add_local_file(REPO_ROOT / name, f"{UV_ROOT}/{name}", copy=True)
    return image.dockerfile_commands(f"RUN {UV_SYNC_COMMAND}", f"ENV PATH={UV_ROOT}/.venv/bin:$PATH")


image = _with_locked_dependencies(modal.Image.debian_slim(python_version=PYTHON_VERSION)).add_local_python_source(
    *PACKAGES, ignore=_ignore
)
raw_volume = modal.Volume.from_name(RAW_VOLUME_NAME, create_if_missing=True)
app = modal.App(APP_NAME, image=image)


@app.function(timeout=FUNCTION_TIMEOUT_SECONDS, volumes={RAW_MOUNT: raw_volume.with_mount_options(read_only=True)})
def evaluate_manifest_remote(entry: ManifestEntry) -> dict:
    os.environ["GIT_SHA"] = entry.git_sha  # no git in the container; the run manifest still records the commit
    raw = prepare_raw_dir(Path(RAW_MOUNT), REMOTE_RAW_DIR, _recorded_hashes()) if entry.tier == TIER_SYNTHEA else None
    return {**evaluate_manifest(entry, out_dir=REMOTE_RUNS_DIR, raw_dir=raw), "executor": EXECUTOR_MODAL}


def remote_map(entries: Sequence[ManifestEntry], *, raw_dir: Path | None = None) -> list[dict | BaseException]:
    """Map the entries across containers, in order; a failed or timed-out entry comes back as its exception.
    ``raw_dir`` is the local sample and is unused here: the container reads the Volume."""
    del raw_dir
    try:
        with modal.enable_output(), app.run():
            return list(evaluate_manifest_remote.map(list(entries), return_exceptions=True))
    except Exception as exc:  # the SDK's exception hierarchy is not ours; every failure must reach the fallback
        raise RemoteRunFailed(f"{type(exc).__name__}: {exc}") from exc
