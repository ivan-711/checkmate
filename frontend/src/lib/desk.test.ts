import { describe, expect, it } from "vitest";
import { scenario } from "@/data/scenario";
import { deriveStageState, type StageInputs } from "./desk";

const proposed = scenario.pair;
const withStatus = (status: "PROPOSED" | "LINKED" | "REJECTED") => ({
  ...proposed,
  pair: { ...proposed.pair, decision: { ...proposed.pair.decision, status } },
});

const base: StageInputs = { detail: null, resolved: false, heldPairs: 0, intent: null };

describe("deriveStageState", () => {
  it("is idle before Resolve when no check-in is held", () => {
    expect(deriveStageState(base)).toBe("idle");
  });

  it("is held while the gate holds a check-in and nothing is compared yet", () => {
    expect(deriveStageState({ ...base, heldPairs: 2 })).toBe("held");
  });

  it("is review once the pair is scored and waiting on a person", () => {
    expect(deriveStageState({ ...base, detail: withStatus("PROPOSED"), resolved: true })).toBe("review");
  });

  it("is confirm while the approve or reject sheet is open", () => {
    expect(
      deriveStageState({ ...base, detail: withStatus("PROPOSED"), resolved: true, intent: "APPROVE" }),
    ).toBe("confirm");
  });

  it("is linked after an approval and rejected after a reject", () => {
    expect(deriveStageState({ ...base, detail: withStatus("LINKED"), resolved: true })).toBe("linked");
    expect(deriveStageState({ ...base, detail: withStatus("REJECTED"), resolved: true })).toBe("rejected");
  });

  it("a rejected pair stays rejected even while a check-in is held, so Resolve again is offered", () => {
    expect(deriveStageState({ ...base, detail: withStatus("REJECTED"), resolved: true, heldPairs: 1 })).toBe(
      "rejected",
    );
  });
});
