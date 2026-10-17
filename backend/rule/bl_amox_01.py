"""Rule BL-AMOX-01 v1: penicillin-class allergy versus active penicillin-class order.

Spec: evaluation/synthea-and-clinical-rule.md section 5. The identity gate holds by
construction: ``evaluate`` only ever sees the members of one entity, and every LINKED
edge is human-approved (architecture section 10), so no path search happens here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from backend.rule.resources import (
    ALLERGY_FILE,
    MEDICATION_FILE,
    AllergyRecord,
    Coding,
    MemberResources,
    OrderRecord,
    SourceRef,
    is_anaphylaxis,
    is_rxnorm,
    strip_snomed_tag,
    worst_reaction,
)
from backend.rule.terminology import RXNORM_SYSTEM, Terminology, load_terminology
from contracts.models.alerts import CARD_FOOTER, AlertStatus, AlertTier, Citation, ResourceRef, SafetyAlert
from contracts.version import RULE_ID, RULE_VERSION

SEVERITY_MODERATE = "moderate"  # both tiers; nothing renders as a time-critical alarm
ELIGIBLE_ORDER_STATUSES = frozenset({"active"})
ELIGIBLE_ORDER_INTENTS = frozenset({"order", "original-order"})
INELIGIBLE_VERIFICATIONS = frozenset({"refuted", "entered-in-error"})
SERIOUS_CRITICALITY = "high"
SERIOUS_SEVERITY = "severe"
VERIFICATION_NOT_STATED = "not stated in source"
NO_CACHED_LABEL = "no cached label for this drug"
# Closed map from source system to the on-screen label (UX spec 3.1); unknown systems show their id.
SOURCE_LABELS = {"ER_FHIR": "ER FHIR", "CLINIC_CSV": "Clinic CSV", "SPECIALIST": "Specialist"}

HEADLINE_A = "Flagged for clinician review."
HEADLINE_B = "Possible conflict, flagged for clinician review."
REVEAL_SENTENCE = (
    "Two records that were previously separate are now linked to this patient by an approved identity link."
)
NON_REVEAL_SENTENCE = "Both records come from the same source."
CLASS_SENTENCE = "This rule treats that code as penicillin-class."
# Evidence panel statement (reviewer R3b, finding 9): the spec defines eligible orders on MedicationRequest;
# a medications.csv row is admitted on the adapter rule from section 4, and the panel says so.
CSV_ORDER_NOTE = (
    "A medications.csv row with an empty STOP is treated as an active order with intent order "
    "(CSV order status derived from STOP); a row with a STOP date is completed and never fires."
)
CLOSING = (
    "This is a rule-based flag on synthetic data. It does not say what the patient took or tolerated, "
    "or what should be prescribed. A clinician decides."
)


AlertKey = tuple[UUID, str, UUID, str, str]


def alert_key(
    allergy_record_id: UUID, allergy_resource_id: str, order_record_id: UUID, order_resource_id: str, tier: AlertTier
) -> AlertKey:
    """What makes two flags the same alert across re-evaluations; the service keys rows by it too."""
    return (allergy_record_id, allergy_resource_id, order_record_id, order_resource_id, tier.value)


@dataclass(frozen=True)
class RuleFlag:
    tier: AlertTier
    revealed_by_merge: bool
    allergy: AllergyRecord
    order: OrderRecord
    card_text: str
    citation: Citation | None
    constructed_scenario: bool

    @property
    def key(self) -> AlertKey:
        return alert_key(
            self.allergy.ref.source_record_id,
            self.allergy.ref.resource_id,
            self.order.ref.source_record_id,
            self.order.ref.resource_id,
            self.tier,
        )


# Eligibility ----------------------------------------------------------------------------


def class_coding(codings: tuple[Coding, ...], term: Terminology) -> Coding | None:
    """The first RxNorm coding that resolves into the penicillin class, scanning every coding."""
    return next((c for c in codings if is_rxnorm(c.system) and term.class_ingredients_of(c.code)), None)


def is_eligible_allergy(allergy: AllergyRecord, term: Terminology) -> bool:
    return (
        class_coding(allergy.codings, term) is not None
        and allergy.type == "allergy"
        and allergy.clinical_status == "active"
        and allergy.verification_status not in INELIGIBLE_VERIFICATIONS
    )


def is_eligible_order(order: OrderRecord, term: Terminology) -> bool:
    return (
        class_coding(order.codings, term) is not None
        and order.status in ELIGIBLE_ORDER_STATUSES
        and order.intent in ELIGIBLE_ORDER_INTENTS
    )


def is_serious(allergy: AllergyRecord) -> bool:
    return (
        allergy.criticality == SERIOUS_CRITICALITY
        or any(r.severity == SERIOUS_SEVERITY for r in allergy.reactions)
        or any(is_anaphylaxis(r) for r in allergy.reactions)
    )


# Card text ------------------------------------------------------------------------------


def source_label(source_system: str) -> str:
    return SOURCE_LABELS.get(source_system, source_system)


def _ref_text(ref: SourceRef, csv_file: str) -> str:
    label = source_label(ref.source_system)
    if ref.resource_id.startswith(csv_file + ":"):
        return f"[{label}, {csv_file} row {ref.resource_id[len(csv_file) + 1 :]}]"
    return f"[{label}, {ref.resource_id}]"


def _reaction_text(allergy: AllergyRecord) -> str:
    worst = worst_reaction(allergy.reactions)
    if worst is None:
        return "not recorded"
    name = strip_snomed_tag(worst.manifestation_display) or ("anaphylaxis" if is_anaphylaxis(worst) else None)
    severity = worst.severity or "severity not recorded"
    return f"{name}, {severity}" if name else severity


def _reaction_word(allergy: AllergyRecord) -> str:
    worst = worst_reaction(allergy.reactions)
    return worst.severity if worst and worst.severity else "not recorded"


def _allergy_sentence(allergy: AllergyRecord, code: Coding) -> str:
    display = strip_snomed_tag(code.display) or f"RxNorm {code.code}"
    verification = allergy.verification_status or VERIFICATION_NOT_STATED
    return (
        f"{_ref_text(allergy.ref, ALLERGY_FILE)} documents an allergy coded {display} (RxNorm {code.code}; "
        f"status active; verification {verification}; reaction: {_reaction_text(allergy)})."
    )


def _order_sentence(order: OrderRecord, code: Coding) -> str:
    display = code.display or f"RxNorm {code.code}"
    return f"{_ref_text(order.ref, MEDICATION_FILE)} has an active order for {display}, RxNorm {code.code}."


def _citation_sentence(citation: Citation | None, drug_name: str | None) -> str:
    if citation is None:
        return f"Label citation: {NO_CACHED_LABEL}."
    return f'The {drug_name} label (DailyMed, set {citation.set_id}, revised {citation.revised}) states: "{citation.quote}".'


def render_card(
    tier: AlertTier,
    revealed: bool,
    allergy: AllergyRecord,
    order: OrderRecord,
    citation: Citation | None,
    drug_name: str | None,
    term: Terminology,
) -> str:
    first = REVEAL_SENTENCE if revealed else NON_REVEAL_SENTENCE
    body = [
        first,
        _allergy_sentence(allergy, class_coding(allergy.codings, term)),
        CLASS_SENTENCE,
        _order_sentence(order, class_coding(order.codings, term)),
    ]
    if tier == AlertTier.A:
        return " ".join([HEADLINE_A, *body, _citation_sentence(citation, drug_name), CLOSING])
    reaction = f"The documented reaction is {_reaction_word(allergy)}; this rule cannot tell whether it is serious."
    return " ".join([HEADLINE_B, *body, reaction, CLOSING])


# Evaluation -----------------------------------------------------------------------------


def _citation_for(order: OrderRecord, term: Terminology) -> tuple[Citation | None, str | None]:
    label = term.label_for(term.ingredients_of(class_coding(order.codings, term).code))
    if label is None:
        return None, None
    return Citation(
        label_name=label.label_name, set_id=label.set_id, revised=label.revised, url=label.url, quote=label.quote
    ), label.drug_name


def evaluate(members: Sequence[MemberResources], term: Terminology | None = None) -> list[RuleFlag]:
    """All flags over one entity's members, in a deterministic order. Pure."""
    term = term or load_terminology()
    allergies = [a for m in members for a in m.allergies if is_eligible_allergy(a, term)]
    orders = [o for m in members for o in m.orders if is_eligible_order(o, term)]
    flags: list[RuleFlag] = []
    for allergy in allergies:
        for order in orders:
            tier = AlertTier.A if is_serious(allergy) else AlertTier.B
            # Spec section 5 pseudocode compares source systems, not record ids: two records of one
            # system that a registrar links read as "Both records come from the same source."
            revealed = allergy.ref.source_system != order.ref.source_system
            citation, drug_name = _citation_for(order, term) if tier == AlertTier.A else (None, None)
            flags.append(
                RuleFlag(
                    tier=tier,
                    revealed_by_merge=revealed,
                    allergy=allergy,
                    order=order,
                    card_text=render_card(tier, revealed, allergy, order, citation, drug_name, term),
                    citation=citation,
                    constructed_scenario=allergy.ref.is_constructed or order.ref.is_constructed,
                )
            )
    flags.sort(
        key=lambda f: (
            str(f.allergy.ref.source_record_id),
            f.allergy.ref.resource_id,
            str(f.order.ref.source_record_id),
            f.order.ref.resource_id,
        )
    )
    return flags


def to_safety_alert(
    flag: RuleFlag,
    *,
    alert_id: UUID,
    entity_id: UUID,
    identified_at: datetime,
    status: AlertStatus = AlertStatus.PRELIMINARY,
) -> SafetyAlert:
    return SafetyAlert(
        id=alert_id,
        entity_id=entity_id,
        tier=flag.tier,
        allergy_ref=ResourceRef(
            source_record_id=flag.allergy.ref.source_record_id,
            source_system=flag.allergy.ref.source_system,
            resource_id=flag.allergy.ref.resource_id,
        ),
        order_ref=ResourceRef(
            source_record_id=flag.order.ref.source_record_id,
            source_system=flag.order.ref.source_system,
            resource_id=flag.order.ref.resource_id,
        ),
        revealed_by_merge=flag.revealed_by_merge,
        severity=SEVERITY_MODERATE,
        status=status,
        card_text=flag.card_text,
        card_footer=CARD_FOOTER,
        citation=flag.citation,
        constructed_scenario=flag.constructed_scenario,
        identified_at=identified_at,
    )


def detected_issue(alert: SafetyAlert) -> dict:
    """The R4 DetectedIssue-shaped view of an alert (spec section 5, output object).

    DetectedIssueCategory has no allergy code, so ``code`` carries ``text`` plus the local
    rule id, and says so in the ``note`` list.
    """
    return {
        "resourceType": "DetectedIssue",
        "id": str(alert.id),
        "status": alert.status.value.lower(),
        "code": {
            "coding": [{"system": "urn:chartguard:rule", "code": RULE_ID, "display": f"{RULE_ID} {RULE_VERSION}"}],
            "text": f"Penicillin-class allergy versus active penicillin-class order ({RULE_ID} {RULE_VERSION})",
        },
        "severity": alert.severity,
        "patient": {"reference": f"Entity/{alert.entity_id}"},
        "identifiedDateTime": alert.identified_at.isoformat(),
        "implicated": [
            {
                "reference": alert.order_ref.resource_id,
                "display": f"{source_label(alert.order_ref.source_system)} order",
            },
            {
                "reference": alert.allergy_ref.resource_id,
                "display": f"{source_label(alert.allergy_ref.source_system)} allergy",
            },
        ],
        "detail": alert.card_text,
        "reference": alert.citation.url if alert.citation else None,
        "evidence": [
            {
                "detail": [
                    {"display": f"tier {alert.tier.value}; revealed_by_merge={str(alert.revealed_by_merge).lower()}"}
                ]
            }
        ],
        "note": [
            "DetectedIssueCategory has no allergy code; code.text plus the local code BL-AMOX-01 is used instead.",
            CSV_ORDER_NOTE,
            alert.card_footer,
        ],
        "meta": {"tag": [{"system": "urn:chartguard:provenance", "code": "constructed-scenario"}]}
        if alert.constructed_scenario
        else {},
        "extension": [{"url": "urn:chartguard:terminology-snapshot", "valueString": RXNORM_SYSTEM}],
    }
