"""Offline terminology for BL-AMOX-01: the penicillin class set, order-code folding and labels.

Everything is read once from the JSON files committed under ``cache/``; the runtime
never calls RxNav or DailyMed (ADR-011).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "cache"
ANAPHYLAXIS_SNOMED = "39579001"
SNOMED_SYSTEM = "http://snomed.info/sct"
RXNORM_SYSTEM = "http://www.nlm.nih.gov/research/umls/rxnorm"


@dataclass(frozen=True)
class Label:
    drug_name: str
    label_name: str
    set_id: str
    revised: str
    section: str
    url: str
    quote: str
    ingredients: frozenset[str]


@dataclass(frozen=True)
class Terminology:
    class_id: str
    rela_sources: tuple[str, ...]
    rxnav_version: str
    fetched: str
    class_ingredients: frozenset[str]
    pin_to_in: dict[str, str]
    scd_to_ingredients: dict[str, tuple[str, ...]]
    labels: tuple[Label, ...]

    def knows(self, code: str) -> bool:
        """Whether the cache can say anything about this RxNorm code."""
        return code in self.class_ingredients or code in self.pin_to_in or code in self.scd_to_ingredients

    def fold(self, code: str) -> str:
        """A precise ingredient (PIN) folds to its ingredient (IN); anything else stays."""
        return self.pin_to_in.get(code, code)

    def ingredients_of(self, code: str) -> frozenset[str]:
        """Ingredients behind an order or allergy code: SCD map first, then PIN fold, then the code itself."""
        scd = self.scd_to_ingredients.get(code)
        if scd is not None:
            return frozenset(self.fold(c) for c in scd)
        return frozenset({self.fold(code)})

    def class_ingredients_of(self, code: str) -> frozenset[str]:
        return self.ingredients_of(code) & self.class_ingredients

    def label_for(self, ingredients: frozenset[str]) -> Label | None:
        """The label whose ingredient set equals the order's; otherwise none (never a near match)."""
        for label in self.labels:
            if label.ingredients == ingredients:
                return label
        return None

    def snapshot(self) -> dict:
        """What the evidence panel shows about the class table."""
        return {
            "classId": self.class_id,
            "relaSources": list(self.rela_sources),
            "rxnavVersion": self.rxnav_version,
            "fetched": self.fetched,
            "ingredients": sorted(self.class_ingredients),
        }


def _load_label(path: Path) -> Label:
    raw = json.loads(path.read_text())
    return Label(
        drug_name=raw["drug_name"],
        label_name=raw["label_name"],
        set_id=raw["set_id"],
        revised=raw["revised"],
        section=raw["section"],
        url=raw["url"],
        quote=raw["quote"],
        ingredients=frozenset(raw["ingredients"]),
    )


@lru_cache(maxsize=1)
def load_terminology(cache_dir: Path = CACHE_DIR) -> Terminology:
    klass = json.loads((cache_dir / "penicillin_class.json").read_text())
    scd = json.loads((cache_dir / "scd_to_ingredient.json").read_text())
    labels = tuple(_load_label(p) for p in sorted((cache_dir / "labels").glob("*.json")))
    return Terminology(
        class_id=klass["class_id"],
        rela_sources=tuple(klass["rela_sources"]),
        rxnav_version=klass["rxnav_version"],
        fetched=klass["fetched"],
        class_ingredients=frozenset(i["rxcui"] for i in klass["ingredients"]),
        pin_to_in=dict(klass["pin_to_in"]),
        scd_to_ingredients={code: tuple(entry["ingredients"]) for code, entry in scd["codes"].items()},
        labels=labels,
    )
