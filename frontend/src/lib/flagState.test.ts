import { describe, expect, it } from "vitest";
import type { MatchDecision, SafetyAlert } from "@/api/types";
import type { CaseData } from "@/data/source";
import { scenario } from "@/data/scenario";
import { flagState } from "./flagState";

function caseWith(status: MatchDecision["status"], outcome: CaseData["outcome"]): CaseData {
  const base = scenario.pair;
  return {
    detail: { ...base, pair: { ...base.pair, decision: { ...base.pair.decision, status } } },
    outcome,
    resolved: true,
  };
}

const linkedOutcome = (alerts: SafetyAlert[]) => ({
  decision: { ...scenario.pair.pair.decision, status: "LINKED" as const },
  entity: scenario.entityIfApproved,
  alerts,
});

describe("flagState", () => {
  it("is idle before any decision", () => {
    expect(flagState(caseWith("PROPOSED", null))).toEqual({ kind: "idle" });
  });

  it("is silent after a rejection: the rule never runs", () => {
    expect(flagState(caseWith("REJECTED", null))).toEqual({ kind: "silent" });
  });

  it("raises the alert from the approval", () => {
    const state = flagState(caseWith("LINKED", linkedOutcome([scenario.alertIfApproved])));
    expect(state).toEqual({ kind: "raised", alert: scenario.alertIfApproved });
  });

  it("says no flag when the approval raised none", () => {
    expect(flagState(caseWith("LINKED", linkedOutcome([])))).toEqual({ kind: "none" });
  });

  it("never claims a result for a link whose review result this view does not hold", () => {
    expect(flagState(caseWith("LINKED", null))).toEqual({ kind: "unavailable" });
  });
});
