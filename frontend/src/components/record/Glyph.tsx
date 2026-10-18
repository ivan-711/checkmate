// The CheckMate mark (touch 1): two half-discs. A source's glyph fills its own half; the record's
// mark fills both and closes when a link is approved. Decorative everywhere: the words sit beside it.

const LEFT = "M11 3A9 9 0 0 0 11 21Z";
const RIGHT = "M13 3A9 9 0 0 1 13 21Z";

const FILLED_HALF: Record<string, "left" | "right"> = { ER_FHIR: "left", CLINIC_CSV: "right" };

/** The half-disc of one source; a source the mark does not know shows both halves outlined. */
export function SourceGlyph({ sourceSystem, className }: { sourceSystem: string; className?: string }) {
  const filled = FILLED_HALF[sourceSystem];
  const half = (d: string, isFilled: boolean) =>
    isFilled ? (
      <path d={d} fill="currentColor" />
    ) : (
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.4" />
    );
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={className}>
      {half(LEFT, filled === "left")}
      {half(RIGHT, filled === "right")}
    </svg>
  );
}

/** The whole mark: apart by a 2 px gap, or closed into one disc once the record is joined. */
export function RecordMark({ joined, className }: { joined: boolean; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={className}>
      <path d={LEFT} fill="currentColor" transform={joined ? "translate(1 0)" : undefined} />
      <path d={RIGHT} fill="currentColor" transform={joined ? "translate(-1 0)" : undefined} />
    </svg>
  );
}
