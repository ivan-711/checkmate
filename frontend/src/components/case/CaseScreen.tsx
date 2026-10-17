"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { ReviewResponse } from "@/api/types";
import { useAnnounce } from "@/components/ui/LiveRegion";
import { useDataSource } from "@/data/DataSourceProvider";
import type { CaseData } from "@/data/source";
import { differingFields } from "@/lib/display";
import { EvidenceRail } from "./EvidenceRail";
import { FlagCard, type FlagState } from "./FlagCard";
import { GoldenRecord } from "./GoldenRecord";
import { ReviewPanel } from "./ReviewPanel";
import { SourceCardView } from "./SourceCardView";
import { Timeline } from "./Timeline";

function flagState({ detail, outcome }: CaseData): FlagState {
  const { status } = detail.pair.decision;
  if (status === "REJECTED") return { kind: "silent" };
  if (status !== "LINKED") return { kind: "idle" };
  if (!outcome) return { kind: "unavailable" };
  const alert = outcome.alerts?.[0];
  return alert ? { kind: "raised", alert } : { kind: "none" };
}

function announcement(response: ReviewResponse): string {
  if (response.decision.status === "REJECTED")
    return "Link rejected. Records kept separate. No safety check ran.";
  return response.alerts?.length
    ? "Records linked into one golden record. Flagged for clinician review."
    : "Records linked into one golden record.";
}

export function CaseScreen() {
  const source = useDataSource();
  const announce = useAnnounce();
  const [justApproved, setJustApproved] = useState(false);
  const caseQuery = useQuery({ queryKey: ["case"], queryFn: () => source.getCase() });
  const entity = caseQuery.data?.outcome?.entity ?? null;
  const linked = caseQuery.data?.detail.pair.decision.status === "LINKED" && entity !== null;
  const timeline = useQuery({
    queryKey: ["timeline", entity?.id],
    queryFn: () => source.getTimeline(entity!.id),
    enabled: linked,
  });

  if (caseQuery.isPending) return <p aria-busy="true">Loading case...</p>;
  if (caseQuery.isError) return <p className="text-error-ink">Case unavailable: {caseQuery.error.message}</p>;

  const { detail } = caseQuery.data;
  const cards = [detail.recordA, detail.recordB];
  const differs = differingFields(detail.recordA.normalized, detail.recordB.normalized);

  function onDecided(response: ReviewResponse) {
    setJustApproved(response.decision.status === "LINKED");
    announce(announcement(response));
  }

  return (
    <div className="space-y-4">
      <h1 className="sr-only">Case</h1>
      <div className="grid grid-cols-[1fr_28rem] gap-4 max-[1100px]:grid-cols-1">
        <div className="space-y-4">
          {linked && entity ? (
            <>
              <GoldenRecord entity={entity} cards={cards} focusOnMount={justApproved} />
              <Timeline events={timeline.data} cards={cards} />
            </>
          ) : (
            <section aria-labelledby="sources-heading">
              <h2 id="sources-heading" className="mb-2 text-[18px] font-semibold uppercase tracking-wider">
                Sources <span className="font-normal normal-case tracking-normal text-ink-2">2 systems</span>
              </h2>
              <div className="grid grid-cols-2 gap-4">
                {cards.map((card) => (
                  <SourceCardView key={card.record.id} card={card} differs={differs} />
                ))}
              </div>
            </section>
          )}
          <FlagCard state={flagState(caseQuery.data)} />
        </div>
        <aside className="space-y-4 rounded-lg border border-border-subtle bg-surface p-4">
          <EvidenceRail detail={detail} />
          <ReviewPanel detail={detail} onDecided={onDecided} />
        </aside>
      </div>
    </div>
  );
}
