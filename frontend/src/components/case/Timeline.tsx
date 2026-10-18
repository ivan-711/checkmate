"use client";

import { useEffect, useState, type CSSProperties } from "react";
import type { MatchDecision, SourceCard, TimelineEvent } from "@/api/types";
import { ConstructedChip } from "@/components/ui/ConstructedChip";
import { SourceGlyph } from "@/components/ui/SourceGlyph";
import { agoText } from "@/lib/desk";
import { actorName, formatCt, sourceLabel } from "@/lib/display";
import styles from "./Timeline.module.css";

/** Rows on screen before "Earlier entries"; a corpus record can carry 100 events per source. */
export const HISTORY_ROWS = 5;
const SECOND_MS = 1000;

const newestFirst = (a: TimelineEvent, b: TimelineEvent) => b.occurredAt.localeCompare(a.occurredAt);

/** Which rows stay on screen: always the newest of each source (so both sources are visible) and
 * every constructed-scenario row (the flag is about it), then the newest of the rest up to `rows`.
 * The rest fold away, newest first. */
export function historyRows(events: TimelineEvent[], rows: number) {
  const sorted = [...events].sort(newestFirst);
  const keep = new Set<TimelineEvent>();
  const seen = new Set<string>();
  for (const e of sorted) {
    if (!seen.has(e.sourceSystem)) {
      seen.add(e.sourceSystem);
      keep.add(e);
    }
    if (e.isConstructed) keep.add(e);
  }
  for (const e of sorted) {
    if (keep.size >= rows) break;
    keep.add(e);
  }
  return { shown: sorted.filter((e) => keep.has(e)), hidden: sorted.filter((e) => !keep.has(e)) };
}

function LinkedBy({ decision }: { decision: MatchDecision }) {
  // The server render says when; once on screen it counts up ("4 s ago").
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), SECOND_MS);
    return () => clearInterval(id);
  }, []);
  const when =
    now === null ? formatCt(decision.decidedAt) : agoText((now - Date.parse(decision.decidedAt)) / SECOND_MS);
  return (
    <p className="text-[15px] text-ink-2">
      Linked by {actorName(decision.actor)} · {when}
    </p>
  );
}

function Row({ event, cards, index }: { event: TimelineEvent; cards: SourceCard[]; index: number }) {
  const side = cards[0]?.record.sourceSystem === event.sourceSystem ? "left" : "right";
  return (
    <li
      data-testid="timeline-event"
      data-source-system={event.sourceSystem}
      className={`${styles.row} grid grid-cols-[6.5rem_1fr] gap-x-3 border-t border-hair py-2 text-[15px]`}
      style={{ "--i": index } as CSSProperties}
    >
      <time dateTime={event.occurredAt} className="font-mono text-[14px] tabular-nums text-ink-2">
        {event.occurredAt.slice(0, 10)}
      </time>
      <span className="min-w-0">
        <span className="flex items-center gap-1.5 text-[13px] text-ink-3">
          <SourceGlyph side={side} size={12} />
          {sourceLabel(event.sourceSystem, cards)}
        </span>
        <span className="flex flex-wrap items-center gap-2">
          {event.display}
          {event.isConstructed && <ConstructedChip />}
        </span>
      </span>
    </li>
  );
}

interface Props {
  events: TimelineEvent[] | null | undefined;
  cards: SourceCard[];
  /** The link this history comes from; null while it is not known. */
  decision?: MatchDecision | null;
}

/** History: both sources' events on the one record, newest first, after a registrar links them. */
export function Timeline({ events, cards, decision = null }: Props) {
  const rows = events ? historyRows(events, HISTORY_ROWS) : null;
  const oldest = rows?.hidden.at(-1)?.occurredAt.slice(0, 4);
  return (
    <section data-testid="timeline" aria-labelledby="timeline-heading" className="space-y-2">
      <div>
        <h2 id="timeline-heading" className="text-[15px] font-semibold text-ink-2">
          History · both sources
        </h2>
        {decision?.status === "LINKED" && <LinkedBy decision={decision} />}
      </div>
      {events === undefined && <p className="text-ink-3">Loading history…</p>}
      {events === null && <p className="text-ink-3">History not available from this source yet.</p>}
      {rows && rows.shown.length === 0 && <p className="text-ink-3">No events on this record yet.</p>}
      {rows && rows.shown.length > 0 && (
        <ol>
          {rows.shown.map((e, i) => (
            <Row key={`${e.resourceId}-${e.occurredAt}`} event={e} cards={cards} index={i} />
          ))}
        </ol>
      )}
      {rows && rows.hidden.length > 0 && (
        <details>
          <summary className="flex h-11 cursor-pointer items-center text-[15px] font-semibold text-ink underline underline-offset-2">
            Earlier entries, oldest {oldest}
          </summary>
          <ol>
            {rows.hidden.map((e, i) => (
              <Row key={`${e.resourceId}-${e.occurredAt}`} event={e} cards={cards} index={i} />
            ))}
          </ol>
        </details>
      )}
    </section>
  );
}
