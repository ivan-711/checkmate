"""R3b reviewer tests for rule BL-AMOX-01 v1, written from the spec (evaluation doc section 5),
not from the builder's test file. The 18-row table, the attack cases, the exact card text,
the say/never-say list, the DetectedIssue shape and the no-network guarantee.
"""
from __future__ import annotations

import json
import re
import socket
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from backend.link.union_find import components
from backend.rule import bl_amox_01 as rule
from backend.rule.resources import MemberResources, parse_member
from backend.rule.terminology import load_terminology
from contracts.models.alerts import CARD_FOOTER, AlertTier
from contracts.models.common import SourceKind

T0 = datetime(2026, 10, 17, 18, 0, tzinfo=UTC)
ER_ID = UUID("11111111-0000-4000-8000-000000000001")
CLINIC_ID = UUID("22222222-0000-4000-8000-000000000002")
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
SNOMED = "http://snomed.info/sct"
ANAPHYLAXIS = "39579001"

# Verbatim from the spec (section 5, "Exact card text", "Non-reveal template", "Tier B card",
# "Card footer", citations). Bracketed placeholders only.
SPEC_TIER_A = (
    "Flagged for clinician review. Two records that were previously separate are now linked to this patient by an "
    "approved identity link. [Clinic CSV, allergies.csv row [id]] documents an allergy coded [penicillin V] (RxNorm 7984; "
    "status active; verification [confirmed / unconfirmed / not stated in source]; reaction: [anaphylaxis, severe]). "
    "This rule treats that code as penicillin-class. [ER FHIR, MedicationRequest/[id]] has an active order for "
    "[amoxicillin 500 MG Oral Tablet], RxNorm 308192. The [amoxicillin/clavulanate] label (DailyMed, set [id], revised "
    '[date]) states: "[verbatim section 4 quote]". This is a rule-based flag on synthetic data. It does not say what the '
    "patient took or tolerated, or what should be prescribed. A clinician decides."
)
SPEC_NON_REVEAL_FIRST = "Both records come from the same source."
SPEC_TIER_B_HEADLINE = "Possible conflict, flagged for clinician review."
SPEC_TIER_B_REACTION = "The documented reaction is [mild/moderate/not recorded]; this rule cannot tell whether it is serious."
SPEC_FOOTER = (
    "Rule BL-AMOX-01 v1. Not checked: cephalosporin cross-reactivity, intolerances, dose, free-text allergies. "
    "Absence of a flag is not evidence that no conflict exists. This rule and its wording were not reviewed by a clinician."
)
SPEC_QUOTE = (
    "contraindicated in patients with a history of serious hypersensitivity reactions (e.g., anaphylaxis or "
    "Stevens-Johnson syndrome) to amoxicillin, clavulanate or to other beta-lactam antibacterial drugs (e.g., "
    "penicillins and cephalosporins)"
)
NEVER_SAY = (
    "prevented", "would have died", "the AI caught", "alert stopped", "contraindicated for this patient", "diagnosed",
    "held", "automatically canceled", "AI decided", "blocked", "fatal", "saved a life", "the patient is allergic",
)
MUST_SAY = ("flagged for clinician review", "rule-based flag on synthetic data", "A clinician decides.")


def template_regex(template: str) -> re.Pattern:
    """Innermost bracketed placeholders become wildcards; every other character must match exactly."""
    escaped = re.escape(template)
    return re.compile(re.sub(r"\\\[([^\[\]]*?)\\\]", "(.+?)", escaped), re.DOTALL)


# Builders -------------------------------------------------------------------------------

def fhir_allergy(*, code="7984", display="Penicillin V", system=RXNORM, type_="allergy", clinical="active",
                 verification: str | None = "confirmed", criticality: str | None = "low",
                 reactions=((ANAPHYLAXIS, "Anaphylaxis (disorder)", "severe"),), rid="al-1") -> dict:
    r: dict = {"resourceType": "AllergyIntolerance", "id": rid,
               "clinicalStatus": {"coding": [{"code": clinical}]},
               "category": ["medication"],
               "code": {"coding": [{"system": system, "code": code, "display": display}]},
               "recordedDate": "2024-03-02T10:00:00Z",
               "reaction": [{"manifestation": [{"coding": [{"system": SNOMED, "code": mc, "display": md}]}],
                             **({"severity": sev} if sev else {})} for mc, md, sev in reactions]}
    if verification is not None:
        r["verificationStatus"] = {"coding": [{"code": verification}]}
    if criticality is not None:
        r["criticality"] = criticality
    if type_ is not None:
        r["type"] = type_
    return r


def fhir_order(*, code="308192", display="Amoxicillin 500 MG Oral Tablet", status="active", intent="order",
               rid="mr-1", constructed=False) -> dict:
    r = {"resourceType": "MedicationRequest", "id": rid, "status": status, "intent": intent,
         "medicationCodeableConcept": {"coding": [{"system": RXNORM, "code": code, "display": display}]},
         "authoredOn": "2026-10-17T15:00:00Z", "requester": {"display": "Dr. Example"}}
    if constructed:
        r["meta"] = {"tag": [{"system": "urn:chartguard:provenance", "code": "constructed-scenario"}]}
    return r


def bundle(*resources: dict) -> dict:
    return {"resourceType": "Bundle", "type": "transaction",
            "entry": [{"resource": {"resourceType": "Patient", "id": "p"}}, *({"resource": r} for r in resources)]}


def er(*resources: dict, record_id: UUID = ER_ID, constructed=False) -> MemberResources:
    return parse_member(source_record_id=record_id, source_system="ER_FHIR", source_local_id="ER-1",
                        kind=SourceKind.FHIR_PATIENT, is_constructed=constructed, ingested_at=T0, raw_payload=bundle(*resources))


def csv_allergy(*, code="7984", description="Penicillin V", stop="", type_="allergy", severity1="SEVERE",
                reaction1=ANAPHYLAXIS, description1="Anaphylaxis (disorder)", severity2="", reaction2="",
                description2="") -> dict:
    # allergies.csv header (Synthea, Nov 2021 sample): no verification, no criticality.
    return {"START": "2024-03-02", "STOP": stop, "PATIENT": "p", "ENCOUNTER": "e", "CODE": code, "SYSTEM": "Unknown",
            "DESCRIPTION": description, "TYPE": type_, "CATEGORY": "medication", "REACTION1": reaction1,
            "DESCRIPTION1": description1, "SEVERITY1": severity1, "REACTION2": reaction2, "DESCRIPTION2": description2,
            "SEVERITY2": severity2}


def csv_order(*, code="308192", description="Amoxicillin 500 MG Oral Tablet", stop="") -> dict:
    return {"START": "2026-10-01", "STOP": stop, "PATIENT": "p", "CODE": code, "DESCRIPTION": description,
            "DISPENSES": "1", "TOTALCOST": "1.0", "REASONCODE": ""}


def clinic(allergies=(), medications=(), record_id: UUID = CLINIC_ID) -> MemberResources:
    payload = {"Id": "p", "allergies": list(allergies), "medications": list(medications), "encounters": []}
    return parse_member(source_record_id=record_id, source_system="CLINIC_CSV", source_local_id="C-7",
                        kind=SourceKind.CSV_ROW, is_constructed=False, ingested_at=T0, raw_payload=payload)


def flags(members: list[MemberResources], approved_edges: list[tuple[UUID, UUID]]):
    """Identity gate as the service does it: components over human-approved edges, then the rule per component."""
    by_id = {m.source_record_id: m for m in members}
    out = []
    for comp in {c for c in components(approved_edges, by_id).values()}:
        out.extend(rule.evaluate([by_id[i] for i in sorted(comp, key=str)]))
    return out


HERO_ALLERGY = clinic(allergies=[csv_allergy()])
HERO_ORDER = er(fhir_order(constructed=True), constructed=True)
LINK = [(CLINIC_ID, ER_ID)]


# The 18-row table -------------------------------------------------------------------------

TABLE = {
    "01 severe reaction, active amoxicillin, approved link: A": ([HERO_ALLERGY, HERO_ORDER], LINK, ["A"]),
    "02 same, unlinked: none": ([HERO_ALLERGY, HERO_ORDER], [], []),
    "03a allergy source alone: none": ([HERO_ALLERGY], [], []),
    "03b order source alone: none": ([HERO_ORDER], [], []),
    "04 after split (edge gone): none": ([HERO_ALLERGY, HERO_ORDER], [], []),
    "05a inactive allergy (FHIR): none": ([er(fhir_allergy(clinical="inactive")), clinic(medications=[csv_order()])], LINK, []),
    "05b inactive allergy (CSV STOP set): none": ([clinic(allergies=[csv_allergy(stop="2025-01-01")]), HERO_ORDER], LINK, []),
    "06 refuted: none": ([er(fhir_allergy(verification="refuted")), clinic(medications=[csv_order()])], LINK, []),
    "06b entered-in-error: none": ([er(fhir_allergy(verification="entered-in-error")), clinic(medications=[csv_order()])], LINK, []),
    "07 intolerance: none": ([er(fhir_allergy(type_="intolerance")), clinic(medications=[csv_order()])], LINK, []),
    "08 order completed: none": ([HERO_ALLERGY, er(fhir_order(status="completed"))], LINK, []),
    "08b order stopped/cancelled/on-hold/entered-in-error: none": (
        [HERO_ALLERGY, er(fhir_order(status="stopped", rid="a"), fhir_order(status="cancelled", rid="b"),
                          fhir_order(status="on-hold", rid="c"), fhir_order(status="entered-in-error", rid="d"))], LINK, []),
    "09 penicillin allergy, doxycycline order: none": (
        [HERO_ALLERGY, er(fhir_order(code="1649988", display="doxycycline hyclate 100 MG Oral Tablet"))], LINK, []),
    "10 cephalosporin allergy only: none": (
        [clinic(allergies=[csv_allergy(code="2231", description="Cephalexin")]), HERO_ORDER], LINK, []),
    "11 mild reaction only: B": (
        [clinic(allergies=[csv_allergy(severity1="MILD", reaction1="271807003", description1="Eruption of skin (disorder)")]),
         HERO_ORDER], LINK, ["B"]),
    "12 allergy and order in one source: fires": ([er(fhir_allergy(), fhir_order())], [], ["A"]),
    "13 only path is an unapproved auto-link edge: none": ([HERO_ALLERGY, HERO_ORDER], [], []),
    "14 penicillin V allergy, penicillin V potassium order: A": (
        [HERO_ALLERGY, er(fhir_order(code="834061", display="Penicillin V Potassium 250 MG Oral Tablet"))], LINK, ["A"]),
    "15a order coded with PIN 1297882 (folds to 723): fires": (
        [HERO_ALLERGY, er(fhir_order(code="1297882", display="amoxicillin anhydrous"))], LINK, ["A"]),
    "15b order coded with SCD 308182 (folds to 723): fires": (
        [HERO_ALLERGY, er(fhir_order(code="308182", display="Amoxicillin 250 MG Oral Capsule"))], LINK, ["A"]),
    "16 order for a drug without a cached label: fires": (
        [HERO_ALLERGY, er(fhir_order(code="789980", display="Ampicillin 100 MG/ML Injectable Solution"))], LINK, ["A"]),
    "17 CSV allergy, no verification, SEVERITY1=SEVERE: A": ([HERO_ALLERGY, HERO_ORDER], LINK, ["A"]),
    "18 order draft: none": ([HERO_ALLERGY, er(fhir_order(status="draft"))], LINK, []),
}


@pytest.mark.parametrize("row", list(TABLE))
def test_spec_table(row):
    members, edges, expected = TABLE[row]
    assert [f.tier.value for f in flags(members, edges)] == expected


def test_row_04_split_retracts():
    assert len(flags([HERO_ALLERGY, HERO_ORDER], LINK)) == 1
    assert flags([HERO_ALLERGY, HERO_ORDER], []) == []


def test_row_12_same_source_non_reveal_template():
    (flag,) = flags([er(fhir_allergy(), fhir_order())], [])
    assert flag.revealed_by_merge is False
    # the spec template names the hero's sources; here both resources sit in one FHIR record, so the
    # two source references are placeholders too
    expected = SPEC_TIER_A.replace(
        "Two records that were previously separate are now linked to this patient by an approved identity link.",
        SPEC_NON_REVEAL_FIRST).replace("[Clinic CSV, allergies.csv row [id]]", "[source ref]").replace(
        "[ER FHIR, MedicationRequest/[id]]", "[source ref]")
    m = template_regex(expected).fullmatch(flag.card_text)
    assert m, flag.card_text
    assert m.group(1) == "[ER FHIR, AllergyIntolerance/al-1]" and m.group(5) == "[ER FHIR, MedicationRequest/mr-1]"
    assert "previously separate" not in flag.card_text


def test_row_16_no_cached_label_citation_line():
    (flag,) = flags([HERO_ALLERGY, er(fhir_order(code="789980", display="Ampicillin 100 MG/ML Injectable Solution"))], LINK)
    assert flag.tier == AlertTier.A and flag.citation is None
    assert "no cached label for this drug" in flag.card_text
    assert "states:" not in flag.card_text and SPEC_QUOTE not in flag.card_text


def test_row_17_csv_verification_not_stated():
    (flag,) = flags([HERO_ALLERGY, HERO_ORDER], LINK)
    assert flag.tier == AlertTier.A
    assert "verification not stated in source" in flag.card_text
    assert flag.allergy.verification_status is None and flag.allergy.criticality is None


# Attack cases ---------------------------------------------------------------------------

def test_allergy_with_type_missing_never_fires():
    assert flags([er(fhir_allergy(type_=None)), clinic(medications=[csv_order()])], LINK) == []
    assert flags([clinic(allergies=[csv_allergy(type_="")]), HERO_ORDER], LINK) == []


def test_order_active_with_intent_plan_never_fires():
    assert flags([HERO_ALLERGY, er(fhir_order(intent="plan"))], LINK) == []
    assert flags([HERO_ALLERGY, er(fhir_order(intent="proposal"))], LINK) == []
    assert [f.tier.value for f in flags([HERO_ALLERGY, er(fhir_order(intent="original-order"))], LINK)] == ["A"]


def test_cephalosporin_allergy_with_amoxicillin_order_never_fires():
    cef_fhir = er(fhir_allergy(code="2231", display="Cephalexin"))
    assert flags([cef_fhir, clinic(medications=[csv_order()])], LINK) == []
    # cefaclor, cefuroxime: other cephalosporin ingredients, same answer
    for code in ("2176", "2194"):
        assert flags([er(fhir_allergy(code=code, display="cephalosporin")), clinic(medications=[csv_order()])], LINK) == []


def test_non_rxnorm_allergen_is_out_of_scope():
    snomed_allergy = er(fhir_allergy(code="91936005", display="Allergy to penicillin", system=SNOMED))
    assert flags([snomed_allergy, clinic(medications=[csv_order()])], LINK) == []


def test_pin_order_folds_to_723():
    term = load_terminology()
    assert term.fold("1297882") == "723"
    (flag,) = flags([HERO_ALLERGY, er(fhir_order(code="1297882", display="amoxicillin anhydrous"))], LINK)
    assert flag.tier == AlertTier.A
    assert flag.citation is not None and flag.citation.quote == SPEC_QUOTE


def test_severe_on_second_reaction_only_is_tier_a():
    allergy = fhir_allergy(criticality="low",
                           reactions=(("271807003", "Eruption of skin (disorder)", "mild"),
                                      ("422587007", "Nausea (finding)", "severe")))
    (flag,) = flags([er(allergy), clinic(medications=[csv_order()])], LINK)
    assert flag.tier == AlertTier.A
    csv = csv_allergy(severity1="MILD", reaction1="271807003", description1="Eruption of skin (disorder)",
                      severity2="SEVERE", reaction2="422587007", description2="Nausea (finding)")
    (flag,) = flags([clinic(allergies=[csv]), HERO_ORDER], LINK)
    assert flag.tier == AlertTier.A


def test_anaphylaxis_code_without_severity_is_tier_a():
    allergy = fhir_allergy(criticality="low", reactions=((ANAPHYLAXIS, "Anaphylaxis (disorder)", None),))
    (flag,) = flags([er(allergy), clinic(medications=[csv_order()])], LINK)
    assert flag.tier == AlertTier.A


def test_criticality_high_alone_is_tier_a():
    (flag,) = flags([er(fhir_allergy(criticality="high", reactions=())), clinic(medications=[csv_order()])], LINK)
    assert flag.tier == AlertTier.A


def test_unconfirmed_is_allowed_and_shown():
    (flag,) = flags([er(fhir_allergy(verification="unconfirmed")), clinic(medications=[csv_order()])], LINK)
    assert "verification unconfirmed" in flag.card_text


def test_two_eligible_orders_give_one_flag_per_allergy_order_pair():
    member = er(fhir_order(rid="mr-1"), fhir_order(code="562251", display="Amoxicillin / Clavulanate", rid="mr-2"))
    out = flags([HERO_ALLERGY, member], LINK)
    # spec pseudocode: emit Flag for each (A, O); two orders -> two flags with distinct keys
    assert len(out) == 2 and len({f.key for f in out}) == 2
    assert {f.order.ref.resource_id for f in out} == {"MedicationRequest/mr-1", "MedicationRequest/mr-2"}


def test_tier_b_card_has_no_contraindication_quotation():
    (flag,) = flags([clinic(allergies=[csv_allergy(severity1="MODERATE", reaction1="271807003",
                                                   description1="Eruption of skin (disorder)")]), HERO_ORDER], LINK)
    assert flag.tier == AlertTier.B and flag.citation is None
    text = flag.card_text
    assert text.startswith(SPEC_TIER_B_HEADLINE + " ")
    assert "Two records that were previously separate are now linked to this patient by an approved identity link." in text
    assert '"' not in text and "states:" not in text and "DailyMed" not in text and "contraindicated" not in text
    assert "The documented reaction is moderate; this rule cannot tell whether it is serious." in text
    assert text.endswith("A clinician decides.")
    # not recorded
    (flag,) = flags([clinic(allergies=[csv_allergy(severity1="", reaction1="", description1="")]), HERO_ORDER], LINK)
    assert flag.tier == AlertTier.B and "The documented reaction is not recorded;" in flag.card_text


def test_tier_a_card_matches_the_spec_template_character_for_character():
    (flag,) = flags([HERO_ALLERGY, HERO_ORDER], LINK)
    m = template_regex(SPEC_TIER_A).fullmatch(flag.card_text)
    assert m, flag.card_text
    row_id, allergen, verification, reaction, mr_id, order_display, _label_drug, set_id, revised, quote = m.groups()
    assert row_id == "0" and mr_id == "mr-1"
    assert allergen == "penicillin V"
    assert verification == "not stated in source"
    assert reaction == "anaphylaxis, severe"
    assert order_display == "Amoxicillin 500 MG Oral Tablet"
    assert quote == SPEC_QUOTE, "label quoted verbatim, never paraphrased"
    assert flag.citation is not None and flag.citation.set_id == set_id and flag.citation.revised == revised
    assert set_id in {"d5eba477-e255-4d97-9e16-30543c298680", "f10634cb-6505-43f1-9b70-314c58673016"}


def test_amoxicillin_clavulanate_order_cites_the_clavulanate_label():
    (flag,) = flags([HERO_ALLERGY, er(fhir_order(code="562251", display="Amoxicillin 250 MG / Clavulanate 125 MG Oral Tablet"))], LINK)
    assert flag.citation.set_id == "f10634cb-6505-43f1-9b70-314c58673016" and flag.citation.revised == "10/2026"
    assert flag.citation.quote == SPEC_QUOTE


def test_footer_is_the_spec_text():
    assert CARD_FOOTER == SPEC_FOOTER
    alert = rule.to_safety_alert(flags([HERO_ALLERGY, HERO_ORDER], LINK)[0], alert_id=UUID(int=1), entity_id=UUID(int=2),
                                 identified_at=T0)
    assert alert.card_footer == SPEC_FOOTER


# Say / never say ------------------------------------------------------------------------

def every_flag():
    for members, edges, _ in TABLE.values():
        yield from flags(members, edges)


def test_every_card_says_the_say_words_and_none_of_the_never_say_words():
    seen = 0
    for flag in every_flag():
        seen += 1
        alert = rule.to_safety_alert(flag, alert_id=UUID(int=1), entity_id=UUID(int=2), identified_at=T0)
        rendered = " ".join([alert.card_text, alert.card_footer, json.dumps(rule.detected_issue(alert))])
        low = rendered.lower()
        for phrase in NEVER_SAY:
            assert phrase.lower() not in low, (phrase, rendered)
        for phrase in MUST_SAY:
            assert phrase.lower() in alert.card_text.lower(), (phrase, alert.card_text)
    assert seen == 8, "rows 1, 11, 12, 14, 15a, 15b, 16, 17 fire"


def test_source_files_contain_no_never_say_strings():
    root = Path(__file__).resolve().parents[3]
    files = [*(root / "backend").rglob("*.py"), root / "contracts" / "models" / "alerts.py"]
    files = [f for f in files if "tests" not in f.parts]
    banned = ("would have died", "the AI caught", "alert stopped", "contraindicated for this patient",
              "automatically canceled", "AI decided", "saved a life", "fatal prescription")
    for f in files:
        low = f.read_text().lower()
        for phrase in banned:
            assert phrase.lower() not in low, (f, phrase)


# Output shape ---------------------------------------------------------------------------

def test_detected_issue_shape():
    (flag,) = flags([HERO_ALLERGY, HERO_ORDER], LINK)
    alert = rule.to_safety_alert(flag, alert_id=UUID(int=5), entity_id=UUID(int=6), identified_at=T0)
    assert alert.severity == "moderate" and alert.status.value == "PRELIMINARY"
    assert alert.rule_id == "BL-AMOX-01" and alert.rule_version == "v1"
    assert alert.constructed_scenario is True
    issue = rule.detected_issue(alert)
    assert issue["resourceType"] == "DetectedIssue" and issue["status"] == "preliminary" and issue["severity"] == "moderate"
    assert issue["patient"]["reference"].endswith(str(alert.entity_id))
    assert [i["reference"].split("/")[0] for i in issue["implicated"]] == ["MedicationRequest", "allergies.csv:0"] or \
        issue["implicated"][0]["reference"].startswith("MedicationRequest/")
    assert issue["detail"] == alert.card_text and issue["reference"] == alert.citation.url
    assert issue["identifiedDateTime"] == T0.isoformat()
    assert issue["code"]["text"] and any(c["code"] == "BL-AMOX-01" for c in issue["code"]["coding"])
    tier_b = flags([clinic(allergies=[csv_allergy(severity1="MILD", reaction1="271807003",
                                                  description1="Eruption of skin (disorder)")]), HERO_ORDER], LINK)[0]
    b = rule.to_safety_alert(tier_b, alert_id=UUID(int=7), entity_id=UUID(int=6), identified_at=T0)
    assert b.severity == "moderate", "both tiers moderate: nothing renders as a time-critical alarm"
    assert rule.detected_issue(b)["reference"] is None


# No network -----------------------------------------------------------------------------

def test_rule_makes_no_network_call(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("network call attempted at rule runtime")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    load_terminology.cache_clear()
    try:
        term = load_terminology()
        out = rule.evaluate([HERO_ALLERGY, HERO_ORDER], term)
        assert len(out) == 1 and out[0].citation is not None
        assert rule.detected_issue(rule.to_safety_alert(out[0], alert_id=UUID(int=1), entity_id=UUID(int=2), identified_at=T0))
    finally:
        load_terminology.cache_clear()


def test_rule_modules_import_no_http_client():
    root = Path(__file__).resolve().parents[3] / "backend" / "rule"
    for f in root.rglob("*.py"):
        src = f.read_text()
        for name in ("httpx", "requests", "urllib", "aiohttp", "socket"):
            assert not re.search(rf"^\s*(import|from)\s+{name}\b", src, re.MULTILINE), (f, name)


def test_offline_cache_files_committed_with_provenance():
    cache = Path(__file__).resolve().parents[3] / "backend" / "rule" / "cache"
    klass = json.loads((cache / "penicillin_class.json").read_text())
    assert klass["class_id"] == "N0000175497" and klass["rxnav_version"] and klass["fetched"]
    assert {i["rxcui"] for i in klass["ingredients"]} >= {"7984", "733", "7980", "7233", "7773", "3356", "10591", "723"}
    assert klass["pin_to_in"]["1297882"] == "723"
    scd = json.loads((cache / "scd_to_ingredient.json").read_text())["codes"]
    assert set(scd["562251"]["ingredients"]) == {"723", "48203"}
    for name in ("308192", "308182", "617296", "562508", "834061"):
        assert name in scd
    labels = sorted((cache / "labels").glob("*.json"))
    assert {json.loads(p.read_text())["set_id"] for p in labels} == {
        "f10634cb-6505-43f1-9b70-314c58673016", "d5eba477-e255-4d97-9e16-30543c298680"}
    for p in labels:
        label = json.loads(p.read_text())
        assert label["quote"] == SPEC_QUOTE and label["revised"] and label["url"].startswith("https://dailymed.nlm.nih.gov/")
