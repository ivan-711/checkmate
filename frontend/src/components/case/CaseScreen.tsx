"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { ReviewResponse } from "@/api/types";
import { useAnnounce } from "@/components/ui/LiveRegion";
import { useDataSource } from "@/data/DataSourceProvider";
import { differingFields } from "@/lib/display";
import { flagState } from "@/lib/flagState";
import { EventFeed } from "./EventFeed";
import { EvidenceRail } from "./EvidenceRail";
import { FlagCard } from "./FlagCard";
import { GoldenRecord } from "./GoldenRecord";
import { HumanReviewTile } from "./HumanReviewTile";
import { ReviewPanel } from "./ReviewPanel";
import { SourceCardView } from "./SourceCardView";
import { Timeline } from "./Timeline";

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
  const queryClient = useQueryClient();
  const [justApproved, setJustApproved] = useState(false);
  const caseQuery = useQuery({ queryKey: ["case"], queryFn: () => source.getCase() });
  const entity = caseQuery.data?.outcome?.entity ?? null;
  const linked = caseQuery.data?.detail.pair.decision.status === "LINKED" && entity !== null;
  const timeline = useQuery({
    queryKey: ["timeline", entity?.id],
    queryFn: () => source.getTimeline(entity!.id),
    enabled: linked,
  });
  const resolve = useMutation({
    mutationFn: () => source.resolve(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["case"] });
      await queryClient.invalidateQueries({ queryKey: ["events"] });
      announce("Identity resolved. The candidate pair is ready for review.");
    },
  });

  const resolveButton = (
    <button
      type="button"
      data-testid="resolve-button"
      onClick={() => resolve.mutate()}
      disabled={resolve.isPending}
      className="h-11 rounded-md bg-accent px-4 font-semibold text-on-accent hover:bg-accent-hover disabled:bg-sunken disabled:text-ink-3"
    >
      {resolve.isPending ? "Resolving..." : "Resolve identity"}
    </button>
  );

  if (caseQuery.isPending) return <p aria-busy="true">Loading case...</p>;
  if (caseQuery.isError) {
    return (
      <div className="space-y-3">
        <p className="text-error-ink">Case unavailable: {caseQuery.error.message}</p>
        {resolveButton}
        {resolve.isError && <p className="text-error-ink">Resolve failed: {resolve.error.message}</p>}
      </div>
    );
  }

  const { detail, resolved } = caseQuery.data;
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
              <GoldenRecord
                entity={entity}
                cards={cards}
                focusOnMount={justApproved}
                onFocused={() => setJustApproved(false)}
              />
              <Timeline events={timeline.data} cards={cards} />
            </>
          ) : (
            <section aria-labelledby="sources-heading">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <h2 id="sources-heading" className="text-[18px] font-semibold uppercase tracking-wider">
                  Sources{" "}
                  <span className="font-normal normal-case tracking-normal text-ink-2">2 systems</span>
                </h2>
                {resolveButton}
              </div>
              {resolve.isError && (
                <p className="mb-2 text-error-ink">Resolve failed: {resolve.error.message}</p>
              )}
              <div className="grid grid-cols-2 gap-4">
                {cards.map((card) => (
                  <SourceCardView key={card.record.id} card={card} differs={differs} />
                ))}
              </div>
            </section>
          )}
          <FlagCard state={flagState(caseQuery.data)} />
          <EventFeed />
        </div>
        <aside className="space-y-4">
          {resolved || linked ? (
            <div
              data-testid="candidate-pair"
              className="space-y-4 rounded-lg border border-border-subtle bg-surface p-4"
            >
              <EvidenceRail detail={detail} />
              <ReviewPanel detail={detail} onDecided={onDecided} />
            </div>
          ) : (
            <div className="rounded-lg border border-border-subtle bg-surface p-4 text-ink-2">
              <h2 className="text-[18px] font-semibold uppercase tracking-wider text-ink-1">
                Candidate pair
              </h2>
              <p className="mt-2">Press Resolve identity to block, score and band the loaded records.</p>
            </div>
          )}
          <HumanReviewTile />
        </aside>
      </div>
    </div>
  );
}
