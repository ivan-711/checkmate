"use client";

import { skipToken, useQuery, useQueryClient } from "@tanstack/react-query";
import { IdCard, ShieldCheck } from "lucide-react";
import type { IntakeSession } from "@/api/types";
import { EvidenceRail } from "@/components/case/EvidenceRail";
import { ReviewPanel } from "@/components/case/ReviewPanel";
import { SourceCardView } from "@/components/case/SourceCardView";
import { BandChip } from "@/components/ui/BandChip";
import { useDataSource } from "@/data/DataSourceProvider";
import { differingFields } from "@/lib/display";
import { INTAKE_KEY } from "./KioskPane";

/** The pair a held check-in waits on; the kiosk reads the same entry to tell the patient. */
export const handoffPairKey = (pairId: string | null) => ["handoff-pair", pairId] as const;

/** Reads the kiosk's check-in without starting one: the kiosk owns that request. */
export function useIntakeSession() {
  return useQuery<IntakeSession>({ queryKey: INTAKE_KEY, queryFn: skipToken });
}

export function useHandoffPair() {
  const source = useDataSource();
  const pairId = useIntakeSession().data?.registration.handoffPairIds?.[0] ?? null;
  return useQuery({
    queryKey: handoffPairKey(pairId),
    queryFn: pairId ? () => source.getCandidatePair(pairId) : skipToken,
  });
}

/** UX 3.12: the check-in the gate held, decided by a person through the existing review
 * endpoint. A held check-in exists only because the gate denied an agent action. */
export function RegistrarPane() {
  const queryClient = useQueryClient();
  const held = useIntakeSession().data?.registration.handoffPairIds?.length ?? 0;
  const pair = useHandoffPair();

  if (held === 0) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-lg border border-border-subtle bg-surface p-6 text-center text-ink-3">
        <ShieldCheck aria-hidden size={32} />
        <p className="font-semibold text-ink-2">No held check-ins.</p>
        <p>When the identity gate denies a new chart, the check-in waits here for a registrar.</p>
      </div>
    );
  }
  if (pair.isError) {
    return (
      <p className="rounded-lg border border-border-subtle bg-surface p-4">
        Held check-ins unavailable: {pair.error.message}. Decisions are paused; nothing was changed.
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
    <section
      data-testid="registrar-held"
      aria-labelledby="held-heading"
      className="space-y-3 rounded-lg border border-border-subtle bg-surface p-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 id="held-heading" className="text-[16px] font-semibold uppercase tracking-wider">
          Possible existing chart
        </h3>
        <span className="ml-auto text-[14px] text-ink-2">Held check-ins ({held})</span>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-[32px] font-bold tabular-nums">{decision.p.toFixed(2)}</span>
        <BandChip band={decision.band} />
      </div>
      <p>
        FrontDesk asked to create a new chart. The identity gate denied it because an existing chart scored{" "}
        {decision.p.toFixed(2)} ({decision.band}).
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
        onDecided={() => void queryClient.invalidateQueries({ queryKey: ["handoff-pair"] })}
      />
    </section>
  );
}
