export type MarkState = "open" | "closed";

/**
 * Each half moves on the fuse timing from CONCEPT.md §4 (720 ms, ease-fuse). The var() fallbacks
 * hold until the redesign tokens land in globals.css; reduced motion drops the transition and the
 * halves simply sit in their new place.
 */
const HALF_TRANSITION =
  "transition-transform duration-[var(--t-fuse,720ms)] ease-[var(--ease-fuse,cubic-bezier(0.7,0,0.2,1))] motion-reduce:transition-none";

const DEFAULT_SIZE = 24;

type MarkProps = {
  /** `open`: two half-discs with a 2 px gap. `closed`: the halves meet as one disc, once a link is approved. */
  state?: MarkState;
  /** Rendered width and height in px (the top bar uses 26, the kiosk done state 84). */
  size?: number;
  /** Accessible name. Without one the mark is decorative and hidden from assistive tech. */
  title?: string;
  className?: string;
};

/**
 * The CheckMate mark (CONCEPT.md §5, touch 1): two half-discs that close when a link is approved.
 * Drawn in `currentColor`, so the parent's text colour (the mulberry token, or white on the record)
 * is the mark's colour.
 */
export function Mark({ state = "open", size = DEFAULT_SIZE, title, className }: MarkProps) {
  const closed = state === "closed";
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="currentColor"
      data-state={state}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      className={className}
    >
      {title ? <title>{title}</title> : null}
      <path
        className={[HALF_TRANSITION, closed ? "translate-x-px" : ""].filter(Boolean).join(" ")}
        d="M11 3A9 9 0 0 0 11 21Z"
      />
      <path
        className={[HALF_TRANSITION, closed ? "-translate-x-px" : ""].filter(Boolean).join(" ")}
        d="M13 3A9 9 0 0 1 13 21Z"
      />
    </svg>
  );
}
