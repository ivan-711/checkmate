"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { HANDOFF_KEY, INTAKE_KEY } from "@/components/frontdesk/intake";
import { useDataSource } from "@/data/DataSourceProvider";

/** Reset and Undo share this key so the case screen can hold Resolve until the new session has
 * loaded: a match run that overlaps a reset gets a 503 and leaves no candidate pair. */
export const SESSION_CHANGE_KEY = ["session-change"] as const;
/** Resolve's key, so Reset waits for a match run in flight for the same reason. */
export const RESOLVE_KEY = ["resolve"] as const;
/** The newest match-run receipt Resolve returned in this tab. The work queue draws its funnel
 * from it and never starts a run itself; a session change drops it, the pairs it counted gone. */
export const LATEST_MATCH_RUN_KEY = ["latest-match-run"] as const;
/** Every work-queue read (pages and row details); GETs only. */
export const WORK_QUEUE_KEY = ["work-queue"] as const;

/** The demo reset, one mutation shared by the top bar's Reset demo and the kiosk's Start over
 * (BUILD-SPEC decision 5: on the API a second check-in without a reset would find the first
 * one's own intake record, so Start over must reset). A 5 s "Undo reset" toast covers a stray click. */
export function useDemoReset() {
  const source = useDataSource();
  const queryClient = useQueryClient();

  // Reset, not invalidate, the case: its panels remount, so no half-typed note or stale
  // error survives. Tiles keep showing their values while they refetch.
  async function refreshAfterSessionChange() {
    await Promise.all([
      queryClient.resetQueries({ queryKey: ["case"] }),
      queryClient.invalidateQueries({ queryKey: ["session"] }),
      queryClient.invalidateQueries({ queryKey: ["events"] }),
      queryClient.resetQueries({ queryKey: ["timeline"] }),
      queryClient.invalidateQueries({ queryKey: ["tiles"] }),
      // The reset removed the kiosk's check-in and its held pairs: the kiosk starts a new
      // check-in, and the registrar pane drops the old one.
      queryClient.resetQueries({ queryKey: INTAKE_KEY }),
      queryClient.resetQueries({ queryKey: HANDOFF_KEY }),
      queryClient.resetQueries({ queryKey: WORK_QUEUE_KEY }),
    ]);
    queryClient.removeQueries({ queryKey: LATEST_MATCH_RUN_KEY });
  }

  const restore = useMutation({
    mutationKey: SESSION_CHANGE_KEY,
    mutationFn: (previousSessionId: string) => source.restore(previousSessionId),
    onSuccess: refreshAfterSessionChange,
    onError: (error) => toast(`Undo failed: ${error.message}`),
  });

  return useMutation({
    mutationKey: SESSION_CHANGE_KEY,
    mutationFn: () => source.reset(),
    onSuccess: async (session) => {
      await refreshAfterSessionChange();
      const previous = session.previousSessionId;
      toast("Demo reset.", {
        action:
          previous && source.canRestore
            ? { label: "Undo reset", onClick: () => restore.mutate(previous) }
            : undefined,
      });
    },
    onError: (error) => toast(`Reset failed: ${error.message}`),
  });
}
