"use client";

import { useState } from "react";
import { ConstructedChip } from "@/components/ui/ConstructedChip";
import type { SourceCard, TimelineEvent } from "@/api/types";
import { compactLane } from "@/lib/display";

// A corpus record can carry 100 events per source; the lane shows its latest few so the
// flag card and event feed stay near the fold.
export const TIMELINE_ROWS_PER_SOURCE = 5;

// Marker shape carries the event type alongside its text label, never color alone.
const MARKERS: Record<string, string> = {
  ALLERGY: "rotate-45",
  MEDICATION_ORDER: "",
};

function Marker({ type }: { type: string }) {
  const shape = MARKERS[type] ?? "rounded-full";
  return <span aria-hidden className={`inline-block size-3 shrink-0 bg-ink-1 ${shape}`} />;
}

interface Props {
  events: TimelineEvent[] | null | undefined;
  cards: SourceCard[];
}

export function Timeline({ events, cards }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  return (
    <section
      data-testid="timeline"
      aria-labelledby="timeline-heading"
      className="enter enter-late rounded-lg border border-border-subtle bg-surface p-4"
    >
      <h2 id="timeline-heading" className="text-[18px] font-semibold uppercase tracking-wider">
        Timeline
      </h2>
      <p className="mb-3 text-[16px] text-ink-3">Both sources, linked after approval</p>
      {events === undefined && <p className="text-ink-3">Loading timeline...</p>}
      {events === null && <p className="text-ink-3">Timeline not available from this source yet.</p>}
      {events && (
        <div className="space-y-3">
          {cards.map((card) => {
            const all = events.filter((e) => e.sourceSystem === card.record.sourceSystem);
            const open = expanded.has(card.record.id);
            const { shown: lane, hidden } = compactLane(all, open ? all.length : TIMELINE_ROWS_PER_SOURCE);
            return (
              <div key={card.record.id} className="grid grid-cols-[8rem_1fr] gap-3">
                <h3 className="font-semibold">{card.displayLabel}</h3>
                {lane.length === 0 ? (
                  <p className="text-ink-3">No events from this source.</p>
                ) : (
                  <div>
                    <ol className="space-y-1">
                      {lane.map((e) => (
                        <li
                          key={`${e.resourceId}-${e.occurredAt}`}
                          data-testid="timeline-event"
                          data-source-system={e.sourceSystem}
                          className="flex flex-wrap items-center gap-2"
                        >
                          <Marker type={e.type} />
                          <time dateTime={e.occurredAt} className="tabular-nums text-ink-2">
                            {e.occurredAt.slice(0, 10)}
                          </time>
                          <span>{e.display}</span>
                          {e.isConstructed && <ConstructedChip />}
                        </li>
                      ))}
                    </ol>
                    {hidden > 0 && (
                      <button
                        type="button"
                        onClick={() => setExpanded((prev) => new Set(prev).add(card.record.id))}
                        className="mt-1 h-11 font-semibold text-accent underline underline-offset-2"
                      >
                        Show all ({all.length})
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
