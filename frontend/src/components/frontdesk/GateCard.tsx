"use client";

import { forwardRef } from "react";
import type { ToolCallCandidate, ToolCallRecord } from "@/api/types";
import { rankContributions } from "@/lib/display";
import { kioskSourceLabel, type KioskCopy } from "./copy";

const EVIDENCE_ROWS = 5; // UX 3.11: up to 5 rows, by absolute weight

function signed(logit: number): string {
  return `${logit >= 0 ? "+" : "-"}${Math.abs(logit).toFixed(2)}`;
}

/** Your half of the mark, a dashed half for the chart that may be yours, and the bar the gate
 * draws between them. */
function GateMark() {
  return (
    <svg className="k-gmark" viewBox="0 0 44 28" aria-hidden>
      <path className="mine" d="M13 4A10 10 0 0 0 13 24Z" />
      <path className="theirs" d="M31 4A10 10 0 0 1 31 24Z" />
      <line className="bar" x1="22" y1="3" x2="22" y2="25" />
    </svg>
  );
}

/** The gate's denial of a new chart: the only amber surface, once per denial (CONCEPT.md §4). It
 * says what FrontDesk asked, why the gate said no, and what happens next, in the patient's words.
 * The candidate is masked and sits under Details: the kiosk never shows another chart's name,
 * date, address or phone. Never red. `steps` is how many checklist rows precede it, so the card
 * drops in after the last row has checked. */
export const GateCard = forwardRef<
  HTMLDivElement,
  { call: ToolCallRecord; candidate: ToolCallCandidate; t: KioskCopy; reviewing?: boolean; steps?: number }
>(function GateCard({ call, candidate, t, reviewing = false, steps = 0 }, ref) {
  const score = candidate.p.toFixed(2);
  const [before, , after] = t.gateBody(score);
  // The registrar rail's rows for the same pair, feature by feature: the gate sends only its top
  // features, so a sum per field would neither be the field's total nor match the rail.
  const rows = rankContributions(candidate.topContributions ?? [], t.feature).slice(0, EVIDENCE_ROWS);
  return (
    <div
      ref={ref}
      data-testid="gate-card"
      data-policy={call.gate.policyVersion}
      data-tool={call.toolName}
      className="k-gate"
      style={{ "--steps": steps } as React.CSSProperties}
    >
      <p className="k-gate-top">
        <GateMark />
        {t.gateLabel}
      </p>
      <h3 className="k-gate-title">{t.gateTitle}</h3>
      <p className="k-gate-body">
        {before}
        <b className="num">{score}</b>
        {after}
      </p>
      <p className="k-gate-held">{reviewing ? t.gateReview : t.gateHeld}</p>
      <details className="k-gate-details">
        <summary>{t.details}</summary>
        <div className="k-gate-candidate">
          <p className="k-gate-row">
            <span className="k-gate-lbl">{t.gateCandidate}</span>
            <span className="num k-gate-score">{score}</span>
            <span className="k-band">{t.band[candidate.band]}</span>
          </p>
          <p>{t.gateChart(candidate.recordId.slice(-2), kioskSourceLabel(candidate.sourceSystem, t))}</p>
          {candidate.band === "AUTO_LINK" && <p>{t.gateAutoLinkOff}</p>}
          <ul className="k-gate-evidence">
            {rows.map((c) => (
              <li key={c.feature}>
                <span>{c.label}</span>
                {c.missing ? <span className="k-gate-none">{t.noEvidence}</span> : <span className="num">{signed(c.logit)}</span>}
              </li>
            ))}
          </ul>
          <p className="k-gate-hidden">{t.gateHidden}</p>
        </div>
      </details>
    </div>
  );
});
