"use client";

import { skipToken, useQuery } from "@tanstack/react-query";
import type { IntakeSession } from "@/api/types";
import { useDataSource } from "@/data/DataSourceProvider";

/** One check-in per kiosk; the kiosk starts it, the registrar pane reads the same entry. */
export const INTAKE_KEY = ["intake-session"] as const;

/** The pair a held check-in waits on; both panes read it, so one decision shows in both. */
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
