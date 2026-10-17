"use client";

import { useIsMutating, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useDataSource } from "@/data/DataSourceProvider";

/** Reset and Undo share this key so the case screen can hold Resolve until the new session has
 * loaded: a match run that overlaps a reset gets a 503 and leaves no candidate pair. */
export const SESSION_CHANGE_KEY = ["session-change"] as const;
/** Resolve's key, so Reset waits for a match run in flight for the same reason. */
export const RESOLVE_KEY = ["resolve"] as const;

/** One click, no confirmation; a 5 s "Undo reset" toast covers a stray click. */
export function ResetButton() {
  const source = useDataSource();
  const queryClient = useQueryClient();
  const resolving = useIsMutating({ mutationKey: RESOLVE_KEY }) > 0;

  // Reset, not invalidate, the case: its panels remount, so no half-typed note or stale
  // error survives. Tiles keep showing their values while they refetch.
  async function refreshAfterSessionChange() {
    await Promise.all([
      queryClient.resetQueries({ queryKey: ["case"] }),
      queryClient.invalidateQueries({ queryKey: ["session"] }),
      queryClient.invalidateQueries({ queryKey: ["events"] }),
      queryClient.resetQueries({ queryKey: ["timeline"] }),
      queryClient.invalidateQueries({ queryKey: ["tiles"] }),
    ]);
  }

  const restore = useMutation({
    mutationKey: SESSION_CHANGE_KEY,
    mutationFn: (previousSessionId: string) => source.restore(previousSessionId),
    onSuccess: refreshAfterSessionChange,
    onError: (error) => toast(`Undo failed: ${error.message}`),
  });

  const reset = useMutation({
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

  return (
    <button
      type="button"
      data-testid="reset-button"
      onClick={() => reset.mutate()}
      disabled={reset.isPending || resolving}
      className="h-11 rounded-md border border-border-strong bg-surface px-4 text-[16px] font-semibold text-ink-1 hover:bg-sunken disabled:text-ink-3"
    >
      {reset.isPending ? "Resetting..." : "Reset demo"}
    </button>
  );
}
