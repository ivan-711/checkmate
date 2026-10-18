import { describe, expect, it } from "vitest";
import { scenario } from "@/data/scenario";
import {
  actorName,
  differingFields,
  formatCt,
  compactLane,
  goldenValueText,
  rankContributions,
  sourceLabel,
} from "./display";

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

describe("goldenValueText", () => {
  it("shows plain values as they are and a missing value as null", () => {
    expect(goldenValueText("PLACEHOLDER-GIVEN")).toBe("PLACEHOLDER-GIVEN");
    expect(goldenValueText(54311)).toBe("54311");
    expect(goldenValueText(null)).toBeNull();
    expect(goldenValueText(undefined)).toBeNull();
  });

  it("shows a coded clinical value by its display name and status, never [object Object]", () => {
    const allergy = { code: "7984", display: "Penicillin V", status: "active", resourceId: "a-1" };
    expect(goldenValueText(allergy)).toBe("Penicillin V (active)");
    expect(goldenValueText({ code: "308192", status: "active" })).toBe("308192 (active)");
    expect(goldenValueText({ code: "308192", display: "Amoxicillin 500 MG" })).toBe("Amoxicillin 500 MG");
  });

  it("falls back to key: value pairs for an object without a code, and joins lists", () => {
    expect(goldenValueText({ line: "100 Placeholder St", city: "Madison" })).toBe(
      "line: 100 Placeholder St, city: Madison",
    );
    expect(goldenValueText(["a", { display: "B" }])).toBe("a, B");
  });
});

describe("compactLane", () => {
  const ev = (day: number, isConstructed = false) => ({
    occurredAt: `2020-01-${String(day).padStart(2, "0")}`,
    isConstructed,
  });

  it("keeps the latest rows in date order and reports how many it hid", () => {
    const lane = [ev(3), ev(1), ev(5), ev(2), ev(4)];
    const { shown, hidden } = compactLane(lane, 2);
    expect(shown.map((e) => e.occurredAt)).toEqual(["2020-01-04", "2020-01-05"]);
    expect(hidden).toBe(3);
  });

  it("always keeps constructed-scenario rows, however old", () => {
    const { shown, hidden } = compactLane([ev(1, true), ev(2), ev(3), ev(4)], 2);
    expect(shown.map((e) => e.occurredAt)).toEqual(["2020-01-01", "2020-01-03", "2020-01-04"]);
    expect(hidden).toBe(1);
  });

  it("shows everything when the lane fits", () => {
    expect(compactLane([ev(2), ev(1)], 5)).toEqual({ shown: [ev(1), ev(2)], hidden: 0 });
  });
});
