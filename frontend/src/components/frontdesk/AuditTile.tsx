"use client";

import { useQuery } from "@tanstack/react-query";
import type { Tile } from "@/api/types";
import { useDataSource } from "@/data/DataSourceProvider";
import { formatCt } from "@/lib/display";

const TILE_POLL_MS = 2_000; // UX spec 3.13: the FrontDesk tile refreshes every 2 s

function countsByBucket(tile: Tile) {
  const rows = new Map<string, { allowed: number; denied: number }>();
  for (const b of tile.buckets) {
    const row = rows.get(b.bucket) ?? { allowed: 0, denied: 0 };
    if (b.series === "ALLOW") row.allowed += b.count;
    if (b.series === "DENY") row.denied += b.count;
    rows.set(b.bucket, row);
  }
  return [...rows.entries()].sort(([a], [b]) => a.localeCompare(b));
}

/** The AGENT_GATE slot: allowed versus denied agent actions from agent_gate_5m. */
export function AuditTile() {
  const source = useDataSource();
  const tiles = useQuery({
    queryKey: ["tiles"],
    queryFn: () => source.getTiles(),
    refetchInterval: TILE_POLL_MS,
  });
  const tile = tiles.data?.tiles.find((t) => t.id === "AGENT_GATE");
  const rows = tile ? countsByBucket(tile) : [];
  const allowed = rows.reduce((n, [, r]) => n + r.allowed, 0);
  const denied = rows.reduce((n, [, r]) => n + r.denied, 0);

  return (
    <section
      aria-labelledby="audit-heading"
      className="rounded-lg border border-border-subtle bg-surface p-4"
    >
      <h3 id="audit-heading" className="text-[16px] font-semibold uppercase tracking-wider">
        Agent actions per 5 minutes
      </h3>
      {tiles.isPending && <p aria-busy="true">-</p>}
      {tiles.isError && <p className="text-error-ink">Audit tile unavailable: {tiles.error.message}</p>}
      {tiles.isSuccess && !tile && <p className="text-ink-3">No agent-gate tile in this response.</p>}
      {tile && tile.total === 0 && (
        <>
          <p className="text-[24px] font-semibold">No agent actions yet.</p>
          <p className="text-ink-3">Start a check-in to record the first one.</p>
        </>
      )}
      {tile && tile.total > 0 && (
        <>
          <p className="text-[24px] font-semibold tabular-nums">
            {denied} denied · {allowed} allowed
          </p>
          <table className="mt-2 text-[16px] tabular-nums">
            <thead>
              <tr className="text-left text-ink-3">
                <th className="pr-4 font-normal">Bucket start (CT)</th>
                <th className="pr-4 font-normal">Allowed</th>
                <th className="font-normal">Denied</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([bucket, r]) => (
                <tr key={bucket}>
                  <td className="pr-4">{formatCt(bucket)}</td>
                  <td className="pr-4">{r.allowed}</td>
                  <td>{r.denied}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {tile && (
        <p className="mt-2 font-mono text-[14px] text-ink-3">{tile.aggregate} · continuous aggregate</p>
      )}
    </section>
  );
}
