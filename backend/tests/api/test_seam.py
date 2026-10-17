"""Codex finding 5: the stand-in scorer substitutes only when W2's module is absent; a
dependency failure inside it is re-raised, never silently replaced by different scoring."""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import sys

import pytest

from backend.match import seam
from backend.match.standin import StandInCore

W2_MODULE = "backend.core.api"


class _Raising(importlib.abc.Loader):
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        raise self.exc


class _Finder(importlib.abc.MetaPathFinder):
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    def find_spec(self, fullname, path=None, target=None):
        if fullname == W2_MODULE:
            return importlib.machinery.ModuleSpec(fullname, _Raising(self.exc))
        if fullname == "backend.core":
            return importlib.machinery.ModuleSpec(fullname, _Raising(None), is_package=True)
        return None


@pytest.fixture
def clean_modules():
    saved = {k: sys.modules.pop(k) for k in list(sys.modules) if k.startswith("backend.core")}
    yield
    for k in list(sys.modules):
        if k.startswith("backend.core"):
            del sys.modules[k]
    sys.modules.update(saved)


def test_absent_w2_module_falls_back_to_the_stand_in(clean_modules):
    assert isinstance(seam.resolve_core(), StandInCore)


def test_dependency_failure_inside_w2_module_is_reraised(clean_modules, monkeypatch):
    class _Package(importlib.abc.Loader):
        def create_module(self, spec):
            return None

        def exec_module(self, module):
            module.__path__ = []

    class _Finder2(_Finder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "backend.core":
                return importlib.machinery.ModuleSpec(fullname, _Package(), is_package=True)
            return super().find_spec(fullname, path, target)

    missing_dep = ModuleNotFoundError("No module named 'jellyfish'", name="jellyfish")
    monkeypatch.setattr(sys, "meta_path", [_Finder2(missing_dep), *sys.meta_path])
    with pytest.raises(ModuleNotFoundError) as info:
        seam.resolve_core()
    assert info.value.name == "jellyfish"
