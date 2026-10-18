"use client";

import { useIsMutating } from "@tanstack/react-query";
import { RESOLVE_KEY, SESSION_CHANGE_KEY, useDemoReset } from "./demoReset";

export { LATEST_MATCH_RUN_KEY, RESOLVE_KEY, SESSION_CHANGE_KEY, WORK_QUEUE_KEY } from "./demoReset";

/** One click, no confirmation; the shared reset's "Undo reset" toast covers a stray click. */
export function ResetButton() {
  const resolving = useIsMutating({ mutationKey: RESOLVE_KEY }) > 0;
  // Counts Undo as well as Reset, so a reset never races a restore still in flight.
  const sessionChanging = useIsMutating({ mutationKey: SESSION_CHANGE_KEY }) > 0;
  const reset = useDemoReset();

  return (
    <button
      type="button"
      data-testid="reset-button"
      onClick={() => reset.mutate()}
      disabled={sessionChanging || resolving}
      className="h-11 rounded-md border border-border-strong bg-surface px-4 text-[16px] font-semibold text-ink-1 hover:bg-sunken disabled:text-ink-3"
    >
      {reset.isPending ? "Resetting..." : "Reset demo"}
    </button>
  );
}
