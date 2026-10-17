"""Survivorship rules, applied on read (ADR-014). Pure.

names: most frequent, then most recent. dob and sex: majority, else CONFLICT_UNRESOLVED.
phone, address, zip: most recent. Clinical lists: union (one golden value per item).
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from contracts.models.common import Crosswalk
from contracts.models.entities import GoldenAlternate, GoldenField

RULE_MOST_FREQUENT = "MOST_FREQUENT"
RULE_MOST_RECENT = "MOST_RECENT"
RULE_MAJORITY = "MAJORITY"
RULE_CONFLICT = "CONFLICT_UNRESOLVED"
RULE_UNION = "UNION"


@dataclass(frozen=True)
class MemberDemographics:
    source_system: str
    source_local_id: str
    ingested_at: datetime
    given_name: str | None = None
    family_name: str | None = None
    birth_date: date | None = None
    sex: str | None = None
    phone_e164: str | None = None
    address_line: str | None = None
    zip5: str | None = None

    @property
    def crosswalk(self) -> Crosswalk:
        return Crosswalk(source_system=self.source_system, source_record_id=self.source_local_id)


Value = str | date
Candidate = tuple[Value, MemberDemographics]


def _candidates(members: Sequence[MemberDemographics], attr: str) -> list[Candidate]:
    out = [(getattr(m, attr), m) for m in members if getattr(m, attr) not in (None, "")]
    return sorted(out, key=lambda c: (c[1].ingested_at, c[1].source_local_id), reverse=True)  # most recent first


def _json(value: Value) -> str:
    return value.isoformat() if isinstance(value, date) else value


def _alternates(candidates: list[Candidate], winner: MemberDemographics) -> list[GoldenAlternate]:
    return [GoldenAlternate(value=_json(v), crosswalk=m.crosswalk) for v, m in candidates if m is not winner]


def _field(name: str, winner: Candidate, rule: str, candidates: list[Candidate]) -> GoldenField:
    value, member = winner
    return GoldenField(field=name, value=_json(value), crosswalk=member.crosswalk, rule=rule,
                       alternates=_alternates(candidates, member))


def _normalize(value: Value) -> str:
    return value.casefold().strip() if isinstance(value, str) else value.isoformat()


def most_frequent_then_recent(name: str, candidates: list[Candidate]) -> GoldenField | None:
    if not candidates:
        return None
    counts = Counter(_normalize(v) for v, _ in candidates)
    top = max(counts.values())
    leaders = [c for c in candidates if counts[_normalize(c[0])] == top]
    rule = RULE_MOST_FREQUENT if list(counts.values()).count(top) == 1 and top > 1 else RULE_MOST_RECENT
    if len(counts) == 1:
        rule = RULE_MOST_FREQUENT
    return _field(name, leaders[0], rule, candidates)  # leaders are already most-recent first


def majority_else_conflict(name: str, candidates: list[Candidate]) -> GoldenField | None:
    if not candidates:
        return None
    counts = Counter(_normalize(v) for v, _ in candidates)
    key, top = counts.most_common(1)[0]
    if top * 2 > len(candidates):
        winner = next(c for c in candidates if _normalize(c[0]) == key)
        return _field(name, winner, RULE_MAJORITY, candidates)
    newest = candidates[0][1]
    return GoldenField(field=name, value=None, crosswalk=newest.crosswalk, rule=RULE_CONFLICT,
                       alternates=[GoldenAlternate(value=_json(v), crosswalk=m.crosswalk) for v, m in candidates])


def most_recent(name: str, candidates: list[Candidate]) -> GoldenField | None:
    if not candidates:
        return None
    return _field(name, candidates[0], RULE_MOST_RECENT, candidates)


# Closed map: golden field name -> (member attribute, rule). Identifiers never come from input.
FIELD_RULES: dict[str, tuple[str, Callable[[str, list[Candidate]], GoldenField | None]]] = {
    "givenName": ("given_name", most_frequent_then_recent),
    "familyName": ("family_name", most_frequent_then_recent),
    "birthDate": ("birth_date", majority_else_conflict),
    "sex": ("sex", majority_else_conflict),
    "phone": ("phone_e164", most_recent),
    "address": ("address_line", most_recent),
    "zip5": ("zip5", most_recent),
}


def golden_demographics(members: Sequence[MemberDemographics]) -> list[GoldenField]:
    fields = []
    for name, (attr, rule) in FIELD_RULES.items():
        field = rule(name, _candidates(members, attr))
        if field is not None:
            fields.append(field)
    return fields


def golden_union(name: str, items: Sequence[tuple[dict, Crosswalk]]) -> list[GoldenField]:
    """Clinical lists: every distinct item survives with its own crosswalk."""
    seen: set[str] = set()
    out = []
    for value, crosswalk in items:
        key = f"{value.get('code')}|{crosswalk.source_system}|{crosswalk.source_record_id}"
        if key in seen:
            continue
        seen.add(key)
        out.append(GoldenField(field=name, value=value, crosswalk=crosswalk, rule=RULE_UNION))
    return out
