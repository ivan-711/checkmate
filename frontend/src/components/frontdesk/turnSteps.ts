import type { IntakeTurn, ToolCallRecord } from "@/api/types";
import type { KioskCopy } from "./copy";

export type GateOutcome = "HELD" | "PASSED";

export interface TurnStep {
  /** The step in the past tense, in the patient's words. */
  label: string;
  /** The tool call behind the step (null for reading the message), kept for data attributes and
   * the expanded detail; its id never appears in the label. */
  call: ToolCallRecord | null;
}

export interface TurnSteps {
  /** What the agent did this turn, in call order. */
  done: TurnStep[];
  /** The gate's answer: the last step, a fact read from the gate results, never from the agent. */
  gate: {
    outcome: GateOutcome;
    label: string;
    /** The gate's code, kept for tests and data attributes; the screen shows `reason`. */
    reasonCode: string | null;
    /** The code in plain words, or a neutral phrase for a code the copy deck does not know. */
    reason: string | null;
    policy: string;
  };
}

function stepLabel(call: ToolCallRecord, t: KioskCopy): string {
  const step = t.step[call.toolName];
  return step ? step(call.candidates?.length ?? 0) : t.stepOther;
}

/** The turn as a short checklist ending on the gate's step. Null when no tool ran: the gate
 * never decided anything, so there is no fact to state. */
export function turnSteps(turn: IntakeTurn, t: KioskCopy): TurnSteps | null {
  const calls = turn.toolCalls ?? [];
  if (calls.length === 0) return null;
  const done: TurnStep[] = [
    { label: t.stepRead, call: null },
    ...calls.map((call) => ({ label: stepLabel(call, t), call })),
  ];
  // One denial holds the whole turn; the first denial is the reason the patient is waiting.
  const denied = calls.find((c) => c.gate.outcome === "DENY");
  const decisive = denied ?? calls[calls.length - 1];
  const outcome: GateOutcome = denied ? "HELD" : "PASSED";
  return {
    done,
    gate: {
      outcome,
      label: t.gateStep[outcome],
      reasonCode: denied?.gate.reasonCode ?? null,
      reason: denied ? (t.reason[denied.gate.reasonCode ?? ""] ?? t.reasonFallback) : null,
      policy: decisive.gate.policyVersion,
    },
  };
}
