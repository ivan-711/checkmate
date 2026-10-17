"""Parse a source record's immutable raw payload into the clinical resources the rule,
the timeline and the golden record read.

Two payload families (architecture S1):
- FHIR (kind FHIR_PATIENT): any JSON that contains R4 resources, a transaction Bundle or
  a container dict. Every dict with ``resourceType`` in {AllergyIntolerance,
  MedicationRequest, Encounter, Medication} is collected wherever it sits.
- CSV (kind CSV_ROW): a dict with the patients.csv columns and, beside them, lists of
  allergies.csv, medications.csv and encounters.csv rows. Rows are recognised by their
  Synthea headers (REACTION1 / DISPENSES / ENCOUNTERCLASS) or by their container key.

Only the fields the spec names are read; everything else stays in the raw payload.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from backend.rule.terminology import ANAPHYLAXIS_SNOMED, RXNORM_SYSTEM, SNOMED_SYSTEM, load_terminology
from contracts.models.common import SourceKind
from contracts.models.entities import TimelineVerification

CONSTRUCTED_TAG_SYSTEM = "urn:chartguard:provenance"
CONSTRUCTED_TAG_CODE = "constructed-scenario"
ALLERGY_FILE = "allergies.csv"
MEDICATION_FILE = "medications.csv"
ENCOUNTER_FILE = "encounters.csv"
# CSV SYSTEM values that do not name a code system. The Nov 2021 sample writes "Unknown" on
# every allergy row, so a strict "RxNorm" test would silence the rule on real Synthea CSV;
# such a row is labeled RxNorm only when the terminology cache knows the code.
CSV_UNSTATED_SYSTEMS = frozenset({"unknown", ""})
_SEVERITY_RANK = {"severe": 3, "moderate": 2, "mild": 1}
_SNOMED_TAG = re.compile(r"\s*\((disorder|finding|substance|procedure|product)\)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Coding:
    system: str | None
    code: str
    display: str | None


def is_rxnorm(system: str | None) -> bool:
    return system is not None and "rxnorm" in system.lower()


@dataclass(frozen=True)
class Reaction:
    severity: str | None  # mild / moderate / severe, lower-case; None when not recorded
    manifestations: tuple[Coding, ...]  # every coding of every manifestation, system kept
    manifestation_display: str | None


def is_anaphylaxis(reaction: Reaction) -> bool:
    """Only SNOMED CT 39579001 counts; a local system reusing the digits does not."""
    return any(c.system == SNOMED_SYSTEM and c.code == ANAPHYLAXIS_SNOMED for c in reaction.manifestations)


def worst_reaction(reactions: tuple[Reaction, ...]) -> Reaction | None:
    """Anaphylaxis first, then the explicit severity rank; shared by the card and the timeline."""
    if not reactions:
        return None
    return max(reactions, key=lambda r: (is_anaphylaxis(r), _SEVERITY_RANK.get(r.severity, 0)))


@dataclass(frozen=True)
class SourceRef:
    source_record_id: UUID
    source_system: str
    source_local_id: str
    resource_id: str  # "AllergyIntolerance/<id>" or "allergies.csv:<row>"
    is_constructed: bool
    verification: TimelineVerification


@dataclass(frozen=True)
class AllergyRecord:
    ref: SourceRef
    code: Coding | None  # preferred coding: the first RxNorm one, else the first
    codings: tuple[Coding, ...]  # every coding; eligibility scans all of them
    type: str | None  # allergy / intolerance; None when absent (never eligible)
    clinical_status: str | None  # active / inactive / resolved
    verification_status: str | None  # confirmed / unconfirmed / refuted / entered-in-error; None = not stated
    criticality: str | None  # low / high / unable-to-assess; None for CSV
    reactions: tuple[Reaction, ...]
    recorded_at: datetime | None


@dataclass(frozen=True)
class OrderRecord:
    ref: SourceRef
    code: Coding | None
    codings: tuple[Coding, ...]
    status: str | None  # FHIR MedicationRequest.status
    intent: str | None
    authored_at: datetime | None
    requester_display: str | None


@dataclass(frozen=True)
class EncounterRecord:
    ref: SourceRef
    class_code: str | None
    type: Coding | None
    start: datetime | None
    end: datetime | None
    service_provider: str | None


@dataclass(frozen=True)
class MemberResources:
    source_record_id: UUID
    source_system: str
    source_local_id: str
    kind: SourceKind
    is_constructed: bool
    ingested_at: datetime
    allergies: tuple[AllergyRecord, ...] = field(default_factory=tuple)
    orders: tuple[OrderRecord, ...] = field(default_factory=tuple)
    encounters: tuple[EncounterRecord, ...] = field(default_factory=tuple)


def parse_timestamp(value: Any) -> datetime | None:
    """ISO date or datetime; a bare date is midnight UTC; a naive time is UTC."""
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def strip_snomed_tag(display: str | None) -> str | None:
    """ "Anaphylaxis (disorder)" reads as "anaphylaxis" on the card."""
    if not display:
        return None
    text = _SNOMED_TAG.sub("", display).strip()
    return text[:1].lower() + text[1:] if text else None


# FHIR -----------------------------------------------------------------------------------


def _walk_resources(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        if isinstance(node.get("resourceType"), str):
            yield node
        for value in node.values():
            yield from _walk_resources(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_resources(item)


def _codings(concept: Mapping | None) -> tuple[Coding, ...]:
    if not concept:
        return ()
    return tuple(
        Coding(system=c.get("system"), code=str(c["code"]), display=c.get("display") or concept.get("text"))
        for c in concept.get("coding") or []
        if c.get("code")
    )


def preferred_coding(codings: tuple[Coding, ...]) -> Coding | None:
    """The RxNorm coding when there is one, else the first: display never depends on coding order."""
    return next((c for c in codings if is_rxnorm(c.system)), codings[0] if codings else None)


def _first_coding(concept: Mapping | None) -> Coding | None:
    return preferred_coding(_codings(concept))


def _first_code(concept: Mapping | None) -> str | None:
    coding = _first_coding(concept)
    return coding.code if coding else None


def _is_constructed_resource(resource: Mapping) -> bool:
    tags = (resource.get("meta") or {}).get("tag") or []
    return any(t.get("system") == CONSTRUCTED_TAG_SYSTEM and t.get("code") == CONSTRUCTED_TAG_CODE for t in tags)


def _fhir_ref(base: MemberResources, resource: Mapping, index: int) -> SourceRef:
    """``Type/id``; a resource without an id gets its position in the payload so two such
    resources never share a reference."""
    rid = f"{resource['resourceType']}/{resource.get('id') or f'_{index}'}"
    return SourceRef(
        base.source_record_id,
        base.source_system,
        base.source_local_id,
        rid,
        base.is_constructed or _is_constructed_resource(resource),
        TimelineVerification.CODED,
    )


def _fhir_allergy(base: MemberResources, r: Mapping, index: int) -> AllergyRecord:
    reactions = []
    for reaction in r.get("reaction") or []:
        manifestations = reaction.get("manifestation") or []
        codings = tuple(c for m in manifestations for c in _codings(m))
        display = next((c.display for c in codings if c.display), None)
        reactions.append(Reaction((reaction.get("severity") or None), codings, display))
    codings = _codings(r.get("code"))
    return AllergyRecord(
        ref=_fhir_ref(base, r, index),
        code=preferred_coding(codings),
        codings=codings,
        type=r.get("type"),
        clinical_status=_first_code(r.get("clinicalStatus")),
        verification_status=_first_code(r.get("verificationStatus")),
        criticality=r.get("criticality"),
        reactions=tuple(reactions),
        recorded_at=parse_timestamp(r.get("recordedDate")),
    )


def _fhir_order(base: MemberResources, r: Mapping, index: int, medications: Mapping[str, Mapping]) -> OrderRecord:
    concept = r.get("medicationCodeableConcept")
    if concept is None and (ref := (r.get("medicationReference") or {}).get("reference")):
        # "#id" (contained), "urn:uuid:id" (transaction bundle) or "Medication/id" all key the same map
        med_id = ref.lstrip("#").split("/")[-1].replace("urn:uuid:", "")
        concept = (medications.get(med_id) or {}).get("code")
    codings = _codings(concept)
    return OrderRecord(
        ref=_fhir_ref(base, r, index),
        code=preferred_coding(codings),
        codings=codings,
        status=r.get("status"),
        intent=r.get("intent"),
        authored_at=parse_timestamp(r.get("authoredOn")),
        requester_display=(r.get("requester") or {}).get("display"),
    )


def _fhir_encounter(base: MemberResources, r: Mapping, index: int) -> EncounterRecord:
    period = r.get("period") or {}
    types = r.get("type") or []
    return EncounterRecord(
        ref=_fhir_ref(base, r, index),
        class_code=(r.get("class") or {}).get("code"),
        type=_first_coding(types[0]) if types else None,
        start=parse_timestamp(period.get("start")),
        end=parse_timestamp(period.get("end")),
        service_provider=(r.get("serviceProvider") or {}).get("display"),
    )


def _parse_fhir(base: MemberResources, payload: Any) -> MemberResources:
    resources = list(_walk_resources(payload))
    medications = {r.get("id"): r for r in resources if r["resourceType"] == "Medication"}
    allergies = tuple(
        _fhir_allergy(base, r, i) for i, r in enumerate(resources) if r["resourceType"] == "AllergyIntolerance"
    )
    orders = tuple(
        _fhir_order(base, r, i, medications)
        for i, r in enumerate(resources)
        if r["resourceType"] == "MedicationRequest"
    )
    encounters = tuple(_fhir_encounter(base, r, i) for i, r in enumerate(resources) if r["resourceType"] == "Encounter")
    return MemberResources(**{**base.__dict__, "allergies": allergies, "orders": orders, "encounters": encounters})


# CSV ------------------------------------------------------------------------------------


def _upper(row: Mapping) -> dict[str, Any]:
    return {str(k).upper(): v for k, v in row.items()}


def _row_kind(row: Mapping, container_key: str | None) -> str | None:
    """Container key first, then the header column unique to each Synthea file. REASONCODE is
    not a discriminator: encounters, procedures and careplans carry it too."""
    key = (container_key or "").lower()
    if "allerg" in key or "REACTION1" in row or "SEVERITY1" in row:
        return ALLERGY_FILE
    if "encounter" in key or "ENCOUNTERCLASS" in row:
        return ENCOUNTER_FILE
    if "medic" in key or "DISPENSES" in row or "TOTALCOST" in row:
        return MEDICATION_FILE
    return None


def _walk_rows(node: Any, container_key: str | None = None) -> Iterator[tuple[str, dict]]:
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        up = _upper(item)
                        kind = _row_kind(up, key)
                        if kind:
                            yield kind, up
                        else:
                            yield from _walk_rows(item, key)
            elif isinstance(value, dict):
                yield from _walk_rows(value, key)


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _csv_ref(base: MemberResources, file: str, row: Mapping, index: int) -> SourceRef:
    key = row.get("ROW_ID") or row.get("ID") or row.get("ROW") or str(index)
    return SourceRef(
        base.source_record_id,
        base.source_system,
        base.source_local_id,
        f"{file}:{key}",
        base.is_constructed or _truthy(row.get("CONSTRUCTED", "")),
        TimelineVerification.CSV_DERIVED,
    )


def _csv_code(row: Mapping, *, always_rxnorm: bool = False) -> Coding | None:
    """``always_rxnorm`` for medications.csv, which has no SYSTEM column: its CODE is RxNorm by the
    Synthea CSV data dictionary. allergies.csv mixes RxNorm and SNOMED under SYSTEM "Unknown", so
    there an unstated system is RxNorm only when the terminology cache knows the code."""
    code = str(row.get("CODE") or "").strip()
    if not code:
        return None
    system: str | None = str(row.get("SYSTEM") or "").strip()
    if always_rxnorm or system.lower() == "rxnorm":
        system = RXNORM_SYSTEM
    elif system.lower() in CSV_UNSTATED_SYSTEMS:
        system = RXNORM_SYSTEM if load_terminology().knows(code) else None
    return Coding(system=system, code=code, display=row.get("DESCRIPTION") or None)


def _csv_allergy(base: MemberResources, row: Mapping, index: int) -> AllergyRecord:
    reactions = []
    for n in ("1", "2"):
        code, severity = row.get(f"REACTION{n}"), row.get(f"SEVERITY{n}")
        if code or severity:
            description = row.get(f"DESCRIPTION{n}") or None
            # Synthea reaction codes are SNOMED CT (CSV data dictionary); the adapter says so explicitly
            manifestations = (Coding(SNOMED_SYSTEM, str(code), description),) if code else ()
            reactions.append(
                Reaction((str(severity).lower() or None) if severity else None, manifestations, description)
            )
    code = _csv_code(row)
    return AllergyRecord(
        ref=_csv_ref(base, ALLERGY_FILE, row, index),
        code=code,
        codings=(code,) if code else (),
        type=(str(row.get("TYPE")).lower() or None) if row.get("TYPE") else None,
        clinical_status="active" if not row.get("STOP") else "inactive",
        verification_status=None,  # allergies.csv carries no verificationStatus: "not stated in source"
        criticality=None,  # nor criticality
        reactions=tuple(reactions),
        recorded_at=parse_timestamp(row.get("START")),
    )


def _csv_order(base: MemberResources, row: Mapping, index: int) -> OrderRecord:
    code = _csv_code(row, always_rxnorm=True)
    return OrderRecord(
        ref=_csv_ref(base, MEDICATION_FILE, row, index),
        code=code,
        codings=(code,) if code else (),
        status=str(row["STATUS"]).lower() if row.get("STATUS") else ("active" if not row.get("STOP") else "completed"),
        intent=str(row["INTENT"]).lower() if row.get("INTENT") else "order",
        authored_at=parse_timestamp(row.get("START")),
        requester_display=row.get("PROVIDER") or None,
    )


def _csv_encounter(base: MemberResources, row: Mapping, index: int) -> EncounterRecord:
    code = str(row.get("CODE") or "").strip()
    return EncounterRecord(
        ref=_csv_ref(base, ENCOUNTER_FILE, row, index),
        class_code=row.get("ENCOUNTERCLASS") or None,
        type=Coding("http://snomed.info/sct", code, row.get("DESCRIPTION") or None) if code else None,
        start=parse_timestamp(row.get("START")),
        end=parse_timestamp(row.get("STOP")),
        service_provider=row.get("ORGANIZATION") or None,
    )


def _parse_csv(base: MemberResources, payload: Any) -> MemberResources:
    allergies, orders, encounters = [], [], []
    counters = {ALLERGY_FILE: 0, MEDICATION_FILE: 0, ENCOUNTER_FILE: 0}
    for kind, row in _walk_rows(payload):
        index = counters[kind]
        counters[kind] += 1
        if kind == ALLERGY_FILE:
            allergies.append(_csv_allergy(base, row, index))
        elif kind == MEDICATION_FILE:
            orders.append(_csv_order(base, row, index))
        else:
            encounters.append(_csv_encounter(base, row, index))
    return MemberResources(
        **{**base.__dict__, "allergies": tuple(allergies), "orders": tuple(orders), "encounters": tuple(encounters)}
    )


# Entry point ----------------------------------------------------------------------------


def parse_member(
    *,
    source_record_id: UUID,
    source_system: str,
    source_local_id: str,
    kind: SourceKind | str,
    is_constructed: bool,
    ingested_at: datetime,
    raw_payload: Any,
) -> MemberResources:
    """One source_record row to its parsed clinical resources."""
    kind = SourceKind(kind)
    base = MemberResources(source_record_id, source_system, source_local_id, kind, bool(is_constructed), ingested_at)
    if raw_payload is None:
        return base
    if kind == SourceKind.CSV_ROW:
        return _parse_csv(base, raw_payload)
    return _parse_fhir(base, raw_payload)
