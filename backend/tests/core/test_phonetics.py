import builtins
import importlib
import importlib.util

import pytest

import backend.core.phonetics as phonetics_module
from backend.core.phonetics import PHONETICS_LIBRARY, double_metaphone, phonetic_codes_match


def test_first_library_in_the_mandated_order_is_the_pick():
    assert PHONETICS_LIBRARY == "metaphone"


def test_codes_match_across_spelling_variants_and_empty_is_empty():
    assert phonetic_codes_match("Garcia", "Garsia")
    assert double_metaphone("123") == ("", "")
    assert not phonetic_codes_match("Smith", "Lopez")


# phonetics 1.0.5 is only installed when metaphone 0.6 cannot be, so its presence decides the next pick.
_PHONETICS_INSTALLED = importlib.util.find_spec("phonetics") is not None


@pytest.mark.parametrize(
    "blocked,expected",
    [({"metaphone"}, "phonetics" if _PHONETICS_INSTALLED else "jellyfish"), ({"metaphone", "phonetics"}, "jellyfish")],
)
def test_fallbacks_follow_the_install_order(monkeypatch, blocked, expected):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.split(".")[0] in blocked:
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    library, fn = phonetics_module._pick_library()
    assert library == expected
    assert fn("Garcia")[0]
    monkeypatch.undo()
    importlib.reload(phonetics_module)
