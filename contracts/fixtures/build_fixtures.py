"""Build the placeholder fixtures from the models so they can never drift from the contract.

``python -m contracts.fixtures.build_fixtures`` rewrites scenario.json and hard_negative.json.
Every value is a watermarked PLACEHOLDER. Real values come from the engine export after
W1-W3b land (provisional hero before 16:00, final hero after the 20:00 freeze).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from contracts.models.alerts import AlertStatus, AlertTier, Citation, ResourceRef, SafetyAlert
from contracts.models.common import ActorType, Band, Contribution, Crosswalk, DecisionStatus, PairOrigin
from contracts.models.entities import (
    Entity,
    EntityMember,
    GoldenAlternate,
    GoldenField,
    TimelineEvent,
    TimelineVerification,
)
from contracts.models.pairs import CandidatePair, CandidatePairDetail, EvidenceSnapshot, MatchDecision, MergePreview
from contracts.models.records import NormalizedRecord, SourceCard, SourceKind, SourceRecord
from contracts.models.sessions import SessionResponse
from contracts.models.thresholds import ThresholdSet
from contracts.models.tiles import Tile, TileBucket, TileId, TilesResponse
from contracts.models.whatifs import HeldOutRecall, ScoreState, WhatIfButton, WhatIfResponse
from contracts.version import REGISTRAR_LABELS

OUT = Path(__file__).parent
T0 = datetime(2026, 10, 17, 18, 0, tzinfo=UTC)
U = lambda n: UUID(f"00000000-0000-4000-8000-{n:012d}")
SCORER = "placeholder-scorer-0"
THRESH = "provisional-0"
C_LOW, C_HIGH = 0.0, 2.0

FEATURES = ["given_name_jw", "family_name_jw", "family_metaphone", "dob_exact", "dob_day_month_swap",
            "dob_one_digit_edit", "sex_match", "phone_match", "address_jaccard", "zip_match"]


def contribs(values: dict[str, float]) -> list[Contribution]:
    return [Contribution(feature=f, logit=values.get(f, 0.0), value=None if f not in values else 1.0) for f in FEATURES]


def snapshot(raw: float, c: list[Contribution], rules: list[str]) -> EvidenceSnapshot:
    return EvidenceSnapshot(
        features={f: (None if x.value is None else x.value) for f, x in zip(FEATURES, c)},
        missing_flags={f: x.value is None for f, x in zip(FEATURES, c)},
        weights={f: 1.0 for f in FEATURES}, intercept=-2.0, contributions=c, raw_score=raw,
        c_low=C_LOW, c_high=C_HIGH, negative_rules_fired=rules, scorer_version=SCORER, threshold_set_id=THRESH,
    )


def card(n: int, system: str, kind: SourceKind, label: str, given: str, family: str, dob: str, addr: str | None,
         constructed: bool = False) -> SourceCard:
    rec = SourceRecord(id=U(n), source_system=system, source_local_id=f"PLACEHOLDER-{n}", kind=kind,
                       payload_sha256="0" * 64, is_constructed=constructed, ingested_at=T0)
    norm = NormalizedRecord(record_id=U(n), given_name=given, family_name=family,
                            given_name_folded=given.lower(), family_name_folded=family.lower(),
                            birth_date=dob, sex="FEMALE", phone_e164="+15555550100", address_line=addr, zip5="54311")
    return SourceCard(record=rec, normalized=norm, display_label=label)


def pair_detail(n: int, a: SourceCard, b: SourceCard, raw: float, p: float, band: Band, rules: list[str],
                origin: PairOrigin, status: DecisionStatus, actor: str, actor_type: ActorType,
                alert_would_fire: bool, c: list[Contribution]) -> CandidatePairDetail:
    dec = MatchDecision(id=U(n + 1), pair_id=U(n), version=1, logit=raw, p=p, band=band, negative_rules_fired=rules,
                        status=status, actor=actor, actor_type=actor_type, decided_at=T0, scorer_version=SCORER,
                        threshold_set_id=THRESH, evidence_snapshot=snapshot(raw, c, rules))
    pair = CandidatePair(id=U(n), record_a_id=a.record.id, record_b_id=b.record.id,
                         block_keys=["metaphone_surname_birth_year:PLACEHOLDER"], origin=origin, decision=dec)
    return CandidatePairDetail(pair=pair, record_a=a, record_b=b, contributions=c, history=[dec],
                               merge_preview=MergePreview(entity_id_if_approved=U(900), member_count_if_approved=2,
                                                          alert_would_fire=alert_would_fire))


def build_scenario() -> dict:
    er = card(1, "ER_FHIR", SourceKind.FHIR_PATIENT, "ER FHIR", "PLACEHOLDER-GIVEN", "PLACEHOLDER-FAMILY",
              "1985-07-03", "100 Placeholder St", constructed=True)
    clinic = card(2, "CLINIC_CSV", SourceKind.CSV_ROW, "Clinic CSV", "PLACEHOLDER-GIVEN", "PLACEHOLDER FAMILY",
                  "1985-07-03", "100 Placeholder St")
    base_c = contribs({"given_name_jw": 0.9, "family_name_jw": 0.6, "family_metaphone": 0.5, "dob_exact": 0.8,
                       "sex_match": 0.2, "phone_match": 0.4, "address_jaccard": 0.7, "zip_match": 0.3})
    base_raw, base_p = 1.0, 0.73
    detail = pair_detail(10, er, clinic, base_raw, base_p, Band.REVIEW, [], PairOrigin.MATCH_RUN,
                         DecisionStatus.PROPOSED, "system:scorer", ActorType.SYSTEM, True, base_c)

    session = SessionResponse(id=U(100), scenario_id="hero", scorer_version=SCORER, threshold_set_id=THRESH,
                              created_at=T0, sources=[er, clinic], hero_provisional=True, hero_constructed_floor=True)

    def gf(field, value, src, rule, alt=None):
        return GoldenField(field=field, value=value, crosswalk=Crosswalk(source_system=src, source_record_id=f"PLACEHOLDER-{1 if src=='ER_FHIR' else 2}"),
                           rule=rule, alternates=[] if alt is None else [GoldenAlternate(value=alt[0], crosswalk=Crosswalk(source_system=alt[1], source_record_id="PLACEHOLDER-x"))])

    entity = Entity(id=U(900), version=1, members=[
        EntityMember(source_record_id=er.record.id, source_system="ER_FHIR", is_constructed=True),
        EntityMember(source_record_id=clinic.record.id, source_system="CLINIC_CSV")],
        golden=[gf("givenName", "PLACEHOLDER-GIVEN", "CLINIC_CSV", "MOST_FREQUENT"),
                gf("familyName", "PLACEHOLDER FAMILY", "CLINIC_CSV", "MOST_RECENT", ("PLACEHOLDER-FAMILY", "ER_FHIR")),
                gf("birthDate", "1985-07-03", "ER_FHIR", "MAJORITY"),
                gf("phone", "+15555550100", "ER_FHIR", "MOST_RECENT")])

    timeline = [
        TimelineEvent(entity_id=U(900), occurred_at=datetime(2024, 3, 2, tzinfo=UTC), type="ALLERGY",
                      codes=["RxNorm:7984"], display="Allergy to penicillin V (reaction: anaphylaxis, severe)",
                      source_record_id=clinic.record.id, source_system="CLINIC_CSV", resource_id="allergies.csv:PLACEHOLDER",
                      verification=TimelineVerification.CSV_DERIVED),
        TimelineEvent(entity_id=U(900), occurred_at=T0, type="MEDICATION_ORDER", codes=["RxNorm:308192"],
                      display="Amoxicillin 500 MG Oral Tablet (active order)", source_record_id=er.record.id,
                      source_system="ER_FHIR", resource_id="MedicationRequest/PLACEHOLDER",
                      verification=TimelineVerification.CODED, is_constructed=True),
    ]

    alert = SafetyAlert(
        id=U(950), entity_id=U(900), tier=AlertTier.A,
        allergy_ref=ResourceRef(source_record_id=clinic.record.id, source_system="CLINIC_CSV", resource_id="allergies.csv:PLACEHOLDER"),
        order_ref=ResourceRef(source_record_id=er.record.id, source_system="ER_FHIR", resource_id="MedicationRequest/PLACEHOLDER"),
        revealed_by_merge=True, status=AlertStatus.PRELIMINARY, constructed_scenario=True, identified_at=T0,
        card_text=("Flagged for clinician review. Two records that were previously separate are now linked to this patient "
                   "by an approved identity link. [Clinic CSV, allergies.csv row PLACEHOLDER] documents an allergy coded "
                   "penicillin V (RxNorm 7984; status active; verification not stated in source; reaction: anaphylaxis, severe). "
                   "This rule treats that code as penicillin-class. [ER FHIR, MedicationRequest/PLACEHOLDER] has an active "
                   "order for amoxicillin 500 MG Oral Tablet, RxNorm 308192. The amoxicillin label (DailyMed, set "
                   "d5eba477-e255-4d97-9e16-30543c298680, revised 3/2023) states: \"contraindicated in patients with a history "
                   "of serious hypersensitivity reactions (e.g., anaphylaxis or Stevens-Johnson syndrome) to amoxicillin, "
                   "clavulanate or to other beta-lactam antibacterial drugs (e.g., penicillins and cephalosporins)\". "
                   "This is a rule-based flag on synthetic data. It does not say what the patient took or tolerated, or what "
                   "should be prescribed. A clinician decides."),
        citation=Citation(label_name="Amoxicillin for oral suspension (Proficient Rx)", set_id="d5eba477-e255-4d97-9e16-30543c298680",
                          revised="3/2023", url="https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=d5eba477-e255-4d97-9e16-30543c298680",
                          quote=("contraindicated in patients with a history of serious hypersensitivity reactions (e.g., anaphylaxis "
                                 "or Stevens-Johnson syndrome) to amoxicillin, clavulanate or to other beta-lactam antibacterial drugs "
                                 "(e.g., penicillins and cephalosporins)")),
    )

    thresholds = ThresholdSet(thresholds_id=THRESH, c_low=C_LOW, c_high=C_HIGH, auto_link_enabled=False, is_calibrated=False)

    def tile(tid, agg, series):
        buckets = [TileBucket(bucket=T0, series=s, count=n) for s, n in series]
        return Tile(id=tid, aggregate=agg, window_minutes=60, buckets=buckets, total=sum(n for _, n in series))

    tiles = TilesResponse(as_of=T0, tiles=[
        tile(TileId.DECISION_FLOW, "band_flow_1m", [("REVIEW", 0), ("KEEP_SEPARATE", 0), ("AUTO_LINK", 0)]),
        tile(TileId.HUMAN_REVIEW, "review_outcomes_5m", [("APPROVED", 0), ("REJECTED", 0)]),
        tile(TileId.AGENT_GATE, "agent_gate_5m", [("ALLOW", 0), ("DENY", 0)]),
    ])

    baseline = ScoreState(p=base_p, raw_score=base_raw, band=Band.REVIEW, contributions=base_c)
    recall = [HeldOutRecall(button=b, category=f"PLACEHOLDER-{b.value}", recall=None, n_pairs=0, n_entities=0, n_components=0, low_support=True)
              for b in WhatIfButton]
    what_ifs = {}
    spec = {  # button: (raw, p, band, caption, hidden, changed feature)
        WhatIfButton.REMOVE_ADDRESS: (-0.6, 0.35, Band.KEEP_SEPARATE, "Without the address there is not enough to link.", True, "address_jaccard"),
        WhatIfButton.CHANGE_BIRTH_YEAR: (-0.9, 0.29, Band.KEEP_SEPARATE, "A different birth year: not enough to link.", True, "dob_exact"),
        WhatIfButton.SWAP_DOB_DAY_MONTH: (0.95, 0.72, Band.REVIEW, "Day and month swapped: the engine has a named feature for this; the score barely moves.", False, "dob_day_month_swap"),
        WhatIfButton.ACCENT_HYPHEN_SURNAME: (0.97, 0.72, Band.REVIEW, "Accents and hyphens changed: a named feature; the score barely moves.", False, "family_name_jw"),
    }
    for b, (raw, p, band, caption, hidden, feat) in spec.items():
        what_ifs[b.value] = WhatIfResponse(
            baseline=baseline, what_if=ScoreState(p=p, raw_score=raw, band=band, contributions=base_c),
            deltas=[Contribution(feature=feat, logit=raw - base_raw)], caption=caption,
            counterfactual_fields={feat: "PLACEHOLDER"}, alert_would_be_hidden=hidden, held_out_recall=recall, seed=20261017,
        ).model_dump(by_alias=True, mode="json")

    return {
        "placeholder": True,
        "watermark": "PLACEHOLDER: engine export replaces this file (provisional hero before 16:00, final at 20:00)",
        "hero": {"provisional": True, "constructedFloor": True, "selectedBy": None, "criteria": None},
        "registrarLabels": list(REGISTRAR_LABELS),
        "session": session.model_dump(by_alias=True, mode="json"),
        "pair": detail.model_dump(by_alias=True, mode="json"),
        "entityIfApproved": entity.model_dump(by_alias=True, mode="json"),
        "timelineIfApproved": [t.model_dump(by_alias=True, mode="json") for t in timeline],
        "alertIfApproved": alert.model_dump(by_alias=True, mode="json"),
        "thresholds": thresholds.model_dump(by_alias=True, mode="json"),
        "tiles": tiles.model_dump(by_alias=True, mode="json"),
        "whatIfs": what_ifs,
        "frontdeskIntake": {
            "scenarioContextId": "hero-er-arrival",
            "utteranceEs": "Me llamo PLACEHOLDER-GIVEN PLACEHOLDER FAMILY, nací el 3 de julio de 1985.",
            "utteranceEn": "My name is PLACEHOLDER-GIVEN PLACEHOLDER FAMILY, born July 3, 1985.",
            "expectedGate": {"tool": "propose_new_chart", "outcome": "DENY", "reasonCode": "CANDIDATE_IN_REVIEW_OR_HIGHER"},
        },
    }


def build_hard_negative() -> dict:
    a = card(21, "ER_FHIR", SourceKind.FHIR_PATIENT, "ER FHIR", "PLACEHOLDER-TWIN-A", "PLACEHOLDER-FAMILY", "1985-07-03", "100 Placeholder St")
    b = card(22, "CLINIC_CSV", SourceKind.CSV_ROW, "Clinic CSV", "PLACEHOLDER-TWIN-B", "PLACEHOLDER-FAMILY", "1985-07-03", "100 Placeholder St")
    c = contribs({"given_name_jw": 0.2, "family_name_jw": 0.9, "family_metaphone": 0.5, "dob_exact": 0.8,
                  "sex_match": 0.2, "phone_match": 0.4, "address_jaccard": 0.7, "zip_match": 0.3})
    # raw score below c_low (0.0): KEEP_SEPARATE on the cutoff itself; TWIN is listed as fired so the UI shows the rule,
    # but negative rules only ever demote AUTO_LINK to REVIEW (architecture §3 S6), never produce KEEP_SEPARATE.
    detail = pair_detail(30, a, b, -0.6, 0.35, Band.KEEP_SEPARATE, ["TWIN"], PairOrigin.MATCH_RUN,
                         DecisionStatus.PROPOSED, "system:scorer", ActorType.SYSTEM, False, c)
    return {"placeholder": True, "kind": "HARD_NEGATIVE_TWIN",
            "note": "Same surname, DOB, address and phone; different given names: the TWIN rule keeps them separate.",
            "pair": detail.model_dump(by_alias=True, mode="json")}


def main() -> None:
    (OUT / "scenario.json").write_text(json.dumps(build_scenario(), indent=2, ensure_ascii=False) + "\n")
    (OUT / "hard_negative.json").write_text(json.dumps(build_hard_negative(), indent=2, ensure_ascii=False) + "\n")
    print("fixtures written")


if __name__ == "__main__":
    main()
