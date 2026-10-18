/** The CheckMate mark's half-disc for one source (CONCEPT.md §5, touch 1): the first source fills the
 * left half, the second the right, so two records read as the two halves of one record. */
export function SourceGlyph({
  side,
  size = 16,
  className = "",
  title,
}: {
  side: "left" | "right";
  size?: number;
  className?: string;
  title?: string;
}) {
  // A full circle outline with one half filled; the gap at the seam is the mark's 2 px break.
  const half = side === "left" ? "M8 1.5A6.5 6.5 0 0 0 8 14.5Z" : "M8 1.5A6.5 6.5 0 0 1 8 14.5Z";
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
      className={className}
    >
      {title && <title>{title}</title>}
      <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d={half} fill="currentColor" />
    </svg>
  );
}

/** Which half a source system gets: the session's first system is the left half. */
export function glyphSide(sourceSystem: string, systems: readonly string[]): "left" | "right" {
  const i = systems.indexOf(sourceSystem);
  return i <= 0 ? "left" : "right";
}
