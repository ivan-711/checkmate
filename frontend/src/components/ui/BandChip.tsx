import { Check, Eye, Split } from "lucide-react";
import type { Band } from "@/api/types";

const BANDS = {
  AUTO_LINK: { label: "AUTO-LINK", Icon: Check, className: "bg-band-auto text-on-band-auto" },
  REVIEW: { label: "REVIEW", Icon: Eye, className: "bg-band-review text-on-band-review" },
  KEEP_SEPARATE: { label: "KEEP SEPARATE", Icon: Split, className: "bg-band-keep text-on-band-keep" },
} as const satisfies Record<Band, unknown>;

export function BandChip({ band }: { band: Band }) {
  const { label, Icon, className } = BANDS[band];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[14px] font-semibold ${className}`}
    >
      <Icon aria-hidden size={16} />
      {label}
    </span>
  );
}
