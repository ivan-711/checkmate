import { useId } from "react";

const EXPLANATION =
  "This ER record was constructed as registered without the allergy history; the order is part of the demo scenario. All records are synthetic.";

/** Outlined, text only; the explanation shows on hover and on keyboard focus. */
export function ConstructedChip() {
  const tipId = useId();
  return (
    <span
      tabIndex={0}
      aria-describedby={tipId}
      className="group relative inline-flex items-center rounded border border-ink-2 px-2 text-[14px] font-medium text-ink-2"
    >
      constructed scenario
      <span
        role="tooltip"
        id={tipId}
        className="invisible absolute left-0 top-full z-20 mt-1 w-80 rounded-lg border border-border-strong bg-surface p-3 text-[14px] font-normal text-ink-1 shadow-lg group-hover:visible group-focus:visible"
      >
        {EXPLANATION}
      </span>
    </span>
  );
}
