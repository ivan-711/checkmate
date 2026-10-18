import type { Band } from "@/api/types";
import { BAND_LABELS } from "./BandChip";

/** The band as a stamp: ink outline, the canonical label in capitals (CONCEPT.md §4: the one
 * uppercase on the stage). Bands are not records, so the stamp is never mulberry. */
export function BandStamp({ band, testId }: { band: Band; testId?: string }) {
  return (
    <span
      data-testid={testId}
      className="inline-block self-start rounded-[5px] border-[1.5px] border-ink px-1.5 pb-[3px] pt-1 text-[12.5px] font-semibold leading-none tracking-[0.09em] text-ink"
    >
      {BAND_LABELS[band]}
    </span>
  );
}
