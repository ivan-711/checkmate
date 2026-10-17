"""The 18-row test table from the rule spec (section 5), every row, through the real parser.

Rows about link state (2, 3, 4, 13) run the pure union-find over approved edges and
evaluate each component, which is exactly what the service does inside the transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from backend.link.union_find import components
from backend.rule.bl_amox_01 import (
    CLOSING,
    HEADLINE_A,
    HEADLINE_B,
    NO_CACHED_LABEL,
    NON_REVEAL_SENTENCE,
    REVEAL_SENTENCE,
    VERIFICATION_NOT_STATED,
    detected_issue,
    evaluate,
    to_safety_alert,
)
from backend.rule.resources import MemberResources, parse_member
from contracts.models.alerts import CARD_FOOTER, AlertTier
from contracts.models.common import SourceKind

T0 = datetime(2026, 10, 17, 18, 0, tzinfo=UTC)
ER = UUID("00000000-0000-4000-8000-000000000001")
CLINIC = UUID("00000000-0000-4000-8000-000000000002")
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
SNOMED = "http://snomed.info/sct"


def fhir_allergy(
    code="7984",
    display="Penicillin V",
    *,
    type_="allergy",
    clinical="active",
    verification="confirmed",
    criticality="low",
    reactions=(("39579001", "Anaphylaxis (disorder)", "severe"),),
    system=RXNORM,
) -> dict:
    r = {
        "resourceType": "AllergyIntolerance",
        "id": "al-1",
        "clinicalStatus": {"coding": [{"code": clinical}]},
        "verificationStatus": {"coding": [{"code": verification}]},
        "category": ["medication"],
        "criticality": criticality,
        "code": {"coding": [{"system": system, "code": code, "display": display}]},
        "recordedDate": "2024-03-02T10:00:00Z",
        "reaction": [
            {"manifestation": [{"coding": [{"system": SNOMED, "code": mc, "display": md}]}], "severity": sev}
            for mc, md, sev in reactions
        ],
    }
    if type_ is not None:
        r["type"] = type_
    return r


def fhir_order(
    code="308192", display="Amoxicillin 500 MG Oral Tablet", *, status="active", intent="order", constructed=False
) -> dict:
    r = {
        "resourceType": "MedicationRequest",
        "id": "mr-1",
        "status": status,
        "intent": intent,
        "medicationCodeableConcept": {"coding": [{"system": RXNORM, "code": code, "display": display}]},
        "authoredOn": "2026-10-17T15:00:00Z",
        "requester": {"display": "Dr. Example"},
    }
    if constructed:
        r["meta"] = {"tag": [{"system": "urn:chartguard:provenance", "code": "constructed-scenario"}]}
    return r


def bundle(*resources: dict) -> dict:
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {"fullUrl": "urn:uuid:p", "resource": {"resourceType": "Patient", "id": "p"}},
            *({"fullUrl": f"urn:uuid:{r['id']}", "resource": r} for r in resources),
        ],
    }


def er_member(*resources: dict, record_id: UUID = ER, constructed=False) -> MemberResources:
    return parse_member(
        source_record_id=record_id,
        source_system="ER_FHIR",
        source_local_id="ER-MRN-1",
        kind=SourceKind.FHIR_PATIENT,
        is_constructed=constructed,
        ingested_at=T0,
        raw_payload=bundle(*resources),
    )


def csv_allergy_row(
    code="7984",
    description="Penicillin V",
    *,
    stop="",
    type_="allergy",
    severity1="SEVERE",
    reaction1="39579001",
    description1="Anaphylaxis",
) -> dict:
    return {
        "START": "2024-03-02",
        "STOP": stop,
        "PATIENT": "p",
        "ENCOUNTER": "e",
        "CODE": code,
        "SYSTEM": "Unknown",
        "DESCRIPTION": description,
        "TYPE": type_,
        "CATEGORY": "medication",
        "REACTION1": reaction1,
        "DESCRIPTION1": description1,
        "SEVERITY1": severity1,
        "REACTION2": "",
        "DESCRIPTION2": "",
        "SEVERITY2": "",
    }


def clinic_member(allergies=(), medications=(), record_id: UUID = CLINIC) -> MemberResources:
    payload = {
        "Id": "p",
        "First": "Ana",
        "Last": "Placeholder",
        "allergies": list(allergies),
        "medications": list(medications),
    }
    return parse_member(
        source_record_id=record_id,
        source_system="CLINIC_CSV",
        source_local_id="CLINIC-7",
        kind=SourceKind.CSV_ROW,
        is_constructed=False,
        ingested_at=T0,
        raw_payload=payload,
    )


def flags_for(members: list[MemberResources], approved_edges: list[tuple[UUID, UUID]]):
    """What the service does: components over approved edges, the rule per component."""
    by_id = {m.source_record_id: m for m in members}
    comps = components(approved_edges, by_id)
    out = []
    for comp in {frozenset(c) for c in comps.values()}:
        out.extend(evaluate([by_id[i] for i in sorted(comp, key=str)]))
    return out


LINK = [(ER, CLINIC)]
HERO_ALLERGY = clinic_member(allergies=[csv_allergy_row()])
HERO_ORDER = er_member(fhir_order(constructed=True), constructed=True)

ROWS = {
    1: ([HERO_ALLERGY, HERO_ORDER], LINK, "A"),
    2: ([HERO_ALLERGY, HERO_ORDER], [], None),
    "3a": ([HERO_ALLERGY], [], None),
    "3b": ([HERO_ORDER], [], None),
    5: ([clinic_member(allergies=[csv_allergy_row(stop="2025-01-01")]), HERO_ORDER], LINK, None),
    6: (
        [
            er_member(fhir_allergy(verification="refuted")),
            clinic_member(
                medications=[
                    {
                        "START": "2026-10-01",
                        "STOP": "",
                        "CODE": "308192",
                        "DESCRIPTION": "Amoxicillin 500 MG Oral Tablet",
                        "DISPENSES": "1",
                    }
                ]
            ),
        ],
        LINK,
        None,
    ),
    7: ([clinic_member(allergies=[csv_allergy_row(type_="intolerance")]), HERO_ORDER], LINK, None),
    8: ([HERO_ALLERGY, er_member(fhir_order(status="completed"))], LINK, None),
    9: (
        [HERO_ALLERGY, er_member(fhir_order(code="1649988", display="doxycycline hyclate 100 MG Oral Tablet"))],
        LINK,
        None,
    ),
    10: ([clinic_member(allergies=[csv_allergy_row(code="2231", description="Cephalexin")]), HERO_ORDER], LINK, None),
    11: (
        [
            clinic_member(
                allergies=[
                    csv_allergy_row(severity1="MILD", reaction1="271807003", description1="Eruption of skin (disorder)")
                ]
            ),
            HERO_ORDER,
        ],
        LINK,
        "B",
    ),
    12: ([er_member(fhir_allergy(), fhir_order())], [], "A"),
    13: (
        [HERO_ALLERGY, HERO_ORDER],
        [],
        None,
    ),  # the only edge is an unapproved auto-link proposal: not in the approved set
    14: (
        [HERO_ALLERGY, er_member(fhir_order(code="834061", display="Penicillin V Potassium 250 MG Oral Tablet"))],
        LINK,
        "A",
    ),
    "15a": ([HERO_ALLERGY, er_member(fhir_order(code="1297882", display="amoxicillin anhydrous"))], LINK, "A"),
    "15b": ([HERO_ALLERGY, er_member(fhir_order(code="308182", display="Amoxicillin 250 MG Oral Capsule"))], LINK, "A"),
    16: (
        [HERO_ALLERGY, er_member(fhir_order(code="789980", display="Ampicillin 100 MG/ML Injectable Solution"))],
        LINK,
        "A",
    ),
    17: ([HERO_ALLERGY, HERO_ORDER], LINK, "A"),
    18: ([HERO_ALLERGY, er_member(fhir_order(status="draft"))], LINK, None),
}


@pytest.mark.parametrize("row", list(ROWS))
def test_table_row(row):
    members, edges, expected = ROWS[row]
    flags = flags_for(members, edges)
    if expected is None:
        assert flags == []
    else:
        assert [f.tier.value for f in flags] == [expected]


def test_row_1_tier_a_card_is_the_exact_reveal_text():
    (flag,) = flags_for([HERO_ALLERGY, HERO_ORDER], LINK)
    assert flag.revealed_by_merge is True
    assert flag.constructed_scenario is True
    assert flag.card_text == (
        "Flagged for clinician review. Two records that were previously separate are now linked to this patient by an "
        "approved identity link. [Clinic CSV, allergies.csv row 0] documents an allergy coded penicillin V (RxNorm 7984; "
        "status active; verification not stated in source; reaction: anaphylaxis, severe). This rule treats that code as "
        "penicillin-class. [ER FHIR, MedicationRequest/mr-1] has an active order for Amoxicillin 500 MG Oral Tablet, "
        "RxNorm 308192. The amoxicillin label (DailyMed, set d5eba477-e255-4d97-9e16-30543c298680, revised 3/2023) "
        'states: "contraindicated in patients with a history of serious hypersensitivity reactions (e.g., anaphylaxis or '
        "Stevens-Johnson syndrome) to amoxicillin, clavulanate or to other beta-lactam antibacterial drugs (e.g., "
        'penicillins and cephalosporins)". This is a rule-based flag on synthetic data. It does not say what the patient '
        "took or tolerated, or what should be prescribed. A clinician decides."
    )
    assert flag.citation is not None and flag.citation.set_id == "d5eba477-e255-4d97-9e16-30543c298680"


def test_amoxicillin_clavulanate_order_cites_the_chartwell_label():
    (flag,) = flags_for(
        [
            HERO_ALLERGY,
            er_member(fhir_order(code="562251", display="Amoxicillin 250 MG / Clavulanate 125 MG Oral Tablet")),
        ],
        LINK,
    )
    assert flag.citation.set_id == "f10634cb-6505-43f1-9b70-314c58673016"
    assert flag.citation.revised == "10/2026"
    assert (
        "The amoxicillin/clavulanate label (DailyMed, set f10634cb-6505-43f1-9b70-314c58673016, revised 10/2026) states:"
        in flag.card_text
    )


def test_row_4_split_retracts_when_the_edge_is_gone():
    assert len(flags_for([HERO_ALLERGY, HERO_ORDER], LINK)) == 1
    assert flags_for([HERO_ALLERGY, HERO_ORDER], []) == []


def test_row_11_tier_b_card_has_no_quotation():
    members, edges, _ = ROWS[11]
    (flag,) = flags_for(members, edges)
    assert flag.card_text.startswith(HEADLINE_B + " " + REVEAL_SENTENCE)
    assert "The documented reaction is mild; this rule cannot tell whether it is serious." in flag.card_text
    assert "states:" not in flag.card_text and flag.citation is None
    assert flag.card_text.endswith(CLOSING)


def test_row_12_same_source_uses_the_non_reveal_template():
    members, edges, _ = ROWS[12]
    (flag,) = flags_for(members, edges)
    assert flag.revealed_by_merge is False
    assert flag.card_text.startswith(HEADLINE_A + " " + NON_REVEAL_SENTENCE)
    assert REVEAL_SENTENCE not in flag.card_text


def test_row_16_no_cached_label_line():
    members, edges, _ = ROWS[16]
    (flag,) = flags_for(members, edges)
    assert flag.citation is None
    assert NO_CACHED_LABEL in flag.card_text
    assert "states:" not in flag.card_text


def test_row_17_csv_allergy_shows_verification_not_stated():
    (flag,) = flags_for([HERO_ALLERGY, HERO_ORDER], LINK)
    assert f"verification {VERIFICATION_NOT_STATED}" in flag.card_text
    assert flag.allergy.criticality is None and flag.allergy.verification_status is None


def test_criticality_high_alone_is_tier_a_on_non_synthea_input():
    member = er_member(fhir_allergy(criticality="high", reactions=()), fhir_order())
    (flag,) = evaluate([member])
    assert flag.tier == AlertTier.A and "reaction: not recorded" in flag.card_text


def test_allergy_without_type_is_not_eligible():
    assert evaluate([er_member(fhir_allergy(type_=None), fhir_order())]) == []


def test_safety_alert_and_detected_issue_shape():
    (flag,) = flags_for([HERO_ALLERGY, HERO_ORDER], LINK)
    entity = UUID("00000000-0000-4000-8000-000000000900")
    alert = to_safety_alert(
        flag, alert_id=UUID("00000000-0000-4000-8000-000000000950"), entity_id=entity, identified_at=T0
    )
    assert alert.severity == "moderate" and alert.status.value == "PRELIMINARY" and alert.card_footer == CARD_FOOTER
    assert alert.allergy_ref.source_system == "CLINIC_CSV" and alert.order_ref.resource_id == "MedicationRequest/mr-1"
    assert alert.constructed_scenario is True
    issue = detected_issue(alert)
    assert (
        issue["resourceType"] == "DetectedIssue"
        and issue["status"] == "preliminary"
        and issue["severity"] == "moderate"
    )
    assert issue["detail"] == alert.card_text and issue["reference"] == alert.citation.url
    assert [i["reference"] for i in issue["implicated"]] == ["MedicationRequest/mr-1", "allergies.csv:0"]
    tier_b = to_safety_alert(flags_for(*ROWS[11][:2])[0], alert_id=alert.id, entity_id=entity, identified_at=T0)
    assert tier_b.severity == "moderate" and tier_b.citation is None


def test_never_say_words_are_absent_from_every_card():
    banned = (
        "alert stopped",
        "prevented",
        "the AI caught",
        "diagnosed",
        "would have died",
        "fatal",
        "held",
        "automatically canceled",
        "blocked",
        "AI decided",
        "contraindicated for this patient",
    )
    for members, edges, _ in ROWS.values():
        for flag in flags_for(members, edges):
            low = flag.card_text.lower()
            assert all(b.lower() not in low for b in banned), flag.card_text
            assert "flagged for clinician review" in low


def test_csv_encounter_rows_with_reasoncode_are_encounters_not_orders():
    member = clinic_member()
    payload = {
        "Id": "p",
        "encounters": [
            {
                "Id": "e1",
                "START": "2024-03-02T10:00:00Z",
                "STOP": "2024-03-02T10:30:00Z",
                "PATIENT": "p",
                "ENCOUNTERCLASS": "ambulatory",
                "CODE": "185349003",
                "DESCRIPTION": "Encounter for check up (procedure)",
                "REASONCODE": "",
                "REASONDESCRIPTION": "",
            }
        ],
        "medications": [
            {
                "START": "2026-10-01",
                "STOP": "",
                "PATIENT": "p",
                "CODE": "308192",
                "DESCRIPTION": "Amoxicillin 500 MG Oral Tablet",
                "DISPENSES": "1",
                "REASONCODE": "43878008",
            }
        ],
    }
    parsed = parse_member(
        source_record_id=member.source_record_id,
        source_system="CLINIC_CSV",
        source_local_id="CLINIC-7",
        kind=SourceKind.CSV_ROW,
        is_constructed=False,
        ingested_at=T0,
        raw_payload=payload,
    )
    assert len(parsed.encounters) == 1 and parsed.encounters[0].class_code == "ambulatory"
    assert [o.code.code for o in parsed.orders] == ["308192"] and parsed.orders[0].code.system == RXNORM


def test_csv_unknown_system_is_rxnorm_only_for_cached_codes():
    member = clinic_member(
        allergies=[csv_allergy_row(code="91930004", description="Animal dander (substance)"), csv_allergy_row()]
    )
    systems = {a.code.code: a.code.system for a in member.allergies}
    assert systems["7984"] == RXNORM and systems["91930004"] is None
    assert evaluate([member, HERO_ORDER]) and all(f.allergy.code.code == "7984" for f in evaluate([member, HERO_ORDER]))


def test_idless_fhir_resources_get_distinct_references():
    a1 = fhir_allergy()
    a2 = fhir_allergy(code="733", display="Ampicillin")
    del a1["id"], a2["id"]
    member = parse_member(
        source_record_id=ER,
        source_system="ER_FHIR",
        source_local_id="ER-MRN-1",
        kind=SourceKind.FHIR_PATIENT,
        is_constructed=False,
        ingested_at=T0,
        raw_payload={
            "resourceType": "Bundle",
            "entry": [{"resource": a1}, {"resource": a2}, {"resource": fhir_order()}],
        },
    )
    refs = {a.ref.resource_id for a in member.allergies}
    assert len(refs) == 2 and all(r.startswith("AllergyIntolerance/_") for r in refs)
    assert len({f.key for f in evaluate([member])}) == 2


# Codex review (PR #3) regressions -------------------------------------------------------


def test_eligibility_scans_every_coding_not_only_the_first():
    allergy = fhir_allergy()
    allergy["code"]["coding"].insert(
        0, {"system": "urn:local:allergens", "code": "PEN-V", "display": "Penicillin (local)"}
    )
    order = fhir_order()
    order["medicationCodeableConcept"]["coding"].insert(
        0, {"system": "urn:local:formulary", "code": "AMX500", "display": "Amox 500"}
    )
    (flag,) = evaluate([er_member(allergy, order)])
    assert flag.tier == AlertTier.A
    assert "coded penicillin V (RxNorm 7984;" in flag.card_text and "RxNorm 308192." in flag.card_text


def test_anaphylaxis_requires_the_snomed_system():
    local = fhir_allergy(reactions=())
    local["reaction"] = [
        {
            "manifestation": [
                {"coding": [{"system": "urn:local:reactions", "code": "39579001", "display": "Anaphylaxis"}]}
            ],
            "severity": "mild",
        }
    ]
    (flag,) = evaluate([er_member(local, fhir_order())])
    assert flag.tier == AlertTier.B, "a local system reusing the digits is not SNOMED anaphylaxis"
    snomed = fhir_allergy(reactions=(("39579001", "Anaphylaxis (disorder)", "mild"),))
    (flag,) = evaluate([er_member(snomed, fhir_order())])
    assert flag.tier == AlertTier.A and "reaction: anaphylaxis, mild" in flag.card_text


def test_contained_medication_reference_resolves():
    order = fhir_order()
    concept = order.pop("medicationCodeableConcept")
    order["medicationReference"] = {"reference": "#amox"}
    order["contained"] = [{"resourceType": "Medication", "id": "amox", "code": concept}]
    (flag,) = evaluate([er_member(fhir_allergy(), order)])
    assert flag.tier == AlertTier.A and "Amoxicillin 500 MG Oral Tablet, RxNorm 308192" in flag.card_text
    bundle_ref = fhir_order()
    bundle_ref.pop("medicationCodeableConcept")
    bundle_ref["medicationReference"] = {"reference": "urn:uuid:med-9"}
    (flag,) = evaluate(
        [er_member(fhir_allergy(), bundle_ref, {"resourceType": "Medication", "id": "med-9", "code": concept})]
    )
    assert flag.tier == AlertTier.A


def test_detected_issue_states_the_csv_order_rule():
    from backend.rule.bl_amox_01 import CSV_ORDER_NOTE

    (flag,) = flags_for([HERO_ALLERGY, HERO_ORDER], LINK)
    issue = detected_issue(to_safety_alert(flag, alert_id=ER, entity_id=CLINIC, identified_at=T0))
    assert CSV_ORDER_NOTE in issue["note"] and "derived from STOP" in CSV_ORDER_NOTE
