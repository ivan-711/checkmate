"use client";

import { skipToken, useQuery, useQueryClient } from "@tanstack/react-query";
import { Flag, IdCard, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { ReviewResponse, SafetyAlert } from "@/api/types";
import { EvidenceRail } from "@/components/case/EvidenceRail";
import { ReviewPanel } from "@/components/case/ReviewPanel";
import { SourceCardView } from "@/components/case/SourceCardView";
import { ConstructedChip } from "@/components/ui/ConstructedChip";
import { FlagHeadline } from "@/components/ui/FlagHeadline";
import { useAnnounce } from "@/components/ui/LiveRegion";
import { useDataSource } from "@/data/DataSourceProvider";
import { differingFields } from "@/lib/display";
import { flagHeadline, surfacedLine } from "@/lib/flagHeadline";
import { COPY } from "./copy";
import { HANDOFF_KEY, handoffPairKey, raisedAlertsKey, useIntakeSession } from "./intake";

/** What an approval raised, one line per alert, with the way to the full flag card on the Case
 * screen. Neutral like the flag card: no red, no alert role; the pane announces it once, politely. */
function RaisedFlag({
  alerts,
  pairId,
  focusOnMount,
  onFocused,
}: {
  alerts: SafetyAlert[];
  pairId: string;
  focusOnMount: boolean;
  onFocused: () => void;
}) {
  const openCase = useRef<HTMLAnchorElement>(null);
  useEffect(() => {
    if (!focusOnMount) return;
    openCase.current?.focus();
    onFocused();
  }, [focusOnMount, onFocused]);
  const headingId = `raised-flag-${pairId}`;
  return (
    <section
      data-testid="registrar-flag-summary"
      aria-labelledby={headingId}
      className="reveal space-y-2 rounded-lg border-2 border-l-[6px] border-ink-1 border-l-band-keep bg-surface p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Flag aria-hidden size={18} />
        <h3 id={headingId} className="text-[16px] font-semibold uppercase tracking-wider">
          Flagged for clinician review
        </h3>
        {alerts.some((a) => a.constructedScenario) && <ConstructedChip />}
      </div>
      {alerts.map((alert) => (
        <FlagHeadline key={alert.id} alert={alert} testId="registrar-flag-headline" />
      ))}
      <p data-testid="registrar-flag-count" className="text-[16px] text-ink-2">
        {surfacedLine(alerts.length)}
      </p>
      <Link
        ref={openCase}
        href={`/queue/${pairId}`}
        data-testid="open-case-link"
        className="inline-flex h-11 items-center rounded-md border border-border-strong bg-surface px-4 font-semibold text-ink-1 hover:bg-sunken"
      >
        Open case
      </Link>
    </section>
  );
}

/** One pair the gate held, decided by a person through the existing review endpoint. */
function HeldPair({ pairId, index, total }: { pairId: string; index: number; total: number }) {
  const source = useDataSource();
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const pair = useQuery({
    queryKey: handoffPairKey(pairId),
    queryFn: () => source.getCandidatePair(pairId),
  });
  // Written only by this pane's own approval (below); never fetched.
  const raised = useQuery<SafetyAlert[]>({
    queryKey: raisedAlertsKey(pairId),
    queryFn: skipToken,
    gcTime: Infinity,
  }).data;
  const [focusOpenCase, setFocusOpenCase] = useState(false);
  const headingId = `held-heading-${index}`;

  if (pair.isError) {
    return (
      <p className="rounded-lg border border-border-subtle bg-surface p-4">
        Held check-in unavailable: {pair.error.message}. Decisions are paused; nothing was changed.
      </p>
    );
  }
  if (!pair.data) {
    return (
      <p aria-busy="true" className="rounded-lg border border-border-subtle bg-surface p-4 text-ink-3">
        Loading the held check-in
      </p>
    );
  }

  const detail = pair.data;
  const { decision } = detail.pair;
  const alerts = decision.status === "LINKED" ? (raised ?? []) : [];

  function onDecided(response: ReviewResponse) {
    void queryClient.invalidateQueries({ queryKey: HANDOFF_KEY });
    const surfaced = response.decision.status === "LINKED" ? (response.alerts ?? []) : [];
    if (response.decision.status === "LINKED") queryClient.setQueryData(raisedAlertsKey(pairId), surfaced);
    if (surfaced.length > 0) {
      // The flag is what this approval changed: say it once and land on the way to the case.
      const lines = surfaced.map(flagHeadline).join("; ");
      announce(`Link approved. Flagged for clinician review: ${lines}. ${surfacedLine(surfaced.length)}.`);
      setFocusOpenCase(true);
      return;
    }
    // The Case screen's focus target is not on this pane: go on to the next held pair.
    const next = document.getElementById(`held-heading-${index + 1}`);
    (next ?? document.getElementById(headingId))?.focus();
  }
  const differs = differingFields(detail.recordA.normalized, detail.recordB.normalized);
  return (
    <article
      aria-labelledby={headingId}
      className="space-y-3 border-t border-border-subtle pt-3 first:border-t-0 first:pt-0"
    >
      <h3 id={headingId} tabIndex={-1} className="text-[16px] font-semibold uppercase tracking-wider">
        Possible existing chart{total > 1 && ` ${index + 1} of ${total}`}
      </h3>
      <p>
        FrontDesk asked to create a new chart. The identity gate denied it because an existing chart scored{" "}
        {decision.p.toFixed(2)} ({COPY.en.band[decision.band]}).
      </p>
      <div className="grid min-w-0 grid-cols-2 gap-3 max-[640px]:grid-cols-1">
        <SourceCardView card={detail.recordA} differs={differs} />
        <SourceCardView card={detail.recordB} differs={differs} />
      </div>
      <EvidenceRail detail={detail} />
      <p className="flex items-center gap-2 text-[14px] text-ink-2">
        <IdCard aria-hidden size={16} />
        Confirm with the patient before deciding: ask for a phone number or a photo ID.
      </p>
      <ReviewPanel detail={detail} onDecided={onDecided}>
        {alerts.length > 0 && (
          <RaisedFlag
            alerts={alerts}
            pairId={pairId}
            focusOnMount={focusOpenCase}
            onFocused={() => setFocusOpenCase(false)}
          />
        )}
      </ReviewPanel>
    </article>
  );
}

/** UX 3.12: the check-in the gate held. A held check-in exists only because the gate denied an
 * agent action; every pair the turn handed off is listed, each decided on its own. */
export function RegistrarPane() {
  const pairIds = useIntakeSession()?.registration.handoffPairIds ?? [];

  if (pairIds.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-lg border border-border-subtle bg-surface p-6 text-center text-ink-3">
        <ShieldCheck aria-hidden size={32} />
        <p className="font-semibold text-ink-2">No held check-ins.</p>
        <p>When the identity gate denies a new chart, the check-in waits here for a registrar.</p>
      </div>
    );
  }

  return (
    <section
      data-testid="registrar-held"
      aria-label="Held check-ins"
      className="space-y-3 rounded-lg border border-border-subtle bg-surface p-4"
    >
      <p className="text-right text-[14px] text-ink-2">Held check-ins ({pairIds.length})</p>
      {pairIds.map((pairId, index) => (
        <HeldPair key={pairId} pairId={pairId} index={index} total={pairIds.length} />
      ))}
    </section>
  );
}
