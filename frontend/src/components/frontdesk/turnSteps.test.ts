import { describe, expect, it } from "vitest";
import type { IntakeTurn, ToolCallRecord } from "@/api/types";
import { FixtureSource } from "@/data/fixtureSource";
import { scenario } from "@/data/scenario";
import { COPY } from "./copy";
import { turnSteps } from "./turnSteps";

async function turnFor(text: string): Promise<IntakeTurn> {
  const s = new FixtureSource(scenario);
  const session = await s.startIntake("EN");
  return s.sendTurn(session.id, text, "k1");
}

function call(toolName: string, gate: ToolCallRecord["gate"]): ToolCallRecord {
  return { id: toolName, stepIndex: 0, toolName, args: {}, gate, effect: { status: "NONE" }, latencyMs: 0 };
}

describe("turnSteps", () => {
  it("lists a held turn in the past tense and ends on the gate's HELD fact with its reason", async () => {
    const steps = turnSteps(await turnFor(scenario.frontdeskIntake.utteranceEn), COPY.en)!;
    expect(steps.done).toEqual([
      "Read your check-in",
      "Searched for an existing chart",
      "Asked to create a new chart",
    ]);
    expect(steps.fact).toEqual({
      outcome: "HELD",
      label: "HELD",
      reason: "CANDIDATE_IN_REVIEW_OR_HIGHER",
      policy: "frontdesk-gate/1",
    });
  });

  it("ends on PASSED with the policy when the gate allowed every call", () => {
    const turn = {
      toolCalls: [
        call("search_patients", {
          outcome: "ALLOW",
          handoffRequired: false,
          policyVersion: "frontdesk-gate/1",
        }),
      ],
    } as IntakeTurn;
    const steps = turnSteps(turn, COPY.es)!;
    expect(steps.done).toEqual(["Se leyó su registro", "Se buscó un expediente existente"]);
    expect(steps.fact).toMatchObject({ outcome: "PASSED", label: "PERMITIDO", reason: null });
  });

  it("names an unknown tool by its id rather than guessing what it did", () => {
    const turn = {
      toolCalls: [
        call("lookup_x", {
          outcome: "DENY",
          reasonCode: "UNKNOWN_TOOL",
          handoffRequired: false,
          policyVersion: "frontdesk-gate/1",
        }),
      ],
    } as IntakeTurn;
    expect(turnSteps(turn, COPY.en)!.done[1]).toBe("Called lookup_x");
    expect(turnSteps(turn, COPY.en)!.fact.reason).toBe("UNKNOWN_TOOL");
  });

  it("claims no steps on a turn where no tool ran, so the gate never ran", async () => {
    expect(turnSteps(await turnFor("I have an appointment at three."), COPY.en)).toBeNull();
  });
});
