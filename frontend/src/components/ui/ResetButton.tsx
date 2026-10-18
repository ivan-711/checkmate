"use client";

import { useIsMutating } from "@tanstack/react-query";
import { RESOLVE_KEY, SESSION_CHANGE_KEY, useDemoReset } from "./demoReset";

export { LATEST_MATCH_RUN_KEY, RESOLVE_KEY, SESSION_CHANGE_KEY, WORK_QUEUE_KEY } from "./demoReset";

/** The one Reset: the button, the ⇧R key and the command bar all call this. The mutation itself
 * is `useDemoReset`, which the kiosk's Start over shares (BUILD-SPEC decision 5). */
export function useResetDemo() {
  const resolving = useIsMutating({ mutationKey: RESOLVE_KEY }) > 0;
  // Counts Undo as well as Reset, so a reset never races a restore still in flight.
  const sessionChanging = useIsMutating({ mutationKey: SESSION_CHANGE_KEY }) > 0;
  const reset = useDemoReset();

  const disabled = sessionChanging || resolving;
  return {
    reset: () => {
      if (!disabled) reset.mutate();
    },
    isPending: reset.isPending,
    disabled,
  };
}

/** One click, no confirmation; a 5 s "Undo reset" toast covers a stray click. */
export function ResetButton() {
  const { reset, isPending, disabled } = useResetDemo();
  return (
    <button
      type="button"
      data-testid="reset-button"
      onClick={reset}
      disabled={disabled}
      className="inline-flex h-9 items-center rounded-[10px] border border-hair-strong px-3.5 text-[14px] font-semibold text-ink hover:bg-ink/5 disabled:text-ink-3"
    >
      {isPending ? "Resetting…" : "Reset demo"}
      <kbd aria-hidden="true">⇧R</kbd>
    </button>
  );
}
