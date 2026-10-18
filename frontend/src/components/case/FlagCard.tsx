import { Flag } from "lucide-react";
import { ConstructedChip } from "@/components/ui/ConstructedChip";
import { footerWithoutRule } from "@/lib/display";
import type { FlagState } from "@/lib/flagState";
import { VerifiedTag } from "@/components/ui/VerifiedTag";

const QUIET_LINES = {
  idle: "No safety check yet. It runs after a link is approved.",
  silent: "No safety check ran: no link was approved.",
  unavailable:
    "The safety check result for this link is not available on this screen. No conclusion is shown.",
  none: "The rule did not flag this linked record. Absence of a flag is not evidence that no conflict exists.",
} as const;

/** Neutral by design: it flags for review and does not alarm, so no red and no role="alert". */
export function FlagCard({ state }: { state: FlagState }) {
  if (state.kind !== "raised") {
    return (
      <p
        data-testid="flag-quiet"
        className="flex items-start gap-2 rounded-lg border border-border-subtle bg-sunken p-4 text-[16px] text-ink-2"
      >
        <Flag aria-hidden size={16} className="mt-1 shrink-0 text-ink-3" />
        {QUIET_LINES[state.kind]}
      </p>
    );
  }
  const { alert } = state;
  return (
    <article
      data-testid="flag-card"
      aria-labelledby="flag-heading"
      className="enter enter-last rounded-lg border-2 border-l-[6px] border-ink-1 border-l-band-keep bg-surface p-4"
    >
      <header className="mb-2 flex flex-wrap items-center gap-2">
        <Flag aria-hidden size={20} />
        <h2 id="flag-heading" className="text-[18px] font-semibold uppercase tracking-wider">
          Flagged for clinician review
        </h2>
        {alert.constructedScenario && <ConstructedChip />}
        <VerifiedTag label="Verified" />
        {/* The rule id sits once, in the header; the footer below carries the rule's limits. */}
        <span className="ml-auto font-mono text-[14px] text-ink-3">
          Rule <span data-testid="flag-card-rule-id">{alert.ruleId}</span> {alert.ruleVersion}
        </span>
      </header>
      <p className="mb-2 max-w-[68ch]">{alert.cardText}</p>
      {alert.citation && (
        <p className="mb-2 text-[16px] text-ink-2">
          Source:{" "}
          <a href={alert.citation.url} target="_blank" rel="noreferrer" className="underline">
            {alert.citation.labelName}, DailyMed, revised {alert.citation.revised}
          </a>
        </p>
      )}
      <p className="max-w-[68ch] text-[14px] text-ink-3">
        {footerWithoutRule(alert.cardFooter, alert.ruleId, alert.ruleVersion)}
      </p>
    </article>
  );
}
