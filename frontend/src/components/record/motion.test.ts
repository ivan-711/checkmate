import { describe, expect, it } from "vitest";
import { morphMode, threadsArmed } from "./motion";

describe("morphMode", () => {
  it("morphs only when the approval happened on this stage: review or confirm into linked", () => {
    expect(morphMode({ from: "confirm", to: "linked", reduced: false })).toBe("morph");
    expect(morphMode({ from: "review", to: "linked", reduced: false })).toBe("morph");
  });

  it("is a crossfade under reduced motion", () => {
    expect(morphMode({ from: "confirm", to: "linked", reduced: true })).toBe("crossfade");
  });

  it("renders at rest on load, after Undo reset and on any other change", () => {
    expect(morphMode({ from: undefined, to: "linked", reduced: false })).toBe("instant");
    expect(morphMode({ from: "idle", to: "linked", reduced: false })).toBe("instant");
    expect(morphMode({ from: "linked", to: "idle", reduced: false })).toBe("instant");
    expect(morphMode({ from: "review", to: "confirm", reduced: false })).toBe("instant");
  });
});

describe("threadsArmed", () => {
  it("draws the threads when Resolve lands on this stage", () => {
    expect(threadsArmed({ from: "idle", to: "review" })).toBe(true);
    expect(threadsArmed({ from: "held", to: "review" })).toBe(true);
    expect(threadsArmed({ from: "rejected", to: "review" })).toBe(true);
  });

  it("keeps them still between review and confirm, and on load", () => {
    expect(threadsArmed({ from: "review", to: "confirm" })).toBe(false);
    expect(threadsArmed({ from: "confirm", to: "review" })).toBe(false);
    expect(threadsArmed({ from: undefined, to: "review" })).toBe(false);
  });
});
