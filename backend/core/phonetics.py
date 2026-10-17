"""Double Metaphone behind one function, from the first library that installs.

Install order is fixed by ADR-001 and the build brief: ``metaphone`` 0.6, then ``phonetics``
1.0.5, then jellyfish's Metaphone + NYSIIS. The chosen library is exposed so the README and
the run manifest can record it. These codes are English-centric; nothing here claims they
help with Spanish names (evaluation plan section 2).
"""

from __future__ import annotations

from collections.abc import Callable

PhoneticFn = Callable[[str], tuple[str, str]]


def _pick_library() -> tuple[str, PhoneticFn]:
    try:
        from metaphone import doublemetaphone  # type: ignore[import-not-found]

        def _dm(text: str) -> tuple[str, str]:
            primary, alternate = doublemetaphone(text)
            return primary or "", alternate or ""

        return "metaphone", _dm
    except ImportError:
        pass
    try:
        import phonetics  # type: ignore[import-not-found]

        def _ph(text: str) -> tuple[str, str]:
            primary, alternate = phonetics.dmetaphone(text)
            return primary or "", alternate or ""

        return "phonetics", _ph
    except ImportError:
        pass
    import jellyfish

    def _jf(text: str) -> tuple[str, str]:
        # jellyfish has no Double Metaphone; Metaphone is the primary code and NYSIIS stands in
        # for the alternate so equality checks still have a second chance on spelling variants.
        return jellyfish.metaphone(text) or "", jellyfish.nysiis(text) or ""

    return "jellyfish", _jf


PHONETICS_LIBRARY, _double_metaphone = _pick_library()


def double_metaphone(text: str) -> tuple[str, str]:
    """Primary and alternate phonetic codes; both empty for an empty or non-alphabetic input."""
    cleaned = "".join(ch for ch in text if ch.isalpha() or ch.isspace()).strip()
    if not cleaned:
        return "", ""
    return _double_metaphone(cleaned)


def phonetic_codes_match(a: str, b: str) -> bool:
    """True when any non-empty code of ``a`` equals any code of ``b`` (the usual DM rule)."""
    codes_a = {c for c in double_metaphone(a) if c}
    codes_b = {c for c in double_metaphone(b) if c}
    return bool(codes_a & codes_b)
