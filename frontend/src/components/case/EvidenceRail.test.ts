import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ThresholdSet } from "@/api/types";
import { scenario } from "@/data/scenario";
import { EvidenceRail } from "./EvidenceRail";

const detail = scenario.pair;
const thresholds: ThresholdSet = { ...scenario.thresholds, autoLinkEnabled: false, isCalibrated: false };
// null stands for "still loading" (an explicit undefined would take the default).
const render = (t: ThresholdSet | null = thresholds) =>
  renderToStaticMarkup(createElement(EvidenceRail, { detail, thresholds: t ?? undefined }));

const rows = (html: string) => html.split('data-testid="evidence-feature-row"').slice(1);

describe("EvidenceRail", () => {
  it("shows the score, the band stamp and one row per top feature", () => {
    const html = render();
    expect(html).toContain('data-testid="evidence-rail"');
    expect(html).toMatch(/data-testid="pair-score"[^>]*>0\.73</);
    expect(html).toMatch(/data-testid="pair-band"[^>]*>REVIEW</);
    expect(rows(html)).toHaveLength(5);
  });

  it("names the field each row cites, so hovering it can light both records", () => {
    const html = render();
    const cites = rows(html).map((r) => /data-cite="([a-z]+)"/.exec(r)?.[1]);
    expect(cites).toEqual(["given", "dob", "addr", "family", "family"]);
  });

  it("draws six weight dots per row next to the exact value, and says what the row compared", () => {
    const html = render();
    const first = rows(html)[0];
    expect(first.match(/data-testid="evidence-dot"/g)).toHaveLength(6);
    expect(first).toContain("+0.90");
    expect(first).toContain("Given name");
    expect(first).toContain("Same letters");
  });

  it("every row is keyboard reachable and reads its claim with both values", () => {
    const html = render();
    const first = rows(html)[0];
    expect(first.slice(0, 400)).toContain('tabindex="0"');
    expect(first).toMatch(
      /aria-label="Given name, same letters, weight \+0\.90\. ER FHIR PLACEHOLDER-GIVEN\. Clinic CSV PLACEHOLDER-GIVEN\."/,
    );
  });

  it("says auto-link is off and that the weights are hand-set, from the threshold set", () => {
    const html = render();
    expect(html).toContain("Auto-link is off. You decide.");
    expect(html).toContain("Hand-set demo weights. Not a probability.");
    // The word may appear only for a calibrated threshold set; this one is not.
    expect(html.toLowerCase()).not.toContain("calibrated");
    const calibrated = render({ ...thresholds, isCalibrated: true, autoLinkEnabled: true });
    expect(calibrated).not.toContain("Hand-set demo weights");
    expect(calibrated).not.toContain("Auto-link is off");
  });

  it("makes no claim about calibration or auto-link while the threshold set is still loading", () => {
    const html = render(null);
    expect(html).not.toContain("Not a probability");
    expect(html.toLowerCase()).not.toContain("calibrated");
    expect(html).not.toContain("Auto-link is off");
    expect(html).toMatch(/data-testid="pair-band"[^>]*>REVIEW</);
  });

  it("never shows a feature code or a band enum", () => {
    const html = render();
    expect(html).not.toMatch(/given_name_jw|dob_exact|address_jaccard/);
    expect(html).not.toContain("AUTO_LINK");
  });
});
