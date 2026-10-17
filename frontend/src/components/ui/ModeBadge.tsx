import { Laptop, Rewind } from "lucide-react";
import type { Mode } from "@/data/source";

const BADGES = {
  REPLAY: {
    Icon: Rewind,
    border: "border-dashed",
    title: "Recorded run with original timings; nothing is recomputed.",
  },
  LOCAL: {
    Icon: Laptop,
    border: "border-solid",
    title: "Engine running on this laptop; events in local TimescaleDB on this laptop.",
  },
} as const;

export function ModeBadge({ mode }: { mode: Mode }) {
  const { Icon, border, title } = BADGES[mode];
  return (
    <span
      data-testid="app-mode-badge"
      title={title}
      className={`inline-flex h-9 items-center gap-2 rounded border-2 ${border} border-ink-1 px-3 text-[14px] font-semibold tracking-wide`}
    >
      <Icon aria-hidden size={16} />
      <span>{mode}</span>
      <span className="sr-only">mode. {title}</span>
    </span>
  );
}
