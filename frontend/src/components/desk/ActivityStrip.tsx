"use client";

import { useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useDataSource } from "@/data/DataSourceProvider";
import { groupEvents } from "@/lib/desk";
import { actorName, eventLabel, formatCt } from "@/lib/display";
import { HumanReviewMeter } from "./HumanReviewMeter";

/** The strip shows this many groups; the drawer holds every row the feed returned. */
const STRIP_GROUPS = 3;

/** "01:33:09 CT" reads as "01:33:09" in the strip; the drawer keeps the zone. */
function clock(iso: string): string {
  return formatCt(iso).replace(/ CT$/, "");
}

/** The gate tile: "1 denied · 0 allowed", from the AGENT_GATE aggregate's buckets. */
function GateCount() {
  const source = useDataSource();
  const tiles = useQuery({ queryKey: ["tiles"], queryFn: () => source.getTiles() });
  const tile = tiles.data?.tiles.find((t) => t.id === "AGENT_GATE");
  const count = (series: string) =>
    tile?.buckets.filter((b) => b.series === series).reduce((sum, b) => sum + b.count, 0) ?? 0;
  return (
    <div
      data-testid="tile-agent-gate"
      className="flex-none border-l border-hair pl-4 text-[13px] leading-[1.3] text-ink-2"
    >
      <b className="block text-[14px] font-semibold text-ink">
        {count("DENY")} denied · {count("ALLOW")} allowed
      </b>
      Gate, last {tile?.windowMinutes ?? 5} min
    </div>
  );
}

/** The Activity strip (CONCEPT.md §3): the newest events with repeats collapsed, the gate tile
 * and the human-review meter. The full feed stays mounted in a drawer (closed by default), one
 * event-row per event, so an earlier row such as LINK_REJECTED is still on the page after newer
 * events push it out of the strip. */
export function ActivityStrip() {
  const source = useDataSource();
  const events = useQuery({ queryKey: ["events"], queryFn: () => source.getEvents() });
  const rows = events.data ?? [];
  const groups = groupEvents(rows).slice(0, STRIP_GROUPS);
  const [open, setOpen] = useState(false);
  const drawerId = useId();

  return (
    <footer className="strip relative">
      <span className="text-[14px] font-semibold text-ink-2">Activity</span>
      <ol
        data-testid="activity-strip"
        aria-label="Latest activity"
        className="flex min-w-0 flex-1 flex-wrap gap-x-[22px] overflow-hidden"
        style={{ height: 22 }}
      >
        {events.isPending && (
          <li aria-busy="true" className="text-[14px] text-ink-3">
            Loading…
          </li>
        )}
        {events.isError && <li className="text-[14px] text-ink-2">Activity unavailable: {events.error.message}</li>}
        {events.isSuccess && rows.length === 0 && <li className="text-[14px] text-ink-3">No activity yet.</li>}
        {groups.map((g) => (
          <li
            key={g.eventId}
            data-testid="activity-item"
            data-event-type={g.eventType}
            className="flex items-baseline gap-2 whitespace-nowrap text-[14px]"
          >
            <time dateTime={g.ts} className="font-mono text-[13px] text-ink-3">
              {clock(g.ts)}
            </time>
            <span>{eventLabel(g.eventType)}</span>
            {g.count > 1 && <span className="text-ink-3">×{g.count}</span>}
          </li>
        ))}
      </ol>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={drawerId}
        onClick={() => setOpen((o) => !o)}
        className="flex-none text-[14px] font-semibold text-ink hover:underline"
      >
        {open ? "Hide log" : "All activity"}
      </button>
      <GateCount />
      <HumanReviewMeter />

      <div
        id={drawerId}
        role="region"
        aria-label="Activity log"
        hidden={!open}
        className="absolute bottom-full left-0 right-0 z-20 mb-2 max-h-[60vh] overflow-auto rounded-[20px] bg-paper p-4 shadow-[0_30px_80px_-20px_rgba(40,10,35,0.45),0_0_0_1px_var(--hair)]"
      >
        <p className="mb-2 text-[14px] font-semibold text-ink-2">Append-only log, newest first</p>
        <ol className="space-y-1 text-[15px]">
          {rows.map((row) => (
            <li
              key={row.eventId}
              data-testid="event-row"
              data-event-type={row.eventType}
              className="grid grid-cols-[9rem_1fr_auto] gap-2"
            >
              <time dateTime={row.ts} className="font-mono text-[13px] text-ink-3">
                {formatCt(row.ts)}
              </time>
              <span>
                {eventLabel(row.eventType)}
                <span className="ml-2 font-mono text-[12px] text-ink-3">{row.eventType}</span>
              </span>
              <span className="text-ink-3">{actorName(row.actor)}</span>
            </li>
          ))}
        </ol>
      </div>
    </footer>
  );
}
