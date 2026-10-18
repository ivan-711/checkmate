"use client";

import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { CandidatePairDetail, IntakeSession, ReviewResponse } from "@/api/types";
import { attachablePair, type ReviewRun } from "@/components/case/reviewPlan";
import { INTAKE_KEY, handoffPairKey, useHandoffPairs } from "@/components/frontdesk/intake";
import { useAnnounce } from "@/components/ui/LiveRegion";
import {
  LATEST_MATCH_RUN_KEY,
  RESOLVE_KEY,
  SESSION_CHANGE_KEY,
  WORK_QUEUE_KEY,
} from "@/components/ui/ResetButton";
import { useDataSource } from "@/data/DataSourceProvider";
import { DataError } from "@/data/source";
import { actorName } from "@/lib/display";
import { flagState } from "@/lib/flagState";
import { useDesk } from "./DeskContext";

export const CASE_KEY = ["case", undefined] as const;

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
  const [justApproved, setJustApproved] = useState(false);
  const flagRef = useRef<HTMLDivElement>(null);
  // Held while Reset or Undo runs, until the new session has loaded (see SESSION_CHANGE_KEY).
  const sessionChanging = useIsMutating({ mutationKey: SESSION_CHANGE_KEY }) > 0;
  const caseQuery = useQuery({
    queryKey: CASE_KEY,
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
  // Before Resolve the pair has not been compared: the stage stays idle or held, never "review".
  const compared = (data?.resolved ?? false) || linked;
  const handoffs = useHandoffPairs()
    .map((q) => q.data)
    .filter((d): d is CandidatePairDetail => d !== undefined);
  const thresholds = useQuery({
    queryKey: ["thresholds"],
    queryFn: () => source.getThresholds(),
    staleTime: Infinity,
  });

  useEffect(() => {
    setFacts({
      decision: compared ? (decision?.status ?? null) : null,
      linked,
      flagRaised,
      name,
      registrar: decision?.status === "LINKED" ? actorName(decision.actor) : null,
      reason: decision?.reasonCode ?? null,
      linkedAt: decision?.status === "LINKED" ? decision.decidedAt : null,
    });
  }, [setFacts, decision, compared, linked, flagRaised, name]);

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

  // After an approve, focus goes where the eye should: to the flag's heading when the rule
  // flagged the linked record, with the notice scrolled into view; otherwise the record keeps it.
  useEffect(() => {
    if (!justApproved || !linked || !flagRaised) return;
    flagRef.current?.querySelector<HTMLElement>("#flag-heading")?.focus({ preventScroll: true });
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    flagRef.current?.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
    setJustApproved(false);
  }, [justApproved, linked, flagRaised]);

  /** The server's responses, written into the queries the Desk draws from in the same frame the
   * sheet closes (motion-polish finding 2): the record forms at once, the refetch fills in the rest. */
  function onConfirmed(run: ReviewRun) {
    const attached = data?.detail ? attachablePair(handoffs, data.detail.pair.id) : null;
    const { primary } = run;
    queryClient.setQueryData<typeof data>(CASE_KEY, (d) =>
      d?.detail
        ? {
            ...d,
            resolved: true,
            detail: { ...d.detail, pair: { ...d.detail.pair, decision: primary.decision } },
            outcome: primary.decision.status === "LINKED" ? primary : d.outcome,
          }
        : d,
    );
    if (primary.decision.status === "LINKED") setJustApproved(true);
    if (run.attach && attached) writeAttach(attached.pair.id, run.attach);
  }

  /** A hand-off pair's approval: its decision, and the kiosk's check-in, which the server derives
   * as LINKED once any of its pairs is (backend/frontdesk/registration.py). */
  function writeAttach(pairId: string, response: ReviewResponse) {
    queryClient.setQueryData<CandidatePairDetail>(handoffPairKey(pairId), (d) =>
      d ? { ...d, pair: { ...d.pair, decision: response.decision } } : d,
    );
    if (response.decision.status !== "LINKED") return;
    queryClient.setQueryData<IntakeSession>(INTAKE_KEY, (s) =>
      s ? { ...s, registration: { ...s.registration, state: "LINKED" } } : s,
    );
  }

  function onDecided(response: ReviewResponse) {
    announce(announcement(response));
  }

  return {
    caseQuery,
    sessionChanging,
    cards,
    detail: data?.detail ?? null,
    resolved: data?.resolved ?? false,
    compared,
    handoffs,
    thresholds: thresholds.data,
    onConfirmed,
    writeAttach,
    entity,
    linked,
    flag,
    flagRaised,
    timeline,
    resolve,
    onDecided,
    justApproved,
    setJustApproved,
    flagRef,
  };
}
