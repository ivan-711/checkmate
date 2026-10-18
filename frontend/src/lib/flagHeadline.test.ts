import { describe, expect, it } from "vitest";
import { scenario } from "@/data/scenario";
import { flagHeadline, surfacedLine } from "./flagHeadline";

// Card texts in the shapes backend/rule/bl_amox_01.py renders (rule v1): tier A carries the label
// citation, tier B does not; refs are FHIR ids or CSV rows; the reaction is "<name>, <severity>",
// a severity alone, or "not recorded".
function cardText({
  allergy = "penicillin V",
  reaction = "anaphylaxis, severe",
  order = "amoxicillin 500 MG Oral Tablet",
  tier = "A",
}: { allergy?: string; reaction?: string; order?: string; tier?: "A" | "B" } = {}): string {
  const head =
    tier === "A" ? "Flagged for clinician review." : "Possible conflict, flagged for clinician review.";
  const allergySentence =
    `[Clinic CSV, allergies.csv row 270d9b1e] documents an allergy coded ${allergy} (RxNorm 7984; ` +
    `status active; verification not stated in source; reaction: ${reaction}).`;
  const orderSentence = `[ER FHIR, MedicationRequest/c3a0fc4f] has an active order for ${order}, RxNorm 308192.`;
  const tail =
    tier === "A"
      ? 'The amoxicillin label (DailyMed, set d5eba477, revised 3/2023) states: "contraindicated in patients with a history of serious hypersensitivity reactions (e.g., anaphylaxis)".'
      : "The documented reaction is mild; this rule cannot tell whether it is serious.";
  return [
    head,
    "Two records that were previously separate are now linked to this patient by an approved identity link.",
    allergySentence,
    "This rule treats that code as penicillin-class.",
    orderSentence,
    tail,
    "This is a rule-based flag on synthetic data. A clinician decides.",
  ].join(" ");
}

const headline = (text: string) => flagHeadline({ cardText: text });

describe("flagHeadline", () => {
  it("reads the allergy, its reaction and the ordered drug from the contract fixture's alert", () => {
    expect(flagHeadline(scenario.alertIfApproved)).toBe(
      "Penicillin V allergy (anaphylaxis) · active amoxicillin order",
    );
  });

  it("reads a capitalized order display mid-sentence", () => {
    expect(headline(cardText({ order: "Amoxicillin 500 MG Oral Tablet" }))).toBe(
      "Penicillin V allergy (anaphylaxis) · active amoxicillin order",
    );
  });

  it("reads a tier B card, which has no label citation", () => {
    expect(headline(cardText({ tier: "B", allergy: "penicillin G", reaction: "Hives, mild" }))).toBe(
      "Penicillin G allergy (hives) · active amoxicillin order",
    );
  });

  it("names every ingredient of a combination order", () => {
    expect(headline(cardText({ order: "amoxicillin 250 MG / clavulanate 125 MG Oral Tablet" }))).toBe(
      "Penicillin V allergy (anaphylaxis) · active amoxicillin/clavulanate order",
    );
    expect(headline(cardText({ order: "Amoxicillin 250 MG / Clavulanate 125 MG Oral Tablet" }))).toBe(
      "Penicillin V allergy (anaphylaxis) · active amoxicillin/clavulanate order",
    );
  });

  it("skips a leading quantity on an injectable order", () => {
    expect(
      headline(cardText({ order: "1 ML penicillin G benzathine 1200000 UNT/ML Prefilled Syringe" })),
    ).toBe("Penicillin V allergy (anaphylaxis) · active penicillin G benzathine order");
  });

  it("calls a bare severity a reaction's severity, never a reaction name", () => {
    expect(headline(cardText({ reaction: "severe" }))).toBe(
      "Penicillin V allergy (severe reaction) · active amoxicillin order",
    );
  });

  it("keeps an order the rule could only name by its RxNorm code", () => {
    expect(headline(cardText({ order: "RxNorm 723" }))).toBe(
      "Penicillin V allergy (anaphylaxis) · active RxNorm 723 order",
    );
  });

  it("leaves the reaction out when the record does not give one", () => {
    for (const reaction of ["not recorded", "severity not recorded"]) {
      expect(headline(cardText({ reaction }))).toBe("Penicillin V allergy · active amoxicillin order");
    }
  });

  it("keeps a named reaction whose severity is not recorded", () => {
    expect(headline(cardText({ reaction: "rash, severity not recorded" }))).toBe(
      "Penicillin V allergy (rash) · active amoxicillin order",
    );
  });

  it("keeps an order display it cannot split into a drug name", () => {
    expect(headline(cardText({ order: "Penicillin V Potassium" }))).toBe(
      "Penicillin V allergy (anaphylaxis) · active penicillin V Potassium order",
    );
  });

  it("falls back to plain words for any part the card text does not carry", () => {
    expect(headline("")).toBe("Documented allergy · active order");
    expect(headline("Flagged for clinician review. Something else entirely.")).toBe(
      "Documented allergy · active order",
    );
    const noOrder = cardText().replace(/has an active order for .*?, RxNorm \d+\./, "");
    expect(headline(noOrder)).toBe("Penicillin V allergy (anaphylaxis) · active order");
  });
});

describe("surfacedLine", () => {
  it("counts the allergies an approval surfaced, in the singular and the plural", () => {
    expect(surfacedLine(1)).toBe("1 allergy surfaced");
    expect(surfacedLine(2)).toBe("2 allergies surfaced");
  });
});
