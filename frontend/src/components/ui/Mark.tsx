/** The CheckMate mark (CONCEPT.md §5, touch 1): two half-discs with a 2 px gap. `joined` closes
 * them, which the top bar does when a link is approved. Drawn in currentColor so the same mark
 * sits in mulberry on porcelain and in paper on the record. */
export function Mark({
  joined = false,
  size = 26,
  className = "",
  apart = false,
}: {
  joined?: boolean;
  size?: number;
  className?: string;
  /** The halves pulled apart (the 404 page). */
  apart?: boolean;
}) {
  const shift = joined ? 1 : apart ? -5 : 0;
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      aria-hidden="true"
      className={`mark ${joined ? "mark-joined" : ""} ${className}`}
      data-joined={joined || undefined}
    >
      <path d="M11 3A9 9 0 0 0 11 21Z" fill="currentColor" style={{ transform: `translateX(${shift}px)` }} />
      <path d="M13 3A9 9 0 0 1 13 21Z" fill="currentColor" style={{ transform: `translateX(${-shift}px)` }} />
    </svg>
  );
}
