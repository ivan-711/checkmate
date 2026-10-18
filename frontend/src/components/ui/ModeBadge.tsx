import type { Mode } from "@/data/source";

const BADGES: Record<Mode, { label: string; title: string; dashed: boolean }> = {
  REPLAY: {
    label: "Replay",
    title: "Replay: the agent's turns are recorded. No live model calls.",
    dashed: true,
  },
  LOCAL: {
    label: "Local",
    title: "Local: the engine runs on this laptop; events go to the local database.",
    dashed: false,
  },
};

/** One mode label in the top bar, a status rather than a control. The testid is the one
 * eval/acceptance/g16.spec.ts reads. */
export function ModeBadge({ mode }: { mode: Mode }) {
  const { label, title, dashed } = BADGES[mode];
  return (
    <span
      data-testid="app-mode-badge"
      data-mode={mode}
      title={title}
      className="inline-flex h-9 items-center gap-2 rounded-[10px] border border-hair px-3 text-[14px] font-semibold text-ink-2"
    >
      <span
        aria-hidden="true"
        className={`block h-4 w-4 rounded-full border-[1.5px] border-ink-2 ${dashed ? "border-dashed" : ""}`}
      />
      <span>{label}</span>
      <span className="sr-only">mode. {title}</span>
    </span>
  );
}
