"""Phonetic surname codes shared by W1 (block keys) and W2 (features).

Install order from the build brief: metaphone 0.6, then phonetics 1.0.5, then jellyfish.
``uv add metaphone==0.6`` succeeded on the first try (2026-10-17 13:30 CT, Python 3.12.13),
so the later two were never installed. LIBRARY records the pick for the README.

The codes are English-centric; they are a blocking aid, never evidence for Spanish names.
"""
from __future__ import annotations

from metaphone import doublemetaphone

LIBRARY = "metaphone==0.6"


def double_metaphone(text: str | None) -> tuple[str, str]:
    """Primary and alternate Double Metaphone codes; empty strings when there is nothing to code."""
    if not text:
        return "", ""
    primary, alternate = doublemetaphone(text)
    return primary or "", alternate or ""


def primary_code(text: str | None) -> str | None:
    """The primary code, or None when the input has no codable letters (digits, punctuation only)."""
    primary, _ = double_metaphone(text)
    return primary or None
