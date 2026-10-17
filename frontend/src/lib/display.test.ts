import { describe, expect, it } from "vitest";
import { scenario } from "@/data/scenario";
import { actorName, differingFields, formatCt, rankContributions, sourceLabel } from "./display";

describe("rankContributions", () => {
  it("orders by absolute weight and puts missing features last as no evidence", () => {
    const ranked = rankContributions([
      { feature: "phone_match", logit: 0, value: null },
      { feature: "sex_match", logit: -1.2, value: 0 },
      { feature: "dob_exact", logit: 0.8, value: 1 },
    ]);
    expect(ranked.map((c) => [c.feature, c.missing])).toEqual([
      ["sex_match", false],
      ["dob_exact", false],
      ["phone_match", true],
    ]);
    expect(ranked[0].label).toBe("Sex");
  });

  it("keeps an unknown feature code readable", () => {
    expect(rankContributions([{ feature: "new_thing", logit: 1, value: 1 }])[0].label).toBe("new_thing");
  });
});

describe("differingFields", () => {
  it("marks fields present on both cards with different values", () => {
    const { recordA, recordB } = scenario.pair;
    expect(differingFields(recordA.normalized, recordB.normalized)).toEqual(new Set(["familyName"]));
  });

  it("does not call a missing value a difference", () => {
    const a = { recordId: "a", phoneE164: "+15555550100" };
    const b = { recordId: "b", phoneE164: null };
    expect(differingFields(a, b).size).toBe(0);
  });
});

describe("formatting", () => {
  it("formats a decision time in Central Time", () => {
    expect(formatCt("2026-10-17T19:32:08Z")).toBe("14:32:08 CT");
  });

  it("shows the registrar label without the actor prefix", () => {
    expect(actorName("registrar:Registrar B")).toBe("Registrar B");
    expect(actorName("system:scorer")).toBe("system:scorer");
  });

  it("names a source system by its card label", () => {
    const { recordA, recordB } = scenario.pair;
    expect(sourceLabel("CLINIC_CSV", [recordA, recordB])).toBe("Clinic CSV");
    expect(sourceLabel("SPECIALIST", [recordA, recordB])).toBe("SPECIALIST");
  });
});
