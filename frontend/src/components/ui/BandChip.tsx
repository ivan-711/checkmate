import { Check, Eye, Split } from "lucide-react";
import type { Band } from "@/api/types";

const BANDS = {
  AUTO_LINK: { label: "AUTO-LINK", Icon: Check, className: "bg-band-auto text-on-band-auto" },
  REVIEW: { label: "REVIEW", Icon: Eye, className: "bg-band-review text-on-band-review" },
  KEEP_SEPARATE: { label: "KEEP SEPARATE", Icon: Split, className: "bg-band-keep text-on-band-keep" },
} as const satisfies Record<Band, unknown>;

/** The band names every screen shows, so the chip, the funnel and the filters read alike. */
export const BAND_LABELS = {
  AUTO_LINK: BANDS.AUTO_LINK.label,
  REVIEW: BANDS.REVIEW.label,
  KEEP_SEPARATE: BANDS.KEEP_SEPARATE.label,
} as const satisfies Record<Band, string>;

/** `label` replaces the English text where the screen is in another language (the kiosk);
 * `kiosk` sets it at 16 px, the kiosk's smallest text size. */
export function BandChip({
  band,
  label: override,
  kiosk = false,
}: {
  band: Band;
  label?: string;
  kiosk?: boolean;
}) {
  const { label, Icon, className } = BANDS[band];
  return (
    <span
      data-testid="band-chip"
      className={`inline-flex items-center gap-1 rounded px-2 py-0.5 ${kiosk ? "text-[16px]" : "text-[14px]"} font-semibold ${className}`}
    >
      <Icon aria-hidden size={16} />
      {override ?? label}
    </span>
  );
}
