"""The match seam (backend.match.seam.resolve_core) on every branch, with and without W2 merged.

* W2 absent (or hidden): the stand-in scores. A ``None`` entry in ``sys.modules`` makes the import
  raise ``ModuleNotFoundError`` named exactly ``backend.core.api``, the same as a missing module.
* W2 present: the seam returns ``backend.core.api.CORE`` and never substitutes the stand-in.
* A dependency missing inside W2's code is re-raised, never replaced by different scoring.
* Against the real W2 CORE (skipped until ``backend.core.api`` exists): the routes work by
  attribute only (W2 returns its own ``CoreMatch`` and ``BlockKey``, not the seam's classes).
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import sys
import types

import pytest

from backend.match import seam
from backend.match.standin import StandInCore
from backend.tests.api.conftest import API
from contracts.models.common import Band
from contracts.models.pairs import EvidenceSnapshot

W2_MODULE = "backend.core.api"


@pytest.fixture
def clean_modules():
    saved = {k: sys.modules.pop(k) for k in list(sys.modules) if k.startswith("backend.core")}
    yield
    for k in list(sys.modules):
        if k.startswith("backend.core"):
            del sys.modules[k]
    sys.modules.update(saved)


def test_hidden_w2_module_falls_back_to_the_stand_in(monkeypatch):
    monkeypatch.setitem(sys.modules, W2_MODULE, None)
    assert isinstance(seam.resolve_core(), StandInCore)


def test_seam_picks_backend_core_api_when_importable(monkeypatch):
    sentinel = object()
    fake = types.ModuleType(W2_MODULE)
    fake.CORE = sentinel
    monkeypatch.setitem(sys.modules, W2_MODULE, fake)
    assert seam.resolve_core() is sentinel


def test_dependency_failure_inside_w2_module_is_reraised(clean_modules, monkeypatch):
    class _Package(importlib.abc.Loader):
        def create_module(self, spec):
            return None

        def exec_module(self, module):
            module.__path__ = []

    class _Raising(importlib.abc.Loader):
        def create_module(self, spec):
            return None

        def exec_module(self, module):
            raise ModuleNotFoundError("No module named 'jellyfish'", name="jellyfish")

    class _Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "backend.core":
                return importlib.machinery.ModuleSpec(fullname, _Package(), is_package=True)
            if fullname == W2_MODULE:
                return importlib.machinery.ModuleSpec(fullname, _Raising())
            return None

    monkeypatch.setattr(sys, "meta_path", [_Finder(), *sys.meta_path])
    with pytest.raises(ModuleNotFoundError) as info:
        seam.resolve_core()
    assert info.value.name == "jellyfish"


def test_routes_run_against_w2_core_by_attribute_only(client):
    """Skipped until W2 merges. Then: the seam resolves W2's CORE, its objects satisfy the seam by
    attribute, and reset -> match run -> evidence view work end to end with real scoring."""
    w2 = pytest.importorskip(W2_MODULE)
    core = seam.resolve_core()
    assert core is w2.CORE

    session = client.post(f"{API}/sessions", json={"scenarioId": "hero"}).json()
    assert session["scorerVersion"] == core.scorer_version
    records = [s["normalized"] for s in session["sources"]]
    from contracts.models.records import NormalizedRecord

    a, b = (NormalizedRecord.model_validate(r) for r in records[:2])
    keys = core.block_keys(a)
    assert all(hasattr(k, "key_type") and hasattr(k, "key_value") for k in keys)
    current = client.get(f"{API}/threshold-sets/current").json()  # whatever row is current, never a literal
    thresholds = seam.Thresholds(
        threshold_set_id=current["thresholdsId"], c_low=current["cLow"], c_high=current["cHigh"]
    )
    result = core.match(a, b, thresholds)
    Band(result.band)
    EvidenceSnapshot.model_validate(result.evidence.model_dump(mode="json"))
    assert isinstance(result.p, float) and 0.0 <= result.p <= 1.0

    run = client.post(f"{API}/match-runs")
    assert run.status_code == 201, run.text
    body = run.json()
    assert body["scorerVersion"] == core.scorer_version
    assert sum(body["bandCounts"].values()) == body["candidatePairs"]
    for pair_id in body["queuedPairIds"][:3]:
        detail = client.get(f"{API}/candidate-pairs/{pair_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["history"][0]["evidenceSnapshot"]["scorerVersion"] == core.scorer_version
