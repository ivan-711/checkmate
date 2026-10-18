"use client";

import { hashKey, notifyManager, useQueries, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useCallback, useSyncExternalStore } from "react";
import type { IntakeSession } from "@/api/types";
import { useDataSource } from "@/data/DataSourceProvider";

/** One check-in per kiosk; the kiosk starts it, the registrar pane reads the same entry. */
export const INTAKE_KEY = ["intake-session"] as const;

/** The pairs a held check-in waits on; both panes read them, so one decision shows in both. */
export const HANDOFF_KEY = ["handoff-pair"] as const;
export const handoffPairKey = (pairId: string) => [...HANDOFF_KEY, pairId] as const;

const INTAKE_HASH = hashKey(INTAKE_KEY);

/** Calls onChange after the kiosk's check-in changes, never inside a render. The cache notifies
 * its listeners synchronously, also when useQuery or useQueries builds a query while a component
 * renders; React would then update the registrar pane inside that render. The notify manager
 * runs onChange once that work is done, as React Query's own hooks do. */
export function subscribeToIntake(queryClient: QueryClient, onChange: () => void): () => void {
  return queryClient.getQueryCache().subscribe((event) => {
    if (event.query.queryHash === INTAKE_HASH) notifyManager.schedule(onChange);
  });
}

/** Re-reads the held pairs whenever a mutation succeeds. The registrar decides on the Desk with
 * the case's own review (not a kiosk mutation), so nothing else tells the kiosk that its pair is
 * now LINKED or REJECTED. Any success is enough: re-reading two pairs is cheap, and keying on one
 * screen's mutation would miss the next screen's. */
export function refreshHandoffOnMutation(queryClient: QueryClient): () => void {
  return queryClient.getMutationCache().subscribe((event) => {
    if (event.type === "updated" && event.action.type === "success") {
      void queryClient.invalidateQueries({ queryKey: HANDOFF_KEY });
    }
  });
}

/** The linked chart's active flags as an approval's review response returned them (every current
 * alert on the entity, kept ones included), keyed by that decision: a Reset makes a new one, so an
 * old flag never shows again. Kept in the cache, not under HANDOFF_KEY, which is refetched, so the
 * pane still shows them after a visit to Case and back. */
export const approvalAlertsKey = (decisionId: string) => ["approval-alerts", decisionId] as const;

/** Reads the kiosk's check-in from the cache without observing the query. A second observer
 * would replace the kiosk's queryFn, so Start over and Reset could not start a new check-in. */
export function useIntakeSession(): IntakeSession | undefined {
  const queryClient = useQueryClient();
  const subscribe = useCallback(
    (onChange: () => void) => subscribeToIntake(queryClient, onChange),
    [queryClient],
  );
  const read = useCallback(() => queryClient.getQueryData<IntakeSession>(INTAKE_KEY), [queryClient]);
  // The server snapshot reads the cache too: it is empty during real SSR and hydration (the
  // check-in starts after mount), and a static render of a seeded cache then sees the check-in.
  return useSyncExternalStore(subscribe, read, read);
}

/** Every pair the turn handed off (the hero has two: the ER and the Clinic record). */
export function useHandoffPairs() {
  const source = useDataSource();
  const pairIds = useIntakeSession()?.registration.handoffPairIds ?? [];
  return useQueries({
    queries: pairIds.map((pairId) => ({
      queryKey: handoffPairKey(pairId),
      queryFn: () => source.getCandidatePair(pairId),
    })),
  });
}
