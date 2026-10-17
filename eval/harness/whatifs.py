"""The four what-if transforms on an in-memory copy of a record (architecture section 9, ADR-013).

Used by the hero selector and fixture check. Each returns a new record; nothing stored changes.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

from eval.harness.types import Record

REMOVE_ADDRESS = "REMOVE_ADDRESS"
CHANGE_BIRTH_YEAR = "CHANGE_BIRTH_YEAR"
SWAP_DOB_DAY_MONTH = "SWAP_DOB_DAY_MONTH"
ACCENT_HYPHEN_SURNAME = "ACCENT_HYPHEN_SURNAME"
BUTTONS = (REMOVE_ADDRESS, CHANGE_BIRTH_YEAR, SWAP_DOB_DAY_MONTH, ACCENT_HYPHEN_SURNAME)

# The held-out category each button reads (eval plan section 5, per-button recall)
BUTTON_CATEGORIES = {REMOVE_ADDRESS: ("L7",), CHANGE_BIRTH_YEAR: ("D3",), SWAP_DOB_DAY_MONTH: ("D1",),
                     ACCENT_HYPHEN_SURNAME: ("S1", "S5")}
BUTTON_KIND = {REMOVE_ADDRESS: "band_changer", CHANGE_BIRTH_YEAR: "band_changer",
               SWAP_DOB_DAY_MONTH: "robustness", ACCENT_HYPHEN_SURNAME: "robustness"}


def remove_address(rec: Record) -> Record:
    out = dict(rec)
    out["address_line"] = None
    out["zip5"] = None
    return out


_ISO_DOB = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _iso_dob(rec: Record) -> tuple[str, str, str] | None:
    value = rec.get("birth_date")
    if not value or not _ISO_DOB.match(value):
        return None
    y, m, d = value.split("-")
    return y, m, d


def change_birth_year(rec: Record, delta: int) -> Record:
    out = dict(rec)
    if _iso_dob(rec) is None:
        return out
    y, m, d = rec["birth_date"].split("-")
    out["birth_date"] = f"{int(y) + delta:04d}-{m}-{d}"
    return out


def swap_dob_day_month(rec: Record) -> Record:
    """Applicable only when day <= 12 and day != month; otherwise the record is unchanged."""
    out = dict(rec)
    parts = _iso_dob(rec)
    if parts is None:
        return out
    y, m, d = parts
    if int(d) <= 12 and d != m:
        out["birth_date"] = f"{y}-{d}-{m}"
    return out


def _strip_accents(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def accent_plus_hyphen(rec: Record) -> Record:
    """Fold accents and toggle the hyphen between two surname tokens (S1 plus S5)."""
    out = dict(rec)
    family = rec.get("family_name") or ""
    folded = _strip_accents(family)
    if "-" in folded:
        folded = folded.replace("-", " ")
    elif " " in folded.strip():
        head, _, tail = folded.strip().partition(" ")
        folded = f"{head}-{tail}"
    out["family_name"] = folded
    if rec.get("given_name"):
        out["given_name"] = _strip_accents(rec["given_name"])
    return out


def is_applicable(button: str, rec: Record) -> bool:
    if button == SWAP_DOB_DAY_MONTH:
        return swap_dob_day_month(rec) != rec
    if button == ACCENT_HYPHEN_SURNAME:
        return accent_plus_hyphen(rec) != rec
    if button == REMOVE_ADDRESS:
        return bool(rec.get("address_line"))
    return _iso_dob(rec) is not None


def inapplicable_caption(button: str, rec: Record) -> str:
    """Plain words for an edit that cannot happen on this record: no effect is claimed."""
    if button == SWAP_DOB_DAY_MONTH:
        parts = _iso_dob(rec)
        if parts is None:
            return "This record has no full birth date to swap."
        _, m, d = parts
        if d == m:
            return "This birth date has no day/month swap: the day and the month are the same."
        return "This birth date has no day/month swap: the day is above 12."
    if button == ACCENT_HYPHEN_SURNAME:
        return "This name has no accents or hyphens to change."
    if button == REMOVE_ADDRESS:
        return "This record has no address to remove."
    return "This record has no full birth date to change."


def caption_of(button: str, rec: Record, baseline_band: str, what_if_band: str, delta_p: float) -> str:
    """The caption a what-if ships with, from what the button actually does on ``rec`` (the ER record)."""
    if not is_applicable(button, rec):
        return inapplicable_caption(button, rec)
    return caption_for(button, baseline_band, what_if_band, delta_p)


TRANSFORMS: dict[str, Callable[[Record], Record]] = {
    REMOVE_ADDRESS: remove_address,
    SWAP_DOB_DAY_MONTH: swap_dob_day_month,
    ACCENT_HYPHEN_SURNAME: accent_plus_hyphen,
}


# Captions are derived from the band change and score movement the export actually ships (architecture
# 9.1: narrate only the band changes that occur). "not enough to link" appears only with KEEP_SEPARATE,
# and is abstention (INSUFFICIENT_EVIDENCE), never "two people".
CAPTION_PREFIX = {REMOVE_ADDRESS: "Without the address", CHANGE_BIRTH_YEAR: "A different birth year",
                  SWAP_DOB_DAY_MONTH: "Day and month swapped", ACCENT_HYPHEN_SURNAME: "Accents and hyphens changed"}
NAMED_FEATURE = {SWAP_DOB_DAY_MONTH: "the engine has a named feature for this",
                 ACCENT_HYPHEN_SURNAME: "a named feature"}
BAND_WORDS = {"AUTO_LINK": "the auto-link band", "REVIEW": "review", "KEEP_SEPARATE": "keep separate"}
BARELY_MOVES_P = 0.05  # the published robustness tolerance (eval plan section 3)


def caption_for(button: str, baseline_band: str, what_if_band: str, delta_p: float) -> str:
    prefix = CAPTION_PREFIX[button]
    if what_if_band == "KEEP_SEPARATE" and baseline_band != "KEEP_SEPARATE":
        if button == REMOVE_ADDRESS:
            return "Without the address there is not enough to link."
        return f"{prefix}: not enough to link."
    if what_if_band != baseline_band:
        return f"{prefix}: the pair moves to {BAND_WORDS[what_if_band]}."
    movement = ("the score barely moves" if abs(delta_p) <= BARELY_MOVES_P
                else f"the probability estimate moves by {delta_p:+.2f}")
    if button in NAMED_FEATURE:
        return f"{prefix}: {NAMED_FEATURE[button]}; {movement}."
    return f"{prefix}: the pair stays in {BAND_WORDS[what_if_band]}; {movement}."
