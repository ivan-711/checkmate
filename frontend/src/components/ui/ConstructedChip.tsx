"use client";

import { useId, useRef, useState } from "react";

// The tooltip's width (w-80) and the gap it keeps from the edge of the box it must stay inside.
const TIP_WIDTH_PX = 320;
const EDGE_GAP_PX = 16;

/** The box the tooltip must stay inside: the nearest ancestor that scrolls or clips sideways (a
 * pane can scroll on its own), cut to the window; the window when there is none. */
function boundsFor(chip: HTMLElement): { left: number; right: number } {
  const root = document.documentElement;
  for (let node = chip.parentElement; node && node !== root; node = node.parentElement) {
    if (getComputedStyle(node).overflowX === "visible") continue;
    const left = node.getBoundingClientRect().left + node.clientLeft;
    return { left: Math.max(left, 0), right: Math.min(left + node.clientWidth, root.clientWidth) };
  }
  return { left: 0, right: root.clientWidth };
}

/** Opens the explanation where it fits, before it paints: it starts under the chip and moves left
 * (narrowing on a small screen) so it never runs past either edge of its bounds. */
function placeTip(chip: HTMLElement, tip: HTMLElement | null) {
  if (!tip) return;
  const { left: min, right: max } = boundsFor(chip);
  const width = Math.min(TIP_WIDTH_PX, max - min - 2 * EDGE_GAP_PX);
  const origin = chip.getBoundingClientRect().left + chip.clientLeft;
  const left = Math.max(Math.min(origin, max - EDGE_GAP_PX - width), min + EDGE_GAP_PX);
  tip.style.width = `${width}px`;
  tip.style.left = `${left - origin}px`;
}

const EXPLANATION =
  "This ER record was constructed as registered without the allergy history; the order is part of the demo scenario. All records are synthetic.";

/** Outlined, text only; the explanation shows on hover and on keyboard focus, and Escape hides it
 * (WCAG 1.4.13). A button, so assistive tech knows the chip takes focus for a reason. */
/** The label and explanation default to the Case wording; the kiosk passes its own (UX 10.9). */
export function ConstructedChip({
  label = "constructed scenario",
  explanation = EXPLANATION,
}: { label?: string; explanation?: string } = {}) {
  const tipId = useId();
  const tipRef = useRef<HTMLSpanElement>(null);
  const [dismissed, setDismissed] = useState(false);
  return (
    <button
      type="button"
      data-testid="constructed-scenario-chip"
      aria-describedby={tipId}
      onKeyDown={(e) => {
        if (e.key === "Escape") setDismissed(true);
      }}
      onPointerEnter={(e) => placeTip(e.currentTarget, tipRef.current)}
      onFocus={(e) => placeTip(e.currentTarget, tipRef.current)}
      onBlur={() => setDismissed(false)}
      onMouseLeave={() => setDismissed(false)}
      className="group relative inline-flex items-center rounded border border-ink-2 px-2 text-[14px] font-medium text-ink-2"
    >
      {label}
      <span
        role="tooltip"
        id={tipId}
        ref={tipRef}
        // Out of layout until it opens (display, not visibility), so a closed tooltip never adds width.
        className={`absolute left-0 top-full z-20 mt-1 w-80 rounded-lg border border-border-strong bg-surface p-3 text-left text-[14px] font-normal text-ink-1 shadow-lg ${
          dismissed ? "hidden" : "hidden group-hover:block group-focus:block"
        }`}
      >
        {explanation}
      </span>
    </button>
  );
}
