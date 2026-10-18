"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { EvidenceRail } from "@/components/case/EvidenceRail";
import { ReviewPanel } from "@/components/case/ReviewPanel";
import { Timeline } from "@/components/case/Timeline";
import { attachablePair } from "@/components/case/reviewPlan";
import { HANDOFF_KEY, useIntakeSession } from "@/components/frontdesk/intake";
import { useDataSource } from "@/data/DataSourceProvider";
import { actorName } from "@/lib/display";
import { newChartFacts, type NewChartFacts } from "@/lib/kioskNewChart";
import { useDesk } from "./DeskContext";
import type { useDeskCase } from "./useDeskCase";

type DeskCase = ReturnType<typeof useDeskCase>;

const EYEBROW = "text-[15px] font-semibold text-ink-2";
const TITLE = "my-2 font-display text-[26px] font-[680] leading-[1.12] tracking-[-0.02em]";
const LEAD = "mb-4 text-[16px] leading-[1.45] text-ink-2";
const QUIET_BUTTON =
  "flex h-[52px] w-full items-center justify-center gap-2 rounded-control text-[17px] font-semibold text-ink shadow-[inset_0_0_0_1.5px_var(--hair-strong)] hover:bg-ink/5 disabled:text-ink-3";
const INK_BUTTON =
  "flex h-[52px] w-full items-center justify-center gap-2 rounded-control bg-ink text-[17px] font-semibold text-paper hover:bg-black disabled:bg-hair disabled:text-ink-3";

const KEPT_APART = {
  INSUFFICIENT_EVIDENCE: "Recorded as “not enough evidence”. These records can be compared again.",
  DIFFERENT_PERSON: "Recorded as “different person”. These records will not be suggested again.",
} as const;

function ResolveButton({
  c,
  label,
  tone,
  onResolve,
}: {
  c: DeskCase;
  label: string;
  tone: "ink" | "quiet";
  onResolve: () => void;
}) {
  return (
    <button
      type="button"
      data-testid="resolve-button"
      onClick={onResolve}
      disabled={c.resolve.isPending || c.sessionChanging}
      className={tone === "ink" ? INK_BUTTON : QUIET_BUTTON}
    >
      {c.resolve.isPending ? "Resolving…" : label}
      <kbd aria-hidden="true">R</kbd>
    </button>
  );
}

/** The fallback for decision 1: when the check-in was not attached with the link (the row was
 * off, or its approval failed), one more explicit approval attaches it. */
function AttachCheckIn({ c, registrar }: { c: DeskCase; registrar: string }) {
  const source = useDataSource();
  const queryClient = useQueryClient();
  // Once any hand-off pair is linked the check-in is attached; a weaker pair left proposed is not offered.
  const attached = c.handoffs.some((d) => d.pair.decision.status === "LINKED");
  const pair = c.detail && !attached ? attachablePair(c.handoffs, c.detail.pair.id) : null;
  // One Idempotency-Key per intent, kept until a response, so a retry resends it.
  const key = useRef<string | null>(null);
  const attach = useMutation({
    mutationFn: (pairId: string) => {
      key.current ??= crypto.randomUUID();
      return source.review(
        pairId,
        { action: "APPROVE", actor: `registrar:${registrar}`, note: null },
        key.current,
      );
    },
    onSuccess: async (response, pairId) => {
      key.current = null;
      c.writeAttach(pairId, response);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: HANDOFF_KEY }),
        queryClient.invalidateQueries({ queryKey: ["events"] }),
        queryClient.invalidateQueries({ queryKey: ["tiles"] }),
      ]);
    },
  });
  if (!pair) return null;
  return (
    <div className="space-y-2 rounded-control p-3 shadow-[inset_0_0_0_1px_var(--hair)]">
      <p className="text-[15px] leading-[1.4] text-ink-2">
        The kiosk check-in is still waiting. It matches this record at {pair.pair.decision.p.toFixed(2)}.
      </p>
      <button
        type="button"
        data-testid="attach-checkin-button"
        onClick={() => attach.mutate(pair.pair.id)}
        disabled={attach.isPending}
        className={QUIET_BUTTON}
      >
        {attach.isPending ? "Attaching…" : "Attach check-in"}
      </button>
      {attach.isError && <p className="text-[15px] text-ink">Not attached: {attach.error.message}</p>}
    </div>
  );
}

/** The decision line of a rejection. After a Reject made here the sheet unmounts with its focused
 * control, so focus moves to this line instead of falling to the page. */
function RejectedLine({ c, name }: { c: DeskCase; name: string }) {
  const line = useRef<HTMLParagraphElement>(null);
  const { justRejected, setJustRejected } = c;
  useEffect(() => {
    if (!justRejected) return;
    line.current?.focus();
    setJustRejected(false);
  }, [justRejected, setJustRejected]);
  return (
    <p ref={line} tabIndex={-1} className={EYEBROW}>
      Rejected by {name}
    </p>
  );
}

/** The kiosk's check-in opened a new chart: who, as the patient typed it, and why nothing waits here. */
function NewChartCard({ facts }: { facts: NewChartFacts }) {
  return (
    <div data-pane="new-chart" data-testid="new-chart-card">
      <p className={EYEBROW}>From the kiosk</p>
      <h2 className={TITLE}>New chart opened</h2>
      <p className="text-[20px] font-semibold leading-tight text-ink">{facts.name}</p>
      <dl className="mt-2 mb-4 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[16px]">
        {facts.birthDate && (
          <>
            <dt className="text-ink-2">Born</dt>
            <dd className="text-ink">{facts.birthDate}</dd>
          </>
        )}
        {facts.phone && (
          <>
            <dt className="text-ink-2">Phone</dt>
            <dd className="text-ink">{facts.phone}</dd>
          </>
        )}
      </dl>
      <p className={LEAD}>
        The identity gate allowed a new chart. Nothing to resolve; a registrar finishes the registration in
        person.
      </p>
    </div>
  );
}

/** The registrar's column (CONCEPT.md §8, L4): one pane per Desk state, so exactly one of Resolve,
 * the evidence and Approve, the confirm sheet, History, or "Kept apart" is on screen. */
export function DecisionColumn({ c, onResolve }: { c: DeskCase; onResolve: () => void }) {
  const { desk, sheet, setSheet } = useDesk();
  const newChart = newChartFacts(useIntakeSession());
  const noSession = c.caseQuery.isError && !c.detail;
  if (c.caseQuery.isPending || noSession) return null;
  const detail = c.detail;

  if (detail && (desk === "review" || desk === "confirm")) {
    return (
      <div
        data-testid="candidate-pair"
        data-pane={desk}
        aria-busy={c.resolve.isPending || c.sessionChanging}
        className="absolute inset-0 flex flex-col gap-4"
      >
        {desk === "review" && (
          <div className="min-h-0 flex-1 overflow-y-auto pr-1">
            <EvidenceRail detail={detail} thresholds={c.thresholds} />
          </div>
        )}
        <div className={desk === "confirm" ? "min-h-0 flex-1" : "shrink-0"}>
          <ReviewPanel
            detail={detail}
            handoffPairs={c.handoffs}
            sheet={sheet}
            reopened={c.reopened}
            onSheetChange={setSheet}
            onConfirmed={c.onConfirmed}
            onDecided={c.onDecided}
          />
        </div>
      </div>
    );
  }

  if (detail && desk === "linked") {
    const { decision } = detail.pair;
    return (
      <div data-pane="linked" className="absolute inset-0 space-y-4 overflow-y-auto pr-1">
        <AttachCheckIn c={c} registrar={actorName(decision.actor)} />
        <Timeline events={c.timeline.data} cards={c.cards} decision={decision} />
      </div>
    );
  }

  if (detail && desk === "rejected") {
    const { decision } = detail.pair;
    const reason = decision.reasonCode ?? "INSUFFICIENT_EVIDENCE";
    return (
      <div data-pane="rejected">
        <RejectedLine c={c} name={actorName(decision.actor)} />
        <h2 className={TITLE}>Kept apart</h2>
        <p className={LEAD}>{KEPT_APART[reason]} Nothing was linked. No safety check ran.</p>
        <ResolveButton c={c} label="Resolve again" tone="quiet" onResolve={onResolve} />
      </div>
    );
  }

  // The gate let the kiosk open a new chart: say so, instead of offering a comparison nobody asked for.
  if (desk === "idle" && newChart) return <NewChartCard facts={newChart} />;

  const held = desk === "held";
  return (
    <div data-pane={held ? "held" : "idle"}>
      <p className={EYEBROW}>{held ? "Ready for you" : "Not compared yet"}</p>
      <h2 className={TITLE}>{held ? "Why the gate held this check-in" : "Same person, or two people?"}</h2>
      <p className={LEAD}>
        {held
          ? "FrontDesk asked to open a new chart. The gate denied it because an existing chart may already be this person's. No chart was opened. Nothing was linked."
          : "Resolving compares these records field by field and scores the match. It links nothing."}
      </p>
      {c.resolve.isError && (
        <p className="mb-2 text-[15px] text-ink-2">Resolve failed: {c.resolve.error.message}</p>
      )}
      <ResolveButton c={c} label="Resolve identity" tone={held ? "ink" : "quiet"} onResolve={onResolve} />
      <p className="mt-3 text-[15px] text-ink-3">Nothing links until a registrar approves.</p>
    </div>
  );
}
