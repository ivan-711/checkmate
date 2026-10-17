"use client";

import { useId, useState } from "react";

const EXPLANATION =
  "This ER record was constructed as registered without the allergy history; the order is part of the demo scenario. All records are synthetic.";

/** Outlined, text only; the explanation shows on hover and on keyboard focus, and Escape hides it
 * (WCAG 1.4.13). A button, so assistive tech knows the chip takes focus for a reason. */
export function ConstructedChip() {
  const tipId = useId();
  const [dismissed, setDismissed] = useState(false);
  return (
    <button
      type="button"
      data-testid="constructed-scenario-chip"
      aria-describedby={tipId}
      onKeyDown={(e) => {
        if (e.key === "Escape") setDismissed(true);
      }}
      onBlur={() => setDismissed(false)}
      onMouseLeave={() => setDismissed(false)}
      className="group relative inline-flex items-center rounded border border-ink-2 px-2 text-[14px] font-medium text-ink-2"
    >
      constructed scenario
      <span
        role="tooltip"
        id={tipId}
        className={`absolute left-0 top-full z-20 mt-1 w-80 rounded-lg border border-border-strong bg-surface p-3 text-left text-[14px] font-normal text-ink-1 shadow-lg ${
          dismissed ? "invisible" : "invisible group-hover:visible group-focus:visible"
        }`}
      >
        {EXPLANATION}
      </span>
    </button>
  );
}
