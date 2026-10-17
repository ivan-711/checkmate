"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useDataSource } from "@/data/DataSourceProvider";

/** One click, no confirmation; a 5 s "Undo reset" toast covers a stray click. */
export function ResetButton() {
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
    ]);
  }

  const restore = useMutation({
    mutationFn: (previousSessionId: string) => source.restore(previousSessionId),
    onSuccess: refreshAfterSessionChange,
    onError: (error) => toast(`Undo failed: ${error.message}`),
  });

  const reset = useMutation({
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
      disabled={reset.isPending}
      className="h-11 rounded-md border border-border-strong bg-surface px-4 text-[16px] font-semibold text-ink-1 hover:bg-sunken disabled:text-ink-3"
    >
      {reset.isPending ? "Resetting..." : "Reset demo"}
    </button>
  );
}
