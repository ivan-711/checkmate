"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useDataSource } from "@/data/DataSourceProvider";

/** One click, no confirmation; a 5 s "Undo reset" toast covers a stray click. */
export function ResetButton() {
  const source = useDataSource();
  const queryClient = useQueryClient();

  const restore = useMutation({
    mutationFn: (previousSessionId: string) => source.restore(previousSessionId),
    onSuccess: () => queryClient.invalidateQueries(),
    onError: (error) => toast(`Undo failed: ${error.message}`),
  });

  const reset = useMutation({
    mutationFn: () => source.reset(),
    onSuccess: async (session) => {
      await queryClient.invalidateQueries();
      const previous = session.previousSessionId;
      toast("Demo reset.", {
        action: previous ? { label: "Undo reset", onClick: () => restore.mutate(previous) } : undefined,
      });
    },
    onError: (error) => toast(`Reset failed: ${error.message}`),
  });

  return (
    <button
      type="button"
      onClick={() => reset.mutate()}
      disabled={reset.isPending}
      className="h-11 rounded-md border border-border-strong bg-surface px-4 text-[16px] font-semibold text-ink-1 hover:bg-sunken disabled:text-ink-3"
    >
      {reset.isPending ? "Resetting..." : "Reset demo"}
    </button>
  );
}
