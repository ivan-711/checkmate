"use client";

import { useQuery } from "@tanstack/react-query";
import { useDataSource } from "@/data/DataSourceProvider";
import { formatCt } from "@/lib/display";

const ROWS_SHOWN = 12;

/** The append-only event feed, newest first; one row per action the demo takes. */
export function EventFeed() {
  const source = useDataSource();
  const events = useQuery({ queryKey: ["events"], queryFn: () => source.getEvents() });
  const rows = events.data?.slice(0, ROWS_SHOWN) ?? [];
  return (
    <section
      aria-labelledby="events-heading"
      className="rounded-lg border border-border-subtle bg-surface p-4"
    >
      <h2 id="events-heading" className="text-[18px] font-semibold uppercase tracking-wider">
        Events
      </h2>
      <p className="mb-2 text-[16px] text-ink-3">Append-only log, newest first</p>
      {events.isPending && <p aria-busy="true">Loading events...</p>}
      {events.isError && <p className="text-error-ink">Events unavailable: {events.error.message}</p>}
      {events.isSuccess && rows.length === 0 && <p className="text-ink-3">No events yet.</p>}
      {rows.length > 0 && (
        <ol className="space-y-1 text-[16px]">
          {rows.map((row) => (
            <li
              key={row.eventId}
              data-testid="event-row"
              data-event-type={row.eventType}
              className="grid grid-cols-[9rem_1fr_auto] gap-2"
            >
              <time dateTime={row.ts} className="tabular-nums text-ink-2">
                {formatCt(row.ts)}
              </time>
              <span className="font-mono">{row.eventType}</span>
              <span className="text-ink-3">{row.actor}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
