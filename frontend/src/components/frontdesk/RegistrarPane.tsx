"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { IdCard, ShieldCheck } from "lucide-react";
import { EvidenceRail } from "@/components/case/EvidenceRail";
import { ReviewPanel } from "@/components/case/ReviewPanel";
import { SourceCardView } from "@/components/case/SourceCardView";
import { useDataSource } from "@/data/DataSourceProvider";
import { differingFields } from "@/lib/display";
import { COPY } from "./copy";
import { HANDOFF_KEY, handoffPairKey, useIntakeSession } from "./intake";

/** One pair the gate held, decided by a person through the existing review endpoint. */
function HeldPair({ pairId, index, total }: { pairId: string; index: number; total: number }) {
  const source = useDataSource();
  const queryClient = useQueryClient();
  const pair = useQuery({
    queryKey: handoffPairKey(pairId),
    queryFn: () => source.getCandidatePair(pairId),
  });
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
      <ReviewPanel
        detail={detail}
        onDecided={() => {
          void queryClient.invalidateQueries({ queryKey: HANDOFF_KEY });
          // The Case screen's focus target is not on this pane: go on to the next held pair.
          const next = document.getElementById(`held-heading-${index + 1}`);
          (next ?? document.getElementById(headingId))?.focus();
        }}
      />
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
