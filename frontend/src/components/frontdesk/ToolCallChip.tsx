"use client";

import { FilePlus2, Paperclip, Search, ShieldAlert, ShieldCheck, Wrench } from "lucide-react";
import { useState } from "react";
import type { ToolCallRecord } from "@/api/types";
import type { KioskCopy } from "./copy";

const TOOL_ICONS = {
  search_patients: Search,
  propose_new_chart: FilePlus2,
  attach_history: Paperclip,
} as const;

const OUTCOME = {
  ALLOW: { Icon: ShieldCheck, className: "border-allowed-border bg-allowed-bg", ink: "text-allowed-ink" },
  DENY: { Icon: ShieldAlert, className: "border-denied-border bg-denied-bg", ink: "text-denied-ink" },
} as const;

function summary(call: ToolCallRecord, t: KioskCopy): string {
  const name = call.toolName as keyof KioskCopy["tool"];
  return name in t.tool ? t.tool[name](call.candidates?.length ?? 0) : call.toolName;
}

/** One agent action and the gate's answer. The state comes from the gate result in the API
 * response, never from the agent's text. A denial that has a gate card does not expand. */
export function ToolCallChip({
  call,
  t,
  hasGateCard,
}: {
  call: ToolCallRecord;
  t: KioskCopy;
  hasGateCard: boolean;
}) {
  const [open, setOpen] = useState(false);
  const outcome = OUTCOME[call.gate.outcome];
  const ToolIcon = TOOL_ICONS[call.toolName as keyof typeof TOOL_ICONS] ?? Wrench;
  const row = (
    <>
      <ToolIcon aria-hidden size={20} className="shrink-0 text-ink-2" />
      <span className="font-mono text-[16px] text-ink-2">{call.toolName}</span>
      <span aria-hidden className="text-ink-3">
        ·
      </span>
      <span className="text-[16px] text-ink-1">{summary(call, t)}</span>
      <span className={`ml-auto inline-flex items-center gap-1 text-[18px] font-semibold ${outcome.ink}`}>
        <outcome.Icon aria-hidden size={16} />
        {call.gate.outcome === "ALLOW" ? t.allowed : t.denied}
      </span>
    </>
  );
  const box = `flex min-h-12 w-full flex-wrap items-center gap-2 rounded border px-3 py-2 text-left ${outcome.className}`;
  return (
    <div data-testid="tool-call-chip" data-tool={call.toolName} data-outcome={call.gate.outcome}>
      {hasGateCard ? (
        <div className={box}>{row}</div>
      ) : (
        <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className={box}>
          {row}
        </button>
      )}
      {open && !hasGateCard && (
        <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-4 px-3 text-[16px] text-ink-2">
          <dt>{t.detailDecision}</dt>
          <dd className="font-mono">{call.gate.reasonCode ?? call.gate.outcome}</dd>
          <dt>{t.detailLatency}</dt>
          <dd className="tabular-nums">{call.latencyMs} ms</dd>
        </dl>
      )}
    </div>
  );
}
