"use client";

import { ArrowRight, ShieldAlert } from "lucide-react";
import { forwardRef } from "react";
import type { ToolCallCandidate, ToolCallRecord } from "@/api/types";
import { BandChip } from "@/components/ui/BandChip";
import { rankContributions } from "@/lib/display";
import { sourceSystemLabel, type KioskCopy } from "./copy";

const EVIDENCE_ROWS = 5; // UX 3.11: up to 5 rows, by absolute weight

function signed(logit: number): string {
  return `${logit >= 0 ? "+" : "-"}${Math.abs(logit).toFixed(2)}`;
}

/** The gate's denial of a new chart, shown under the denied chip. The candidate is masked: the
 * kiosk never shows another chart's name, date, address or phone. Amber, never red. */
export const GateCard = forwardRef<
  HTMLDivElement,
  { call: ToolCallRecord; candidate: ToolCallCandidate; t: KioskCopy }
>(function GateCard({ call, candidate, t }, ref) {
  const score = candidate.p.toFixed(2);
  // The registrar rail's rows for the same pair, feature by feature: the gate sends only its top
  // features, so a sum per field would neither be the field's total nor match the rail.
  const rows = rankContributions(candidate.topContributions ?? [], t.feature).slice(0, EVIDENCE_ROWS);
  return (
    <div
      ref={ref}
      data-testid="gate-card"
      className="enter rounded-lg border border-l-[6px] border-denied-border border-l-gate-bar bg-gate-bg px-5 py-4 text-[16px]"
    >
      <h4 className="flex items-center gap-2 text-[24px] font-semibold leading-8 text-ink-1">
        <ShieldAlert aria-hidden size={24} className="shrink-0 text-denied-ink" />
        {t.gateTitle}
      </h4>
      <p className="mt-1">{t.gateDenied}</p>
      <p>
        {t.gateReason(score, t.band[candidate.band])} {t.gatePolicy[0]}
        <span className="whitespace-nowrap">{call.gate.policyVersion}</span>
        {t.gatePolicy[1]}
      </p>
      <div className="mt-3 rounded-md border border-border-subtle bg-surface p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold">{t.gateCandidate}</span>
          <span className="ml-auto text-[20px] font-semibold tabular-nums">{score}</span>
          <BandChip band={candidate.band} label={t.band[candidate.band]} />
        </div>
        <p className="text-ink-2">
          {t.gateChart(candidate.recordId.slice(-2), sourceSystemLabel(candidate.sourceSystem))}
        </p>
        <ul className="mt-2 space-y-0.5">
          {rows.map((c) => (
            <li key={c.feature} className="grid grid-cols-[minmax(0,1fr)_auto] gap-2">
              <span>{c.label}</span>
              {c.missing ? (
                <span className="text-right text-ink-3">{t.noEvidence}</span>
              ) : (
                <span className="text-right tabular-nums">{signed(c.logit)}</span>
              )}
            </li>
          ))}
        </ul>
        <p className="mt-2 text-ink-3">{t.gateHidden}</p>
      </div>
      <p className="mt-3 flex items-center gap-2 font-semibold">
        <ArrowRight aria-hidden size={20} />
        {t.gateHandoff}
      </p>
    </div>
  );
});
