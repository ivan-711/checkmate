"""Executors: who runs ``evaluate_manifest`` over a sweep's entries.

``LocalPoolExecutor`` is the fallback and the reference: a process pool on this machine calling the identical
function. ``ModalExecutor`` maps the same function across Modal containers and reruns any entry that fails or
times out on the local pool, so a sweep always ends in one results table. ``select_executor`` picks by name:
``local`` is always the pool, ``modal`` is the cloud (a clear error without a token), ``auto`` is the cloud
when a token is configured and the pool otherwise.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from eval.sweep.evaluate import evaluate_manifest
from eval.sweep.manifest import ManifestEntry

EXECUTOR_LOCAL = "local"
EXECUTOR_MODAL = "modal"
EXECUTOR_AUTO = "auto"
EXECUTORS = (EXECUTOR_LOCAL, EXECUTOR_MODAL, EXECUTOR_AUTO)
TOKEN_HELP = (
    "no Modal token: run `uvx modal token new` (writes ~/.modal.toml) or set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET"
)
DEFAULT_WORKERS = os.cpu_count() or 1

TokenCheck = Callable[[], tuple[bool, str]]
"""Whether Modal credentials are configured, and why (never the credentials themselves)."""
RemoteMap = Callable[..., Sequence[dict | BaseException]]
"""``remote_map(entries, *, raw_dir)``: one result per entry, in order; a failed entry is its exception.
Raises ``RemoteRunFailed`` when the run could not start at all."""


class ModalTokenMissing(RuntimeError):
    """``--executor modal`` was asked for and no token is configured."""


class RemoteRunFailed(RuntimeError):
    """The remote app did not run at all (token, network, image build): every entry falls back to the pool."""


def modal_token_present() -> tuple[bool, str]:
    """Modal's own credential resolution (environment first, then the active ~/.modal.toml profile).
    The values are never returned, printed or logged."""
    try:
        from modal.config import config  # lazy: a dev-group dependency the local pool never needs
    except ImportError:
        return False, "the modal package is not installed (`uv sync --frozen` installs the dev group)"
    if config.get("token_id") and config.get("token_secret"):
        return True, "Modal token found (environment or the active ~/.modal.toml profile)"
    return False, TOKEN_HELP


def _evaluate(job: tuple[ManifestEntry, Path | None, Path | None]) -> dict:
    entry, out_dir, raw_dir = job
    return {**evaluate_manifest(entry, out_dir=out_dir, raw_dir=raw_dir), "executor": EXECUTOR_LOCAL}


@dataclass(frozen=True)
class LocalPoolExecutor:
    """A process pool on this machine; results come back in entry order."""

    workers: int | None = None
    name: ClassVar[str] = EXECUTOR_LOCAL

    def run(
        self, entries: Sequence[ManifestEntry], *, out_dir: Path | None = None, raw_dir: Path | None = None
    ) -> list[dict]:
        jobs = [(entry, out_dir, raw_dir) for entry in entries]
        if not jobs:
            return []
        workers = max(1, min(self.workers or DEFAULT_WORKERS, len(jobs)))
        with ProcessPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(_evaluate, jobs))


@dataclass(frozen=True)
class ModalExecutor:
    """Modal containers, with the local pool behind them: an entry that fails or times out remotely, or a
    whole run that cannot start (token, network, image), is rerun locally and says so in its result."""

    remote_map: RemoteMap
    fallback: LocalPoolExecutor = field(default_factory=LocalPoolExecutor)
    name: ClassVar[str] = EXECUTOR_MODAL

    def run(
        self, entries: Sequence[ManifestEntry], *, out_dir: Path | None = None, raw_dir: Path | None = None
    ) -> list[dict]:
        entries = list(entries)
        try:
            remote = list(self.remote_map(entries, raw_dir=raw_dir))
        except RemoteRunFailed as exc:
            remote = [exc] * len(entries)
        if len(remote) != len(entries):
            raise RuntimeError(f"Modal returned {len(remote)} results for {len(entries)} entries")
        failed = [(i, entry, r) for i, (entry, r) in enumerate(zip(entries, remote)) if isinstance(r, BaseException)]
        merged: list[dict | None] = [None if isinstance(r, BaseException) else r for r in remote]
        if failed:
            rerun = self.fallback.run([entry for _, entry, _ in failed], out_dir=out_dir, raw_dir=raw_dir)
            for (i, _, exc), result in zip(failed, rerun):
                merged[i] = {**result, "fallbackFrom": EXECUTOR_MODAL, "fallbackReason": f"{type(exc).__name__}: {exc}"}
        return [r for r in merged if r is not None]


def executor_ran(results: Sequence[dict]) -> str:
    """The executor that actually produced the results, which is not always the one asked for: an entry that
    fell back to the local pool says so (``fallbackFrom``), and the sweep file must say so too."""
    ran = " + ".join(sorted({r["executor"] for r in results}))
    fell_back = [r for r in results if r.get("fallbackFrom")]
    if not fell_back:
        return ran
    origin = " + ".join(sorted({r["fallbackFrom"] for r in fell_back}))
    if len(fell_back) == len(results):
        return f"{ran} (fallback from {origin})"
    return f"{ran} ({len(fell_back)} of {len(results)} entries fell back from {origin})"


def select_executor(
    name: str, *, token_present: TokenCheck = modal_token_present, workers: int | None = None
) -> tuple[LocalPoolExecutor | ModalExecutor, str]:
    """The executor for ``name`` and one line saying why."""
    if name not in EXECUTORS:
        raise ValueError(f"unknown executor {name!r}; choose one of {EXECUTORS}")
    if name == EXECUTOR_LOCAL:
        return LocalPoolExecutor(workers=workers), "local process pool as requested"
    present, reason = token_present()
    if not present:
        if name == EXECUTOR_MODAL:
            raise ModalTokenMissing(reason)
        return LocalPoolExecutor(workers=workers), f"local process pool: {reason}"
    from eval.sweep import modal_app  # lazy: the only place the Modal SDK is loaded

    return ModalExecutor(
        remote_map=modal_app.remote_map, fallback=LocalPoolExecutor(workers=workers)
    ), f"Modal: {reason}"
