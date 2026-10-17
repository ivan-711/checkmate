"""Export the selected hero to ``data/scenarios/hero/`` in the contract shape.

``scenario.json`` starts from ``contracts.fixtures.build_fixtures.build_scenario()`` (the frozen shape)
and replaces every placeholder value with the engine's: records, scores, bands, what-ifs, held-out
recall, thresholds, the constructed overlay's resource ids and ``hero.provisional`` per the run.
``hero.json`` carries the raw records and what-if results; ``frontdesk_intake.json`` the ES/EN
utterances and expected ``propose_new_chart`` arguments (architecture section 9.1 step 6).
Timestamps are fixed and floats rounded so CI can regenerate and diff the files.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from contracts.fixtures.build_fixtures import FEATURES, T0, build_scenario
from contracts.models.common import Band
from contracts.models.whatifs import WhatIfButton
from data.hero_overlay import PROVENANCE_SENTENCE, write_overlay
from data.hero_select import whatif_year_direction
from eval.harness import whatifs
from eval.harness.standin import block_keys, display_p, fold
from eval.harness.types import BAND_KEEP_SEPARATE, Record

if TYPE_CHECKING:
    from data.hero_select import Candidate, HeroSelection, Scored
    from eval.harness.run import RunResult

NAMESPACE = uuid.UUID("6f1b4a3e-2c7d-4d0a-9a6e-5a1e00000000")  # fixed: record ids are stable across runs
BUTTON_FEATURE = {WhatIfButton.REMOVE_ADDRESS: "address_jaccard", WhatIfButton.CHANGE_BIRTH_YEAR: "dob_exact",
                  WhatIfButton.SWAP_DOB_DAY_MONTH: "dob_day_month_swap", WhatIfButton.ACCENT_HYPHEN_SURNAME: "family_name_jw"}
MONTHS_ES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
             "noviembre", "diciembre")
MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December")


def record_uuid(record_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE, record_id))


def source_card(rec: Record, label: str, constructed: bool) -> dict:
    rid = record_uuid(rec["record_id"])
    return {
        "record": {"id": rid, "sourceSystem": rec["source_system"], "sourceLocalId": rec["record_id"],
                   "kind": "FHIR_PATIENT" if rec["source_system"] == "ER_FHIR" else "CSV_ROW",
                   "payloadSha256": hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest(),
                   "isConstructed": constructed, "ingestedAt": T0.isoformat().replace("+00:00", "Z"), "rawPayload": None},
        "normalized": {"recordId": rid, "givenName": rec.get("given_name"), "familyName": rec.get("family_name"),
                       "givenNameFolded": fold(rec.get("given_name")) or None,
                       "familyNameFolded": fold(rec.get("family_name")) or None,
                       "birthDate": rec.get("birth_date"), "sex": rec.get("sex"), "phoneE164": rec.get("phone"),
                       "addressLine": rec.get("address_line"), "zip5": rec.get("zip5")},
        "displayLabel": label,
    }


def feature_value(s: Scored, f: str) -> float | None:
    """The feature value when the scorer reports it; otherwise inferred from the logit (0 reads as missing)."""
    if s.features:
        return s.features.get(f)
    return None if s.contributions.get(f, 0.0) == 0.0 else 1.0


def contributions(s: Scored) -> list[dict]:
    return [{"feature": f, "logit": s.contributions.get(f, 0.0), "value": feature_value(s, f)} for f in FEATURES]


def score_state(s: Scored) -> dict:
    return {"p": s.p, "rawScore": s.raw_score, "band": s.band, "contributions": contributions(s),
            "negativeRulesFired": list(s.negative_rules_fired)}


def held_out_recall(numbers: dict) -> list[dict]:
    out = []
    for button in WhatIfButton:
        cell = numbers.get(f"button.{button.value}.recall.lenient", {})
        out.append({"button": button.value, "category": "+".join(whatifs.BUTTON_CATEGORIES[button.value]),
                    "recall": cell.get("value"), "nPairs": cell.get("n_pairs", 0), "nEntities": cell.get("n_entities", 0),
                    "nComponents": cell.get("n_components", 0), "lowSupport": bool(cell.get("low_support", True))})
    return out


def _whatif_key(button: WhatIfButton, hero: Candidate) -> str:
    if button is WhatIfButton.CHANGE_BIRTH_YEAR:
        return f"{whatifs.CHANGE_BIRTH_YEAR}:{'+1' if whatif_year_direction(hero) > 0 else '-1'}"
    return button.value


def utterances(er: Record) -> dict[str, str]:
    y, m, d = (int(x) for x in er["birth_date"].split("-"))
    name = f"{er['given_name']} {er['family_name']}"
    es = f"Me llamo {name}, nací el {d} de {MONTHS_ES[m - 1]} de {y}"
    en = f"My name is {name}, born {MONTHS_EN[m - 1]} {d}, {y}"
    if er.get("phone"):
        es += f", mi teléfono es {er['phone']}"
        en += f", my phone is {er['phone']}"
    if er.get("address_line"):
        es += f", vivo en {er['address_line']}"
        en += f", I live at {er['address_line']}"
    return {"utteranceEs": es + ".", "utteranceEn": en + "."}


def export(selection: HeroSelection, result: RunResult, out: Path, provisional: bool,
           hero: Candidate | None = None) -> None:
    """``hero`` overrides the selection's hero (the best partial when nothing qualified)."""
    hero = hero or selection.hero
    assert hero is not None
    qualified = selection.ok and hero is selection.hero
    by_id = result.corpus.record_by_id()
    er, clinic = by_id[hero.er_record_id], by_id[hero.clinic_record_id]
    scenario = build_scenario()
    thresholds_id = selection.thresholds_id
    scorer = selection.scorer_version
    c_low, c_high = selection.c_low, selection.c_high
    er_card, clinic_card = source_card(er, "ER FHIR", True), source_card(clinic, "Clinic CSV", False)
    er_id, clinic_id = er_card["record"]["id"], clinic_card["record"]["id"]
    pair_id = str(uuid.uuid5(NAMESPACE, f"pair:{hero.entity_id}"))
    decision_id = str(uuid.uuid5(NAMESPACE, f"decision:{hero.entity_id}"))
    entity_id = str(uuid.uuid5(NAMESPACE, f"entity:{hero.entity_id}"))
    alert_id = str(uuid.uuid5(NAMESPACE, f"alert:{hero.entity_id}"))
    # the constructed overlay (Synthea data plan section 4) is written first; the scenario cites its ids
    overlay = write_overlay(out, hero.entity_id, er, clinic, natural_allergies=clinic.get("allergies"))
    allergy_ref, order_ref = overlay.allergy_resource_id, overlay.order_resource_id

    scenario["placeholder"] = False
    scenario["watermark"] = (f"engine export by data/hero_select.py: {'PROVISIONAL' if provisional else 'FINAL'} hero "
                             f"{hero.entity_id}{'' if qualified else ' (best partial; see hero.unmetCriteria)'}; "
                             f"scorer {scorer}; thresholds {thresholds_id}; seed {selection.seed}")
    scenario["hero"] = {"provisional": provisional, "constructedFloor": False, "selectedBy": "data/hero_select.py",
                        "qualified": qualified, "unmetCriteria": hero.unmet(), "criteriaLevel": hero.level,
                        "criteriaRequired": list(hero.required),
                        "criteria": {k: hero.criteria[k] for k in hero.criteria}, "criteriaText": selection.criteria,
                        "relaxationLevel": selection.relaxation_level, "drawnFromTest": selection.drawn_from_test,
                        "seed": selection.seed, "entityId": hero.entity_id, "scorerVersion": scorer,
                        "thresholdsId": thresholds_id, "poolSize": selection.pool_size,
                        "wording": "a selected showcase satisfying published criteria; aggregate metrics cover the full "
                                   "frozen test set"}
    session = scenario["session"]
    session.update(scorerVersion=scorer, thresholdSetId=thresholds_id, sources=[er_card, clinic_card],
                   heroProvisional=provisional, heroConstructedFloor=False)

    pair = scenario["pair"]
    base = hero.baseline
    decision = pair["pair"]["decision"]
    snapshot = decision["evidenceSnapshot"]
    snapshot.update(features={f: feature_value(base, f) for f in FEATURES},
                    missingFlags={f: feature_value(base, f) is None for f in FEATURES},
                    weights={f: result.weights.get(f, 0.0) for f in FEATURES}, intercept=result.weights.get("intercept", 0.0),
                    contributions=contributions(base), rawScore=base.raw_score, cLow=c_low, cHigh=c_high,
                    negativeRulesFired=list(base.negative_rules_fired), scorerVersion=scorer, thresholdSetId=thresholds_id)
    decision.update(id=decision_id, pairId=pair_id, logit=base.raw_score, p=base.p, band=base.band,
                    negativeRulesFired=list(base.negative_rules_fired), scorerVersion=scorer, thresholdSetId=thresholds_id)
    pair["pair"].update(id=pair_id, recordAId=er_id, recordBId=clinic_id,
                        blockKeys=sorted(set(block_keys(er)) & set(block_keys(clinic))))
    pair.update(recordA=er_card, recordB=clinic_card, contributions=contributions(base), history=[decision])
    pair["mergePreview"].update(entityIdIfApproved=entity_id, memberCountIfApproved=2, alertWouldFire=True)

    entity = scenario["entityIfApproved"]
    entity["id"] = entity_id
    entity["members"] = [{"sourceRecordId": er_id, "sourceSystem": "ER_FHIR", "isConstructed": True, "verification": None},
                         {"sourceRecordId": clinic_id, "sourceSystem": "CLINIC_CSV", "isConstructed": False, "verification": None}]

    def golden(field_name, value, system, rule, alternate=None):
        src_id = er["record_id"] if system == "ER_FHIR" else clinic["record_id"]
        g = {"field": field_name, "value": value, "crosswalk": {"sourceSystem": system, "sourceRecordId": src_id},
             "rule": rule, "alternates": []}
        if alternate is not None and alternate[0] != value:
            alt_id = er["record_id"] if alternate[1] == "ER_FHIR" else clinic["record_id"]
            g["alternates"] = [{"value": alternate[0], "crosswalk": {"sourceSystem": alternate[1], "sourceRecordId": alt_id}}]
        return g

    entity["golden"] = [
        golden("givenName", clinic["given_name"], "CLINIC_CSV", "MOST_FREQUENT", (er["given_name"], "ER_FHIR")),
        golden("familyName", clinic["family_name"], "CLINIC_CSV", "MOST_RECENT", (er["family_name"], "ER_FHIR")),
        golden("birthDate", er["birth_date"], "ER_FHIR", "MAJORITY", (clinic["birth_date"], "CLINIC_CSV")),
        golden("phone", er.get("phone") or clinic.get("phone"), "ER_FHIR" if er.get("phone") else "CLINIC_CSV", "MOST_RECENT"),
    ]
    for ev in scenario["timelineIfApproved"]:
        ev["entityId"] = entity_id
        if ev["type"] == "ALLERGY":
            ev.update(sourceRecordId=clinic_id, resourceId=allergy_ref)
        else:
            ev.update(sourceRecordId=er_id, resourceId=order_ref)
    alert = scenario["alertIfApproved"]
    alert.update(id=alert_id, entityId=entity_id)
    alert["allergyRef"].update(sourceRecordId=clinic_id, resourceId=allergy_ref)
    alert["orderRef"].update(sourceRecordId=er_id, resourceId=order_ref)
    alert["cardText"] = (alert["cardText"].replace("allergies.csv row PLACEHOLDER", f"allergies.csv row {overlay.clinic_patient_id}")
                         .replace("MedicationRequest/PLACEHOLDER", order_ref))
    scenario["thresholds"].update(thresholdsId=thresholds_id, cLow=c_low, cHigh=c_high,
                                  tLowDisplay=round(display_p(c_low, {}), 6), tHighDisplay=round(display_p(c_high, {}), 6),
                                  autoLinkEnabled=False, isCalibrated=False, sourceRunId=None)  # the selector's run dir is temporary
    recall = held_out_recall(result.numbers)
    baseline_state = score_state(base)
    scenario["whatIfs"] = {}
    for button in WhatIfButton:
        s = hero.what_ifs[_whatif_key(button, hero)]
        feat = BUTTON_FEATURE[button]
        scenario["whatIfs"][button.value] = {
            "baseline": baseline_state, "whatIf": score_state(s),
            "deltas": [{"feature": f, "logit": round(s.contributions.get(f, 0.0) - base.contributions.get(f, 0.0), 6), "value": None}
                       for f in FEATURES if abs(s.contributions.get(f, 0.0) - base.contributions.get(f, 0.0)) > 1e-9] or
                      [{"feature": feat, "logit": 0.0, "value": None}],
            "caption": whatifs.caption_for(button.value, base.band, s.band, s.p - base.p),
            "counterfactualFields": {feat: _counterfactual(button, er, hero)},
            "alertWouldBeHidden": s.band == BAND_KEEP_SEPARATE, "heldOutRecall": recall, "seed": selection.seed,
        }
    intake = utterances(er)
    scenario["frontdeskIntake"] = {
        "scenarioContextId": "hero-er-arrival", **intake,
        "expectedGate": {"tool": "propose_new_chart", "outcome": "DENY", "reasonCode": "CANDIDATE_IN_REVIEW_OR_HIGHER"},
    }
    (out / "scenario.json").write_text(json.dumps(scenario, indent=2, ensure_ascii=False) + "\n")
    (out / "hero.json").write_text(json.dumps({
        "entityId": hero.entity_id, "provisional": provisional, "qualified": qualified, "unmetCriteria": hero.unmet(),
        "scorerVersion": scorer, "thresholdsId": thresholds_id,
        "cLow": c_low, "cHigh": c_high, "records": {"ER_FHIR": er, "CLINIC_CSV": clinic},
        "baseline": asdict(base), "whatIfs": {k: asdict(v) for k, v in hero.what_ifs.items()}, "intake": asdict(hero.intake),
        "exportedWhatIfKeys": {b.value: _whatif_key(b, hero) for b in WhatIfButton},
        "criteria": hero.criteria, "criteriaLevel": hero.level, "criteriaRequired": list(hero.required),
        "weights": dict(result.weights),
        "constructedOverlay": {"allergyRef": allergy_ref, "orderRef": order_ref, "isConstructed": True,
                               "manifest": "scenario_manifest.json", "provenance": PROVENANCE_SENTENCE},
    }, indent=2, ensure_ascii=False) + "\n")
    (out / "frontdesk_intake.json").write_text(json.dumps({
        "scenarioContextId": "hero-er-arrival", **intake,
        "expectedProposeNewChartArgs": {
            "givenName": er["given_name"], "familyName": er["family_name"], "birthDate": er["birth_date"],
            "sex": er.get("sex"), "phone": er.get("phone"), "addressLine": er.get("address_line"), "postalCode": er.get("zip5"),
            "preferredLanguage": er.get("language", "EN"),
        },
        "expectedGate": {"tool": "propose_new_chart", "outcome": "DENY", "reasonCode": "CANDIDATE_IN_REVIEW_OR_HIGHER",
                         "evidenceRecordId": clinic_id},
        "loads": {"clinicRecord": clinic["record_id"], "erRecord": None,
                  "note": "the frontdesk-hero scenario loads the Clinic CSV record and decoys, not the ER record"},
        "constructedOrder": {"resourceId": order_ref, "attachedBy": "executor", "isConstructed": True},
    }, indent=2, ensure_ascii=False) + "\n")


def _counterfactual(button: WhatIfButton, er: Record, hero: Candidate) -> str | None:
    """The field value the exported what-if actually scored (the same birth-year direction as the score)."""
    if button is WhatIfButton.REMOVE_ADDRESS:
        return None
    if button is WhatIfButton.CHANGE_BIRTH_YEAR:
        return whatifs.change_birth_year(er, whatif_year_direction(hero))["birth_date"]
    if button is WhatIfButton.SWAP_DOB_DAY_MONTH:
        return whatifs.swap_dob_day_month(er)["birth_date"]
    return whatifs.accent_plus_hyphen(er)["family_name"]


def band_from(scenario: dict) -> Band:
    return Band(scenario["pair"]["pair"]["decision"]["band"])
