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

function call(
  toolName: string,
  gate: ToolCallRecord["gate"],
  candidates: ToolCallRecord["candidates"] = [],
): ToolCallRecord {
  return {
    id: toolName,
    stepIndex: 0,
    toolName,
    args: {},
    gate,
    effect: { status: "NONE" },
    latencyMs: 0,
    candidates,
  };
}

describe("turnSteps", () => {
  it("lists a held turn in the past tense and ends on the gate step, held, with its reason", async () => {
    const turn = await turnFor(scenario.frontdeskIntake.utteranceEn);
    const steps = turnSteps(turn, COPY.en)!;
    expect(steps.done.map((s) => s.label)).toEqual([
      "Read your check-in",
      "Found a chart that may be yours",
      "Asked to open a new chart",
    ]);
    // Each tool step carries its call, so the screen can keep the tool's id in a data attribute.
    expect(steps.done.map((s) => s.call?.toolName ?? null)).toEqual([
      null,
      "search_patients",
      "propose_new_chart",
    ]);
    expect(steps.gate).toEqual({
      outcome: "HELD",
      label: "Checked with the identity gate: held",
      reasonCode: "CANDIDATE_IN_REVIEW_OR_HIGHER",
      reason: "An existing chart may be yours",
      policy: "frontdesk-gate/1",
    });
  });

  it("says a search found nothing when it found nothing, and counts more than one chart", () => {
    const allow = { outcome: "ALLOW", handoffRequired: false, policyVersion: "frontdesk-gate/1" } as const;
    const none = { toolCalls: [call("search_patients", allow, [])] } as IntakeTurn;
    expect(turnSteps(none, COPY.en)!.done[1].label).toBe("Searched for an existing chart");
    const candidate = { recordId: "r", sourceSystem: "ER_FHIR", p: 0.5, band: "REVIEW" } as const;
    const two = { toolCalls: [call("search_patients", allow, [candidate, candidate])] } as IntakeTurn;
    expect(turnSteps(two, COPY.en)!.done[1].label).toBe("Found charts that may be yours");
    expect(turnSteps(two, COPY.es)!.done[1].label).toBe("Encontró expedientes que podrían ser suyos");
  });

  it("ends on the gate step, allowed, when the gate allowed every call", () => {
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
    expect(steps.done.map((s) => s.label)).toEqual(["Leyó su mensaje", "Buscó un expediente existente"]);
    expect(steps.gate).toMatchObject({
      outcome: "PASSED",
      label: "Consultó el control de identidad: permitido",
      reasonCode: null,
      reason: null,
    });
  });

  it("describes an unknown tool neutrally on screen and keeps its id on the step", () => {
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
    const steps = turnSteps(turn, COPY.en)!;
    expect(steps.done[1].label).toBe("Tried another step");
    expect(steps.done[1].call?.toolName).toBe("lookup_x");
    expect(steps.gate.reason).toBe(COPY.en.reason.UNKNOWN_TOOL);
  });

  it("falls back to a neutral phrase for a reason code it does not know", () => {
    const turn = {
      toolCalls: [
        call("search_patients", {
          outcome: "DENY",
          reasonCode: "SOMETHING_NEW" as never,
          handoffRequired: false,
          policyVersion: "frontdesk-gate/1",
        }),
      ],
    } as IntakeTurn;
    expect(turnSteps(turn, COPY.es)!.gate.reason).toBe(COPY.es.reasonFallback);
  });

  it("claims no steps on a turn where no tool ran, so the gate never ran", async () => {
    expect(turnSteps(await turnFor("I have an appointment at three."), COPY.en)).toBeNull();
  });
});
