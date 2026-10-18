"use client";

import { useState } from "react";
import type { ToolCallRecord } from "@/api/types";
import type { KioskCopy } from "./copy";
import { KioskMark, Tick } from "./KioskMark";
import type { TurnStep, TurnSteps } from "./turnSteps";

/** One tool step. The patient reads the past-tense line; the tool's id, the gate's code and the
 * latency sit in an expanded detail (CONCEPT.md §8: the id stays in data-tool and the detail). */
function ToolStep({ step, call, index, t }: { step: TurnStep; call: ToolCallRecord; index: number; t: KioskCopy }) {
  const [open, setOpen] = useState(false);
  return (
    <li
      data-testid="tool-call-chip"
      data-tool={call.toolName}
      data-outcome={call.gate.outcome}
      className="k-step on"
      style={{ "--i": index } as React.CSSProperties}
    >
      <Tick />
      <div className="k-step-body">
        <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="k-step-btn">
          {step.label}
        </button>
        {open && (
          <dl className="k-step-detail">
            <dt>{t.detailTool}</dt>
            <dd className="font-mono">{call.toolName}</dd>
            <dt>{t.detailDecision}</dt>
            <dd className="font-mono">{call.gate.reasonCode ?? call.gate.outcome}</dd>
            <dt>{t.detailLatency}</dt>
            <dd className="num">{call.latencyMs} ms</dd>
          </dl>
        )}
      </div>
    </li>
  );
}

/** "Working on it" with a past-tense checklist that fills in, ending on the deterministic gate's
 * step (CONCEPT.md §5, touch 3). While the turn is in flight it shows the one thing that is true,
 * that the message is being read, and a progress line; once the turn lands the title reads
 * "Ready" and the steps check in one after another, the gate last. */
export function WorkChecklist({ steps, t }: { steps: TurnSteps | null; t: KioskCopy }) {
  const working = steps === null;
  return (
    <div className="k-work">
      <p className="k-work-title">
        <KioskMark className="k-spin" />
        {working ? t.working : t.ready}
      </p>
      {working ? (
        <ol aria-label={t.stepsLabel} className="k-steps">
          <li className="k-step on pending" style={{ "--i": 0 } as React.CSSProperties}>
            <Tick kind="pending" />
            <span className="k-step-body">{t.reading}</span>
          </li>
        </ol>
      ) : (
        <ol data-testid="turn-steps" aria-label={t.stepsLabel} className="k-steps">
          {/* The same tool can run twice in a turn, so rows are keyed by position. */}
          {steps.done.map((step, i) =>
            step.call ? (
              <ToolStep key={i} step={step} call={step.call} index={i} t={t} />
            ) : (
              <li key={i} className="k-step on" style={{ "--i": i } as React.CSSProperties}>
                <Tick />
                <span className="k-step-body">{step.label}</span>
              </li>
            ),
          )}
          <li
            data-testid="gate-fact"
            data-voice="verified"
            data-outcome={steps.gate.outcome}
            data-reason={steps.gate.reasonCode ?? undefined}
            data-policy={steps.gate.policy}
            className={`k-step on ${steps.gate.outcome === "HELD" ? "hold" : ""}`}
            style={{ "--i": steps.done.length } as React.CSSProperties}
          >
            <Tick kind={steps.gate.outcome === "HELD" ? "hold" : "done"} />
            <span className="k-step-body">{steps.gate.label}</span>
          </li>
        </ol>
      )}
      {working && (
        <div className="k-gate-line" aria-hidden>
          <i />
        </div>
      )}
    </div>
  );
}
