"use client";

import { useQuery } from "@tanstack/react-query";
import { animate, useReducedMotion } from "motion/react";
import { useEffect, useRef } from "react";
import { useDataSource } from "@/data/DataSourceProvider";

/** Eight ticks: enough for a demo's worth of decisions; the numeral carries the exact count. */
const TICKS = 8;
const TICK_SECONDS = 0.5;

/** The numeral ticks up over half a second (CONCEPT.md §5, touch 7); reduced motion sets the
 * value at once. The text node is written by motion, so the testid keeps one child. */
function Numeral({ value }: { value: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const shown = useRef(0);
  const reduce = useReducedMotion();
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const from = shown.current;
    shown.current = value;
    if (reduce || from === value) {
      el.textContent = String(value);
      return;
    }
    const controls = animate(from, value, {
      duration: TICK_SECONDS,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => {
        el.textContent = String(Math.round(v));
      },
    });
    return () => controls.stop();
  }, [value, reduce]);
  return (
    <span ref={ref} data-testid="tile-human-review-total">
      {value}
    </span>
  );
}

/** The HUMAN_REVIEW tile as a meter: a big numeral over a tick bar, with the limit said out loud
 * (the keynote's send meter). Every link is a registrar's recorded decision; nothing links itself. */
export function HumanReviewMeter() {
  const source = useDataSource();
  const tiles = useQuery({ queryKey: ["tiles"], queryFn: () => source.getTiles() });
  const tile = tiles.data?.tiles.find((t) => t.id === "HUMAN_REVIEW");
  const total = tile?.total ?? 0;
  return (
    <div
      data-testid="tile-human-review"
      role="group"
      aria-label="Human reviews"
      className="flex flex-none items-center gap-3.5"
    >
      <span
        aria-busy={tiles.isPending || undefined}
        className="min-w-[18px] text-right font-display text-[30px] font-bold leading-none tracking-[-0.02em] tabular-nums"
      >
        <Numeral value={total} />
      </span>
      <div className="text-[13px] leading-[1.3] text-ink-2">
        <b className="text-[14px] font-semibold text-ink">Human reviews</b>
        <div aria-hidden="true" className="mt-1 flex gap-[3px]">
          {Array.from({ length: TICKS }, (_, i) => (
            <i key={i} className={`block h-[5px] w-4 rounded-[2px] ${i < total ? "bg-ink" : "bg-hair"}`} />
          ))}
        </div>
        {/* auto_link_enabled is false in this build (CLAUDE.md), so this is a fact, not a count. */}
        <span title="Auto-link is off in this build; every link is a registrar's decision.">
          0 automatic links
        </span>
        {tiles.isError && <span className="sr-only">Tile unavailable: {tiles.error.message}</span>}
      </div>
    </div>
  );
}
