"""W3b's parser against the payloads W1's loaders really store (W1's own fixtures), so the rule,
the timeline and the golden record read exactly what ingest writes."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from backend.ingest.csvio import read_csv_dir
from backend.ingest.fhir import load_bundle
from backend.ingest.records import CSV_CLINICAL_LISTS, FHIR_CLINICAL_LISTS, plain_csv_draft, plain_fhir_draft
from backend.rule.bl_amox_01 import evaluate
from backend.rule.resources import parse_member
from backend.rule.terminology import RXNORM_SYSTEM, SNOMED_SYSTEM
from backend.tests.ingest.conftest import FIXTURES
from contracts.models.alerts import AlertTier

T0 = datetime(2026, 10, 17, 18, 0, tzinfo=UTC)


def member(draft):
    # through JSON, as the payload comes back from the jsonb column
    return parse_member(source_record_id=draft.id, source_system=draft.source_system, source_local_id=draft.source_local_id,
                        kind=draft.kind, is_constructed=draft.is_constructed, ingested_at=T0,
                        raw_payload=json.loads(json.dumps(draft.raw_payload)))


@pytest.fixture(scope="module")
def drafts():
    bundles = {b.patient_id: b for b in (load_bundle(FIXTURES / n) for n in ("bundle_a.json", "bundle_b.json"))}
    csvs = read_csv_dir(FIXTURES / "csv", patient_ids=set(bundles))
    return [plain_fhir_draft(b) for b in bundles.values()] + [plain_csv_draft(p) for p in csvs.values()]


def test_every_clinical_list_w1_stores_is_parsed_one_to_one(drafts):
    for d in drafts:
        m = member(d)
        if d.kind.value == "FHIR_PATIENT":
            sizes = {k: len(d.raw_payload.get(k) or []) for k in FHIR_CLINICAL_LISTS}
            assert (len(m.allergies), len(m.orders), len(m.encounters)) == (
                sizes["allergyIntolerances"], sizes["medicationRequests"], sizes["encounters"]), d.source_local_id
        else:
            sizes = {k: len(d.raw_payload.get(k) or []) for k in CSV_CLINICAL_LISTS}
            assert (len(m.allergies), len(m.orders), len(m.encounters)) == (
                sizes["allergies"], sizes["medications"], sizes["encounters"]), d.source_local_id


def test_w1_codes_systems_and_statuses_come_through(drafts):
    members = [member(d) for d in drafts]
    allergies = [a for m in members for a in m.allergies]
    assert allergies and all(a.code.system == RXNORM_SYSTEM and a.code.code == "7984" for a in allergies)
    assert all(c.system == SNOMED_SYSTEM for a in allergies for r in a.reactions for c in r.manifestations)
    orders = [o for m in members for o in m.orders]
    assert all(o.code.system == RXNORM_SYSTEM for o in orders), "medications.csv CODE is RxNorm, cached or not"
    assert {(o.code.code, o.status) for o in orders} >= {("308192", "active"), ("1014676", "completed")}


def test_rule_over_w1_records(drafts):
    members = {(d.source_system, len(d.raw_payload.get("allergyIntolerances") or d.raw_payload.get("allergies") or [])): member(d)
               for d in drafts}
    with_allergy = [m for (_, n), m in members.items() if n]
    without = [m for (_, n), m in members.items() if not n]
    for m in with_allergy:  # allergy and active amoxicillin in one record: same-source Tier A
        (flag,) = evaluate([m])
        assert flag.tier == AlertTier.A and flag.revealed_by_merge is False
    for m in without:  # cetirizine, completed: silent
        assert evaluate([m]) == []
    fhir, csv = (next(m for m in with_allergy if m.source_system == s) for s in ("ER_FHIR", "CLINIC_CSV"))
    linked = evaluate([fhir, csv])
    assert len(linked) == 4 and sum(f.revealed_by_merge for f in linked) == 2
