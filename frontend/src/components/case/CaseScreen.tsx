"use client";

import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { ReviewResponse } from "@/api/types";
import { useAnnounce } from "@/components/ui/LiveRegion";
import { RESOLVE_KEY, SESSION_CHANGE_KEY } from "@/components/ui/ResetButton";
import { useDataSource } from "@/data/DataSourceProvider";
import { DataError } from "@/data/source";
import { differingFields, type CardField } from "@/lib/display";
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
    ? "Link approved. Records linked into one golden record with a crosswalk on every value. Flagged for clinician review: a rule found a documented allergy beside an active order."
    : "Link approved. Records linked into one golden record with a crosswalk on every value. The rule did not flag this record.";
}

export function CaseScreen({ pairId }: { pairId?: string }) {
  const source = useDataSource();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const [justApproved, setJustApproved] = useState(false);
  // Held while Reset or Undo runs, until the new session has loaded (see SESSION_CHANGE_KEY).
  const sessionChanging = useIsMutating({ mutationKey: SESSION_CHANGE_KEY }) > 0;
  const caseQuery = useQuery({
    queryKey: ["case", pairId],
    queryFn: () => source.getCase(pairId),
    // Paused while Reset or Undo runs: reads against the half-reset session only race the reset.
    enabled: !sessionChanging,
    // "No session" is an answer, not a failure: show the reset prompt at once instead of retrying.
    retry: (failures, error) => !(error instanceof DataError && error.code === "NO_SESSION") && failures < 1,
  });
  const entity = caseQuery.data?.outcome?.entity ?? null;
  const linked = caseQuery.data?.detail?.pair.decision.status === "LINKED" && entity !== null;
  const timeline = useQuery({
    queryKey: ["timeline", entity?.id],
    queryFn: () => source.getTimeline(entity!.id),
    enabled: linked && !sessionChanging,
  });
  const resolve = useMutation({
    mutationKey: RESOLVE_KEY,
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
      disabled={resolve.isPending || sessionChanging}
      className="h-11 rounded-md bg-accent px-4 font-semibold text-on-accent hover:bg-accent-hover disabled:bg-sunken disabled:text-ink-3"
    >
      {resolve.isPending ? "Resolving..." : "Resolve identity"}
    </button>
  );

  if (caseQuery.isPending) return <p aria-busy="true">Loading case...</p>;
  if (caseQuery.isError && caseQuery.error instanceof DataError && caseQuery.error.code === "NO_SESSION") {
    // No session to bind the hero to: Reset demo (in the header) is the one action that helps.
    return <p data-testid="reset-prompt">{caseQuery.error.message}</p>;
  }
  if (caseQuery.isError) {
    return (
      <div className="space-y-3">
        <p className="text-error-ink">Case unavailable: {caseQuery.error.message}</p>
        {resolveButton}
        {resolve.isError && <p className="text-error-ink">Resolve failed: {resolve.error.message}</p>}
      </div>
    );
  }

  const { sources, detail, resolved } = caseQuery.data;
  // The hero's cards are the session's showcase sources, never the pair's records.
  const cards = sources;
  const differs =
    cards.length === 2 ? differingFields(cards[0].normalized, cards[1].normalized) : new Set<CardField>();

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
              {/* The flag sits right under the combined record so it is on screen after Approve. */}
              <FlagCard state={flagState(caseQuery.data)} />
              <Timeline events={timeline.data} cards={cards} />
            </>
          ) : (
            <section aria-labelledby="sources-heading">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <h2 id="sources-heading" className="text-[18px] font-semibold uppercase tracking-wider">
                  Sources{" "}
                  <span className="font-normal normal-case tracking-normal text-ink-2">
                    {cards.length} systems
                  </span>
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
              <div className="mt-4">
                <FlagCard state={flagState(caseQuery.data)} />
              </div>
            </section>
          )}
          <EventFeed />
        </div>
        <aside className="space-y-4">
          {detail && (resolved || linked) ? (
            <div
              data-testid="candidate-pair"
              aria-busy={resolve.isPending || sessionChanging}
              className="space-y-3 rounded-lg border border-border-subtle bg-surface p-3"
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
