import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Band, CandidatePairDetail } from "@/api/types";
import { scenario } from "@/data/scenario";
import { GateOrbit } from "./GateOrbit";

const kiosk = "kiosk-record";

function handoff(id: string, system: string, label: string, p: number, logit: number, band: Band): CandidatePairDetail {
  const { pair, recordA, recordB } = scenario.pair;
  return {
    ...scenario.pair,
    pair: { ...pair, id, origin: "FRONTDESK_HANDOFF", recordAId: kiosk, recordBId: `${id}-r`, decision: { ...pair.decision, p, logit, band } },
    recordA: { ...recordA, record: { ...recordA.record, id: kiosk, sourceSystem: "AGENT_INTAKE" }, displayLabel: "Kiosk" },
    recordB: { ...recordB, record: { ...recordB.record, id: `${id}-r`, sourceSystem: system }, displayLabel: label },
  };
}

const pairs = [
  handoff("p-er", "ER_FHIR", "ER FHIR", 0.98, 3.1, "AUTO_LINK"),
  handoff("p-cl", "CLINIC_CSV", "Clinic CSV", 0.66, 0.7, "REVIEW"),
];

const render = (list = pairs) =>
  renderToStaticMarkup(createElement(GateOrbit, { pairs: list, thresholds: scenario.thresholds, intakeRecordId: kiosk }));

describe("GateOrbit", () => {
  it("draws the check-in at the centre with each held chart in its band's ring", () => {
    const html = render();
    expect(html).toContain('data-testid="gate-orbit"');
    expect(html).toMatch(/data-testid="orbit-chart"[^>]*data-band="AUTO_LINK"[^>]*data-source-system="ER_FHIR"/);
    expect(html).toMatch(/data-testid="orbit-chart"[^>]*data-band="REVIEW"[^>]*data-source-system="CLINIC_CSV"/);
    expect(html).toContain("0.98");
    expect(html).toContain("0.66");
  });

  it("labels the rings with the band names a registrar reads, never the enum", () => {
    const html = render();
    expect(html).toContain("AUTO-LINK");
    expect(html).toContain(">REVIEW<");
    expect(html).toContain("KEEP SEPARATE");
    const text = html.replace(/<[^>]+>/g, " ");
    expect(text).not.toMatch(/AUTO_LINK|KEEP_SEPARATE|FRONTDESK_HANDOFF/);
  });

  it("explains the gate in one sentence and says what did not happen", () => {
    const html = render();
    expect(html).toContain("Inside the dashed ring, the gate allows no new chart. Two charts are inside.");
    expect(html).toContain("No chart was opened. Nothing was linked.");
    expect(html).toMatch(/aria-label="[^"]*ER FHIR scores 0\.98[^"]*Clinic CSV scores 0\.66[^"]*inside the dashed ring[^"]*"/);
  });

  it("counts only the charts inside the gate ring", () => {
    const html = render([pairs[0], handoff("p-far", "CLINIC_CSV", "Clinic CSV", 0.2, -1.4, "KEEP_SEPARATE")]);
    expect(html).toContain("One chart is inside.");
  });

  it("legend names the kiosk check-in and each held chart's source", () => {
    const html = render();
    expect(html).toContain("Kiosk check-in");
    expect(html).toContain("ER FHIR");
    expect(html).toContain("Clinic CSV");
  });
});
