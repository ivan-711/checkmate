import { describe, expect, it } from "vitest";
import type { Band, CandidatePairDetail, ThresholdSet } from "@/api/types";
import { scenario } from "@/data/scenario";
import { BAND_RINGS, orbitPlacement, ringForBand } from "./orbit";

const thresholds: ThresholdSet = {
  thresholdsId: "t",
  cLow: 0,
  cHigh: 2,
  autoLinkEnabled: false,
  isCalibrated: false,
};
const kiosk = "kiosk-record";

function handoff(
  id: string,
  otherSystem: string,
  otherLabel: string,
  p: number,
  logit: number,
  band: Band,
): CandidatePairDetail {
  const { pair, recordA, recordB } = scenario.pair;
  return {
    ...scenario.pair,
    pair: {
      ...pair,
      id,
      origin: "FRONTDESK_HANDOFF",
      recordAId: kiosk,
      recordBId: `${id}-other`,
      decision: { ...pair.decision, p, logit, band },
    },
    recordA: {
      ...recordA,
      record: { ...recordA.record, id: kiosk, sourceSystem: "AGENT_INTAKE" },
      displayLabel: "Kiosk",
    },
    recordB: {
      ...recordB,
      record: { ...recordB.record, id: `${id}-other`, sourceSystem: otherSystem },
      displayLabel: otherLabel,
    },
  };
}

describe("ringForBand", () => {
  it("puts AUTO_LINK innermost, REVIEW inside the gate ring and KEEP_SEPARATE outside it", () => {
    expect(ringForBand("AUTO_LINK")).toBe(BAND_RINGS.AUTO_LINK);
    expect(BAND_RINGS.AUTO_LINK).toBeLessThan(BAND_RINGS.REVIEW);
    expect(BAND_RINGS.REVIEW).toBeLessThan(BAND_RINGS.KEEP_SEPARATE);
  });
});

describe("orbitPlacement", () => {
  const er = handoff("p-er", "ER_FHIR", "ER FHIR", 0.98, 3.1, "AUTO_LINK");
  const clinic = handoff("p-cl", "CLINIC_CSV", "Clinic CSV", 0.66, 0.7, "REVIEW");

  it("places each held chart by the band the API decided, never by recomputing it", () => {
    const { charts } = orbitPlacement([er, clinic], thresholds, kiosk);
    expect(charts.map((c) => [c.pairId, c.band, c.sourceSystem, c.label, c.p])).toEqual([
      ["p-er", "AUTO_LINK", "ER_FHIR", "ER FHIR", "0.98"],
      ["p-cl", "REVIEW", "CLINIC_CSV", "Clinic CSV", "0.66"],
    ]);
    expect(charts[0].radius).toBeLessThan(charts[1].radius);
  });

  it("names the other record, never the kiosk record, whichever side it sits on", () => {
    const flipped = {
      ...er,
      pair: { ...er.pair, recordAId: er.pair.recordBId, recordBId: kiosk },
      recordA: er.recordB,
      recordB: er.recordA,
    };
    const { charts } = orbitPlacement([flipped], thresholds, kiosk);
    expect(charts[0].sourceSystem).toBe("ER_FHIR");
  });

  it("counts the charts inside the gate ring (REVIEW or higher) and reads the gate line from the thresholds", () => {
    const placed = orbitPlacement([er, clinic], thresholds, kiosk);
    expect(placed.insideGate).toBe(2);
    expect(placed.gateAt).toBe(thresholds.cLow);
    const far = handoff("p-far", "CLINIC_CSV", "Clinic CSV", 0.2, -1.4, "KEEP_SEPARATE");
    expect(orbitPlacement([er, far], thresholds, kiosk).insideGate).toBe(1);
  });

  it("keeps a chart inside its band's ring whatever its raw score", () => {
    const hot = handoff("p-hot", "ER_FHIR", "ER FHIR", 0.999, 40, "AUTO_LINK");
    const cold = handoff("p-cold", "CLINIC_CSV", "Clinic CSV", 0.01, -40, "KEEP_SEPARATE");
    const { charts } = orbitPlacement([hot, cold], thresholds, kiosk);
    expect(charts[0].radius).toBeGreaterThan(0);
    expect(charts[0].radius).toBeLessThanOrEqual(BAND_RINGS.AUTO_LINK);
    expect(charts[1].radius).toBeGreaterThan(BAND_RINGS.REVIEW);
    expect(charts[1].radius).toBeLessThanOrEqual(BAND_RINGS.KEEP_SEPARATE);
  });

  it("spreads two charts in the same ring so their marks never overlap", () => {
    const a = handoff("p-a", "ER_FHIR", "ER FHIR", 0.9, 2.5, "AUTO_LINK");
    const b = handoff("p-b", "CLINIC_CSV", "Clinic CSV", 0.9, 2.5, "AUTO_LINK");
    const { charts } = orbitPlacement([a, b], thresholds, kiosk);
    expect(charts[0].angle).not.toBe(charts[1].angle);
  });
});
