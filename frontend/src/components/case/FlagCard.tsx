import { Flag } from "lucide-react";
import type { SafetyAlert } from "@/api/types";
import { ConstructedChip } from "@/components/ui/ConstructedChip";

export type FlagState =
  | { kind: "idle" }
  | { kind: "silent" }
  | { kind: "none" }
  | { kind: "unavailable" }
  | { kind: "raised"; alert: SafetyAlert };

const QUIET_LINES = {
  idle: "No safety check yet. It runs after a link is approved.",
  silent: "No safety check ran: no link was approved.",
  unavailable:
    "Safety check result unavailable in this tab: this source has no alerts read route yet. No conclusion is shown.",
  none: "The rule did not flag this linked record. Absence of a flag is not evidence that no conflict exists.",
} as const;

/** Neutral by design: it flags for review and does not alarm, so no red and no role="alert". */
export function FlagCard({ state }: { state: FlagState }) {
  if (state.kind !== "raised") {
    return (
      <p
        data-testid="flag-quiet"
        className="rounded-lg border border-border-strong bg-surface p-4 text-ink-2"
      >
        {QUIET_LINES[state.kind]}
      </p>
    );
  }
  const { alert } = state;
  return (
    <article
      aria-labelledby="flag-heading"
      className="enter enter-last rounded-lg border-2 border-l-[6px] border-ink-1 border-l-band-keep bg-surface p-4"
    >
      <header className="mb-2 flex flex-wrap items-center gap-2">
        <Flag aria-hidden size={20} />
        <h2 id="flag-heading" className="text-[18px] font-semibold uppercase tracking-wider">
          Flagged for clinician review
        </h2>
        {alert.constructedScenario && <ConstructedChip />}
      </header>
      <p className="mb-2">{alert.cardText}</p>
      {alert.citation && (
        <p className="mb-2 text-[16px] text-ink-2">
          Source:{" "}
          <a href={alert.citation.url} target="_blank" rel="noreferrer" className="underline">
            {alert.citation.labelName}, DailyMed, revised {alert.citation.revised}
          </a>
        </p>
      )}
      <p className="text-[14px] text-ink-3">{alert.cardFooter}</p>
    </article>
  );
}
