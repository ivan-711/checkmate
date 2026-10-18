import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { scenario } from "@/data/scenario";
import { Notice, type NoticeProps } from "./Notice";

const alert = scenario.alertIfApproved;
const render = (props: Partial<NoticeProps> = {}) =>
  renderToStaticMarkup(createElement(Notice, { alert, mode: "instant", ...props }));

// The acceptance script's never-say list (eval/acceptance/g16.spec.ts).
const NEVER_SAY = [
  "prevented",
  "would have died",
  "the ai caught",
  "contraindicated for this patient",
  "fatal",
];

/** Everything before the Details fold is what the notice shows without a click. */
function split(html: string): { shown: string; folded: string } {
  const at = html.indexOf("<details");
  expect(at, "the notice has a Details fold").toBeGreaterThan(-1);
  return { shown: html.slice(0, at), folded: html.slice(at) };
}

describe("Notice", () => {
  it("leads with one sentence: the allergy on one record, the order on the other, a clinician decides", () => {
    const { shown } = split(render());
    const headline = shown.slice(shown.indexOf('data-testid="flag-card-headline"'));
    expect(headline).toMatch(
      /<b>Penicillin V allergy \(anaphylaxis\)<\/b> on the Clinic record, and an <b>active amoxicillin order<\/b> on the Emergency room record\. A clinician decides\./,
    );
  });

  it("keeps the rule id, the constructed-scenario chip and the review words outside the fold", () => {
    const { shown } = split(render());
    expect(shown).toContain('data-testid="flag-card"');
    expect(shown).toMatch(/data-testid="flag-card-rule-id"[^>]*>BL-AMOX-01</);
    expect(shown).toMatch(/BL-AMOX-01<\/span><span[^>]*>v1</); // the version is a sibling, never inside the id
    expect(shown).toContain('data-testid="constructed-scenario-chip"');
    expect(shown).toMatch(/Flagged for clinician review/);
    expect(shown).toContain("Rule result");
    expect(shown).toContain("Surfaced by the link");
  });

  it("says the flag was already on the record when the link did not surface it", () => {
    const { shown } = split(render({ alert: { ...alert, revealedByMerge: false } }));
    expect(shown).not.toContain("Surfaced by the link");
    expect(shown).toContain("On the linked record");
  });

  it("folds the card text, the citation and the rule's limits under a closed Details", () => {
    const { folded } = split(render());
    expect(folded).toMatch(/^<details(?![^>]*\bopen\b)[^>]*>\s*<summary[^>]*>Details/);
    expect(folded).toContain(alert.cardText.slice(0, 60));
    expect(folded).toContain(alert.citation!.labelName);
    expect(folded).toContain("Absence of a flag is not evidence that no conflict exists.");
    expect(folded).not.toContain("Rule BL-AMOX-01 v1."); // the id sits once, in the header
  });

  it("stays neutral: never an alert role, none of the never-say words, a focusable heading", () => {
    const html = render();
    expect(html).not.toContain('role="alert"');
    expect(html).not.toContain("aria-live");
    for (const banned of NEVER_SAY) expect(html.toLowerCase()).not.toContain(banned);
    expect(html).toMatch(/<h3[^>]*id="flag-heading"[^>]*tabindex="-1"/);
  });
});
