import type { IntakeSession } from "@/api/types";

/** What the Desk shows when the gate let the kiosk open a new chart. */
export interface NewChartFacts {
  name: string;
  birthDate: string | null;
  phone: string | null;
}

type ChartArgs = {
  givenName?: string;
  familyName?: string;
  birthDate?: string;
  phone?: string;
  evidence?: Partial<Record<"givenName" | "familyName" | "birthDate" | "phone", string>>;
};

/** The new chart the current check-in opened, read from the allowed propose_new_chart call:
 * each field as the patient typed it (its quoted evidence), else the validated argument. Null
 * unless the check-in's registration is NEW_CHART, so a held check-in never shows it. */
export function newChartFacts(session: IntakeSession | undefined): NewChartFacts | null {
  if (session?.registration.state !== "NEW_CHART") return null;
  const call = (session.turns ?? [])
    .flatMap((turn) => turn.toolCalls ?? [])
    .filter((c) => c.toolName === "propose_new_chart" && c.gate.outcome === "ALLOW")
    .at(-1);
  const args = (call?.args ?? {}) as ChartArgs;
  const typed = (field: keyof NonNullable<ChartArgs["evidence"]>) =>
    args.evidence?.[field] ?? args[field] ?? null;
  const name = [typed("givenName"), typed("familyName")].filter(Boolean).join(" ");
  return { name, birthDate: typed("birthDate"), phone: typed("phone") };
}
