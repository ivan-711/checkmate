"""The sweep manifest (ADR-012): what a sweep measures, frozen before anything runs, hashed on every run.

A sweep is a set of manifests: one entry per seed x scorer version x tier. ``SweepManifest`` is the whole
set; ``ManifestEntry`` is one cell, the unit ``evaluate_manifest`` runs. Both serialize to canonical JSON
(sorted keys, no whitespace) and hash to SHA-256 over that JSON, so the same inputs listed in any order give
the same hash, and the hash is written into every harness run directory the sweep produces.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from eval.harness.run import EXPECTATIONS_DIR, git_sha, load_json

SWEEP_VERSION = 1
TIER_SYNTHEA = "synthea"
TIER_FIXTURE = "fixture"
TIERS = (TIER_FIXTURE, TIER_SYNTHEA)
TIER_NOTE = {
    TIER_SYNTHEA: "W1's Synthea corruption corpus scored by W2's engine: the product measurement",
    TIER_FIXTURE: "the in-repo synthetic fixture scored by the harness stand-in: a self-test, never published",
}
CONFIG_FAST = "fast"
CONFIG_DEVELOPMENT = "development"
CONFIGS = (CONFIG_FAST, CONFIG_DEVELOPMENT)
SPLIT_ID_PREFIX = "heldout-"
SPLIT_ID_DIGITS = 12
UNKNOWN_GIT_SHA = "unknown"


def _canonical(doc: dict) -> str:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _require_unique(what: str, values: Sequence) -> None:
    if not values:
        raise ValueError(f"at least one {what} is required")
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {what} in {list(values)}")


def split_id(expectations_dir: Path = EXPECTATIONS_DIR) -> str:
    """The held-out split id: the protected split contract plus the seeded held-out families, hashed.
    Two sweeps with the same id scored the same partitions with the same families held out."""
    splits = (expectations_dir / "splits.json").read_bytes()
    drawn = (load_json(expectations_dir / "config.json").get("heldOutFamilies") or {}).get("drawn") or []
    digest = hashlib.sha256(splits + _canonical({"heldOutFamilies": sorted(drawn)}).encode()).hexdigest()
    return SPLIT_ID_PREFIX + digest[:SPLIT_ID_DIGITS]


@dataclass(frozen=True)
class ManifestEntry:
    """One cell of a sweep: the unit an executor runs. Carries its parent sweep's hash."""

    seed: int
    scorer_version: str
    tier: str
    split_id: str
    git_sha: str
    config: str
    sweep_sha256: str

    def __post_init__(self) -> None:
        if self.tier not in TIERS:
            raise ValueError(f"unknown tier {self.tier!r}; tiers are {TIERS}")
        if self.config not in CONFIGS:
            raise ValueError(f"unknown config {self.config!r}; configs are {CONFIGS}")

    def as_dict(self) -> dict:
        return {
            "seed": self.seed,
            "scorerVersion": self.scorer_version,
            "tier": self.tier,
            "splitId": self.split_id,
            "gitSha": self.git_sha,
            "config": self.config,
            "sweepSha256": self.sweep_sha256,
        }

    @property
    def sha256(self) -> str:
        return _sha256(_canonical(self.as_dict()))

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, doc: dict) -> ManifestEntry:
        return cls(
            seed=int(doc["seed"]),
            scorer_version=doc["scorerVersion"],
            tier=doc["tier"],
            split_id=doc["splitId"],
            git_sha=doc["gitSha"],
            config=doc["config"],
            sweep_sha256=doc["sweepSha256"],
        )

    @classmethod
    def from_json(cls, text: str) -> ManifestEntry:
        return cls.from_dict(json.loads(text))


@dataclass(frozen=True)
class SweepManifest:
    """The immutable description of a sweep. Seeds, scorer versions and tiers are stored sorted, so the hash
    does not depend on how the command line listed them."""

    seeds: tuple[int, ...]
    scorer_versions: tuple[str, ...]
    tiers: tuple[str, ...]
    split_id: str
    git_sha: str
    config: str = CONFIG_FAST
    version: int = SWEEP_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "seeds", tuple(sorted(int(s) for s in self.seeds)))
        object.__setattr__(self, "scorer_versions", tuple(sorted(self.scorer_versions)))
        object.__setattr__(self, "tiers", tuple(sorted(self.tiers)))
        _require_unique("seed", self.seeds)
        _require_unique("scorer version", self.scorer_versions)
        _require_unique("tier", self.tiers)
        unknown = [t for t in self.tiers if t not in TIERS]
        if unknown:
            raise ValueError(f"unknown tier {unknown}; tiers are {TIERS}")
        if self.config not in CONFIGS:
            raise ValueError(f"unknown config {self.config!r}; configs are {CONFIGS}")
        if not self.split_id or not self.git_sha:
            raise ValueError("split_id and git_sha are required")

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "seeds": list(self.seeds),
            "scorerVersions": list(self.scorer_versions),
            "tiers": list(self.tiers),
            "splitId": self.split_id,
            "gitSha": self.git_sha,
            "config": self.config,
        }

    @property
    def sha256(self) -> str:
        return _sha256(_canonical(self.as_dict()))

    def to_json(self) -> str:
        return json.dumps({**self.as_dict(), "sweepSha256": self.sha256}, indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, doc: dict) -> SweepManifest:
        manifest = cls(
            seeds=tuple(doc["seeds"]),
            scorer_versions=tuple(doc["scorerVersions"]),
            tiers=tuple(doc["tiers"]),
            split_id=doc["splitId"],
            git_sha=doc["gitSha"],
            config=doc.get("config", CONFIG_FAST),
            version=int(doc.get("version", SWEEP_VERSION)),
        )
        if "sweepSha256" in doc and doc["sweepSha256"] != manifest.sha256:
            raise ValueError("the manifest's sweepSha256 does not match its fields")
        return manifest

    @classmethod
    def from_json(cls, text: str) -> SweepManifest:
        return cls.from_dict(json.loads(text))

    def entries(self) -> tuple[ManifestEntry, ...]:
        """The set of manifests the sweep is: one entry per seed x scorer version x tier, in that order."""
        sweep = self.sha256
        return tuple(
            ManifestEntry(
                seed=seed,
                scorer_version=scorer,
                tier=tier,
                split_id=self.split_id,
                git_sha=self.git_sha,
                config=self.config,
                sweep_sha256=sweep,
            )
            for seed, scorer, tier in itertools.product(self.seeds, self.scorer_versions, self.tiers)
        )


def build_manifest(
    seeds: Sequence[int],
    scorer_versions: Sequence[str],
    tiers: Sequence[str],
    config: str = CONFIG_FAST,
    expectations_dir: Path = EXPECTATIONS_DIR,
) -> SweepManifest:
    """A manifest for this checkout: the current commit and the protected split."""
    return SweepManifest(
        seeds=tuple(seeds),
        scorer_versions=tuple(scorer_versions),
        tiers=tuple(tiers),
        split_id=split_id(expectations_dir),
        git_sha=git_sha() or UNKNOWN_GIT_SHA,
        config=config,
    )
