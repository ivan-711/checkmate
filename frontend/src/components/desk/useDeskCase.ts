"use client";

import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { ReviewResponse } from "@/api/types";
import { useAnnounce } from "@/components/ui/LiveRegion";
import { LATEST_MATCH_RUN_KEY, RESOLVE_KEY, SESSION_CHANGE_KEY, WORK_QUEUE_KEY } from "@/components/ui/ResetButton";
import { useDataSource } from "@/data/DataSourceProvider";
import { DataError } from "@/data/source";
import { actorName } from "@/lib/display";
import { flagState } from "@/lib/flagState";
import { useDesk } from "./DeskContext";

function announcement(response: ReviewResponse): string {
  if (response.decision.status === "REJECTED")
    return "Link rejected. Records kept separate. No safety check ran.";
  return response.alerts?.length
    ? "Link approved. The two records are one record now. Flagged for clinician review: a rule found a documented allergy beside an active order."
    : "Link approved. The two records are one record now. The rule did not flag this record.";
}

/** The Desk's data: the hero pair, Resolve, the timeline after a link, and the facts the header
 * and stage read through DeskContext. One hook, so the title, stepper and panes never disagree. */
export function useDeskCase() {
  const source = useDataSource();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const { setFacts, setSheet } = useDesk();
  // Set by an Approve made here; the Organism moves focus after the morph, then clears it.
  const [justApproved, setJustApproved] = useState(false);
  // Held while Reset or Undo runs, until the new session has loaded (see SESSION_CHANGE_KEY).
  const sessionChanging = useIsMutating({ mutationKey: SESSION_CHANGE_KEY }) > 0;
  const caseQuery = useQuery({
    queryKey: ["case", undefined],
    queryFn: () => source.getCase(),
    // Paused while Reset or Undo runs: reads against the half-reset session only race the reset.
    enabled: !sessionChanging,
    // "No session" is an answer, not a failure: show the reset prompt at once instead of retrying.
    retry: (failures, error) => !(error instanceof DataError && error.code === "NO_SESSION") && failures < 1,
  });
  const data = caseQuery.data;
  const entity = data?.outcome?.entity ?? null;
  const decision = data?.detail?.pair.decision ?? null;
  const linked = decision?.status === "LINKED" && entity !== null;
  const flag = data ? flagState(data) : ({ kind: "idle" } as const);
  const flagRaised = flag.kind === "raised";
  const cards = data?.sources ?? [];
  const name = cards.map((c) => c.normalized.givenName).find((n) => n) ?? null;

  useEffect(() => {
    setFacts({
      decision: decision?.status ?? null,
      linked,
      flagRaised,
      name,
      registrar: decision?.status === "LINKED" ? actorName(decision.actor) : null,
      reason: decision?.reasonCode ?? null,
      linkedAt: decision?.status === "LINKED" ? decision.decidedAt : null,
    });
  }, [setFacts, decision, linked, flagRaised, name]);

  // A decision closes any sheet; a reset drops the facts with the query.
  useEffect(() => {
    if (!decision || decision.status !== "PROPOSED") setSheet(null);
  }, [decision, setSheet]);

  const timeline = useQuery({
    queryKey: ["timeline", entity?.id],
    queryFn: () => source.getTimeline(entity!.id),
    enabled: linked && !sessionChanging,
  });

  const resolve = useMutation({
    mutationKey: RESOLVE_KEY,
    mutationFn: () => source.resolve(),
    onSuccess: async (run) => {
      // Kept for the work queue's funnel, so the queue never has to start a run of its own.
      if (run) queryClient.setQueryData(LATEST_MATCH_RUN_KEY, run);
      await queryClient.invalidateQueries({ queryKey: WORK_QUEUE_KEY });
      await queryClient.invalidateQueries({ queryKey: ["case"] });
      await queryClient.invalidateQueries({ queryKey: ["events"] });
      announce("Identity resolved. The candidate pair is ready for review.");
    },
  });

  function onDecided(response: ReviewResponse) {
    setJustApproved(response.decision.status === "LINKED");
    announce(announcement(response));
  }

  return {
    caseQuery,
    sessionChanging,
    cards,
    detail: data?.detail ?? null,
    resolved: data?.resolved ?? false,
    entity,
    linked,
    flag,
    flagRaised,
    timeline,
    resolve,
    onDecided,
    justApproved,
    setJustApproved,
  };
}
