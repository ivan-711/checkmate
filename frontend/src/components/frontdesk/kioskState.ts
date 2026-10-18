import type { IntakeSession, ToolCallRecord } from "@/api/types";

/** What the kiosk shows, read from the check-in and the registrar's decision. The four the Desk
 * stage follows (idle, working, held, done) match the DeskState kiosk union; `replied` is a turn
 * the gate did not hold, `rejected` a check-in every held pair was rejected on. */
export type KioskState = "idle" | "working" | "held" | "replied" | "done" | "rejected";

export type HandoffDecision = "LINKED" | "REJECTED" | null;

/** The denied new chart that a registrar now holds: the card the demo is about. */
export function gateDenial(call: ToolCallRecord) {
  const candidate = call.candidates?.[0];
  const held = call.gate.outcome === "DENY" && call.gate.reasonCode === "CANDIDATE_IN_REVIEW_OR_HIGHER";
  return held && candidate ? candidate : null;
}

export function kioskState({
  session,
  pending,
  failed,
  decided,
}: {
  session: IntakeSession | undefined;
  /** A turn is in flight. */
  pending: boolean;
  /** The last send failed and the message is back in the composer. */
  failed: boolean;
  decided: HandoffDecision;
}): KioskState {
  if (pending) return "working";
  if (decided === "LINKED") return "done";
  if (decided === "REJECTED") return "rejected";
  const turns = session?.turns ?? [];
  if (turns.length === 0) return failed ? "replied" : "idle";
  const held = session?.registration.state === "PENDING_REGISTRAR";
  return held ? "held" : "replied";
}

/** The given name the agent passed to its tools (what the patient typed, as the gate validated
 * it), so the kiosk can greet the person by name. Null when no tool carried one. */
export function patientGivenName(session: IntakeSession | undefined): string | null {
  for (const turn of session?.turns ?? []) {
    for (const call of turn.toolCalls ?? []) {
      const name = call.args?.givenName;
      if (typeof name === "string" && name.trim()) return name.trim();
    }
  }
  return null;
}
