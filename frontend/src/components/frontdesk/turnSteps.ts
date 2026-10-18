import type { IntakeTurn } from "@/api/types";
import type { KioskCopy } from "./copy";

export type GateFactOutcome = "HELD" | "PASSED";

export interface TurnSteps {
  /** What the agent did this turn, in the past tense, in call order. */
  done: string[];
  /** The gate's answer: the last line, a fact read from the gate results, never from the agent. */
  fact: {
    outcome: GateFactOutcome;
    label: string;
    /** The gate's code, kept for tests and data attributes; the screen shows `reason`. */
    reasonCode: string | null;
    /** The code in plain words, or a neutral phrase for a code the copy deck does not know. */
    reason: string | null;
    policy: string;
  };
}

/** The turn as a short checklist ending on the gate's fact. Null when no tool ran: the gate
 * never decided anything, so there is no fact to state. */
export function turnSteps(turn: IntakeTurn, t: KioskCopy): TurnSteps | null {
  const calls = turn.toolCalls ?? [];
  if (calls.length === 0) return null;
  const done = [t.stepRead, ...calls.map((c) => t.step[c.toolName] ?? t.stepOther(c.toolName))];
  // One denial holds the whole turn; the first denial is the reason the patient is waiting.
  const denied = calls.find((c) => c.gate.outcome === "DENY");
  const decisive = denied ?? calls[calls.length - 1];
  const outcome: GateFactOutcome = denied ? "HELD" : "PASSED";
  return {
    done,
    fact: {
      outcome,
      label: t.factLabel[outcome],
      reasonCode: denied?.gate.reasonCode ?? null,
      reason: denied ? (t.reason[denied.gate.reasonCode ?? ""] ?? t.reasonFallback) : null,
      policy: decisive.gate.policyVersion,
    },
  };
}
