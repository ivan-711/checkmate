"use client";

import { useQueries, useQueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";
import type { IntakeSession } from "@/api/types";
import { useDataSource } from "@/data/DataSourceProvider";

/** One check-in per kiosk; the kiosk starts it, the registrar pane reads the same entry. */
export const INTAKE_KEY = ["intake-session"] as const;

/** The pairs a held check-in waits on; both panes read them, so one decision shows in both. */
export const HANDOFF_KEY = ["handoff-pair"] as const;
export const handoffPairKey = (pairId: string) => [...HANDOFF_KEY, pairId] as const;

/** Reads the kiosk's check-in from the cache without observing the query. A second observer
 * would replace the kiosk's queryFn, so Start over and Reset could not start a new check-in. */
export function useIntakeSession(): IntakeSession | undefined {
  const queryClient = useQueryClient();
  return useSyncExternalStore(
    (onChange) => queryClient.getQueryCache().subscribe(onChange),
    () => queryClient.getQueryData<IntakeSession>(INTAKE_KEY),
    () => undefined,
  );
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
