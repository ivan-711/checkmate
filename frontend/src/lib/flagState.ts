import type { SafetyAlert } from "@/api/types";
import type { CaseData } from "@/data/source";

export type FlagState =
  | { kind: "idle" }
  | { kind: "silent" }
  | { kind: "none" }
  | { kind: "unavailable" }
  | { kind: "raised"; alert: SafetyAlert };

/** The flag follows the human decision, never the score: no approved link, no rule run. */
export function flagState({ detail, outcome, alertsKnown }: CaseData): FlagState {
  if (!detail) return { kind: "idle" };
  const { status } = detail.pair.decision;
  if (status === "REJECTED") return { kind: "silent" };
  if (status !== "LINKED") return { kind: "idle" };
  if (!outcome || !alertsKnown) return { kind: "unavailable" };
  const alert = outcome.alerts?.[0];
  return alert ? { kind: "raised", alert } : { kind: "none" };
}
