import { describe, expect, it } from "vitest";
import {
  STORY_STEPS,
  currentStep,
  deriveDeskState,
  stageHead,
  stepStatus,
  type DeskState,
} from "./desk";

describe("deriveDeskState", () => {
  const base = { decision: null, linked: false, sheet: null, kiosk: "idle" } as const;

  it("is idle before anything happens", () => {
    expect(deriveDeskState(base)).toBe("idle");
  });

  it("is held while the kiosk is held and nothing is scored yet", () => {
    expect(deriveDeskState({ ...base, kiosk: "held" })).toBe("held");
  });

  it("is review once the pair is proposed, whatever the kiosk does", () => {
    expect(deriveDeskState({ ...base, decision: "PROPOSED" })).toBe("review");
    expect(deriveDeskState({ ...base, decision: "PROPOSED", kiosk: "held" })).toBe("review");
  });

  it("is confirm while a sheet is open on a proposed pair", () => {
    expect(deriveDeskState({ ...base, decision: "PROPOSED", sheet: "approve" })).toBe("confirm");
    expect(deriveDeskState({ ...base, decision: "PROPOSED", sheet: "reject" })).toBe("confirm");
  });

  it("is linked when the decision is LINKED and the entity has loaded", () => {
    expect(deriveDeskState({ ...base, decision: "LINKED", linked: true })).toBe("linked");
  });

  it("stays in review until the entity for a LINKED decision has loaded", () => {
    expect(deriveDeskState({ ...base, decision: "LINKED", linked: false })).toBe("review");
  });

  it("is rejected after a reject until the pair is resolved again", () => {
    expect(deriveDeskState({ ...base, decision: "REJECTED" })).toBe("rejected");
  });

  it("ignores a stale sheet once the pair is linked", () => {
    expect(deriveDeskState({ ...base, decision: "LINKED", linked: true, sheet: "approve" })).toBe("linked");
  });
});

describe("the story stepper", () => {
  it("has the five steps in story order", () => {
    expect(STORY_STEPS.map((s) => s.label)).toEqual([
      "Check-in",
      "Rules gate",
      "Compare",
      "Link",
      "Clinician flag",
    ]);
  });

  it("starts on Check-in with nothing done", () => {
    expect(currentStep("idle", "idle", false)).toBe("checkin");
  });

  it("moves to Rules gate when the gate holds the kiosk", () => {
    expect(currentStep("idle", "working", false)).toBe("checkin");
    expect(currentStep("held", "held", false)).toBe("gate");
  });

  it("is on Compare while the registrar reviews, confirms or has rejected", () => {
    for (const desk of ["review", "confirm", "rejected"] as DeskState[]) {
      expect(currentStep(desk, "held", false)).toBe("compare");
    }
  });

  it("ends on Link, or on Clinician flag when the link raised one", () => {
    expect(currentStep("linked", "done", false)).toBe("link");
    expect(currentStep("linked", "done", true)).toBe("flag");
  });

  it("marks the steps before the current one done and the ones after upcoming", () => {
    expect(stepStatus("checkin", "compare")).toBe("done");
    expect(stepStatus("gate", "compare")).toBe("done");
    expect(stepStatus("compare", "compare")).toBe("current");
    expect(stepStatus("link", "compare")).toBe("upcoming");
    expect(stepStatus("flag", "compare")).toBe("upcoming");
  });
});

describe("stageHead", () => {
  const ctx = { name: "Sofia", registrar: "Registrar A", flagRaised: true, reason: null };

  it("opens on two records, one name", () => {
    const head = stageHead("idle", ctx);
    expect(head.title).toBe("Two records, one name");
    expect(head.eyebrow).toBe("Records on file");
    expect(head.subtitle).toContain("Sofia");
  });

  it("names the patient at the kiosk while the gate holds them", () => {
    expect(stageHead("held", ctx).title).toBe("Sofia is at the kiosk");
    expect(stageHead("held", ctx).eyebrow).toBe("Needs registrar");
  });

  it("asks the question in review and keeps it through confirm", () => {
    expect(stageHead("review", ctx).title).toBe("Is this the same person?");
    expect(stageHead("confirm", ctx).title).toBe("Is this the same person?");
    expect(stageHead("confirm", ctx).subtitle).not.toBe(stageHead("review", ctx).subtitle);
  });

  it("names the one record and who linked it", () => {
    const head = stageHead("linked", ctx);
    expect(head.title).toBe("One record for Sofia");
    expect(head.eyebrow).toBe("Linked by Registrar A");
    expect(head.subtitle).toContain("flagged for a clinician");
  });

  it("says nothing was flagged when the rule stayed silent", () => {
    expect(stageHead("linked", { ...ctx, flagRaised: false }).subtitle).not.toContain("flagged");
  });

  it("says what a reject did and did not do, by reason", () => {
    const insufficient = stageHead("rejected", { ...ctx, reason: "INSUFFICIENT_EVIDENCE" });
    expect(insufficient.title).toBe("Two records, one name");
    expect(insufficient.subtitle).toContain("compared again");
    const different = stageHead("rejected", { ...ctx, reason: "DIFFERENT_PERSON" });
    expect(different.subtitle).toContain("not be suggested again");
  });

  it("falls back to neutral wording without a name or registrar", () => {
    const head = stageHead("linked", { name: null, registrar: null, flagRaised: false, reason: null });
    expect(head.title).toBe("One record");
    expect(head.eyebrow).toBe("Linked");
    expect(stageHead("held", { ...ctx, name: null }).title).toBe("A patient is at the kiosk");
  });

  it("never uses the words the flag must never say", () => {
    const banned = ["prevented", "would have died", "the ai caught", "contraindicated", "fatal", "thinking", "diagnosed"];
    const states: DeskState[] = ["idle", "held", "review", "confirm", "linked", "rejected"];
    for (const state of states) {
      const text = Object.values(stageHead(state, ctx)).join(" ").toLowerCase();
      for (const word of banned) expect(text, `${state} says "${word}"`).not.toContain(word);
    }
  });
});
