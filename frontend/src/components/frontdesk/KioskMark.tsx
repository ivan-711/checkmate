/** The CheckMate mark: two half-discs with a 2 px gap. The kiosk CSS moves the halves by state
 * (they breathe while the agent works and close once a link is approved). */
export function KioskMark({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={`k-mark ${className}`}>
      <path className="k-mark-l" d="M11 3A9 9 0 0 0 11 21Z" />
      <path className="k-mark-r" d="M13 3A9 9 0 0 1 13 21Z" />
    </svg>
  );
}

/** A checklist tick: a ring with a check that draws in; `pending` is a dashed ring; `hold`
 * shows a pause glyph (the gate held the turn). */
export function Tick({ kind = "done" }: { kind?: "done" | "pending" | "hold" }) {
  return (
    <svg viewBox="0 0 22 22" aria-hidden className={`k-tick k-tick-${kind}`}>
      <circle cx="11" cy="11" r="9.5" />
      {kind === "hold" ? (
        <path d="M9 7v8M13 7v8" />
      ) : kind === "done" ? (
        <path d="M6.5 11.2l3 3 6-6.2" />
      ) : null}
    </svg>
  );
}
