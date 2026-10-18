import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { scenario } from "@/data/scenario";
import { FlagCard } from "./FlagCard";

const alert = scenario.alertIfApproved;
const render = () => renderToStaticMarkup(createElement(FlagCard, { state: { kind: "raised", alert } }));

/** Everything before the Details fold is what the card shows without a click. */
function split(html: string): { shown: string; folded: string } {
  const at = html.indexOf("<details");
  expect(at, "the card has a Details fold").toBeGreaterThan(-1);
  return { shown: html.slice(0, at), folded: html.slice(at) };
}

describe("FlagCard", () => {
  it("leads with the one-line headline, each fact with its source pill, outside the fold", () => {
    const { shown } = split(render());
    const headline = shown.slice(shown.indexOf('data-testid="flag-card-headline"'));
    expect(headline).toMatch(
      /Penicillin V allergy \(anaphylaxis\).*Clinic CSV.*·.*active amoxicillin order.*ER FHIR/s,
    );
    expect(headline.match(/data-testid="flag-source-pill"/g)).toHaveLength(2);
  });

  it("keeps the rule id, the constructed-scenario chip and the review words outside the fold", () => {
    const { shown } = split(render());
    expect(shown).toContain('data-testid="flag-card"');
    expect(shown).toMatch(/data-testid="flag-card-rule-id"[^>]*>BL-AMOX-01</);
    expect(shown).toContain('data-testid="constructed-scenario-chip"');
    expect(shown).toMatch(/flagged for clinician review/i);
  });

  it("folds the card text, the citation and the rule's limits under a closed Details", () => {
    const { folded } = split(render());
    expect(folded).toMatch(/^<details(?![^>]*\bopen\b)[^>]*>\s*<summary[^>]*>Details<\/summary>/);
    expect(folded).toContain(alert.cardText.slice(0, 60));
    expect(folded).toContain(alert.citation!.labelName);
    expect(folded).toContain("Absence of a flag is not evidence that no conflict exists.");
  });

  it("stays neutral: never an alert role", () => {
    expect(render()).not.toContain('role="alert"');
  });
});
