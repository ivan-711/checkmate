import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Tile, TilesResponse } from "@/api/types";
import { DataSourceProvider } from "@/data/DataSourceProvider";
import { AuditTile } from "./AuditTile";

function renderTile(buckets: Tile["buckets"]): string {
  const tile: Tile = {
    id: "AGENT_GATE",
    aggregate: "agent_gate_5m",
    windowMinutes: 60,
    buckets,
    total: buckets.reduce((n, b) => n + b.count, 0),
    realTime: true,
  };
  const queryClient = new QueryClient();
  queryClient.setQueryData<TilesResponse>(["tiles"], { tiles: [tile], asOf: "2026-10-18T03:13:42Z" });
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(DataSourceProvider, null, createElement(AuditTile)),
    ),
  );
}

const row = (bucket: string, series: string, count: number) => ({
  bucket,
  series,
  count,
  meanLatencyMs: null,
  maxLatencyMs: null,
});

describe("AuditTile", () => {
  it("uses an h2 so the Desk heading outline does not skip a level", () => {
    expect(renderTile([])).toContain('<h2 id="audit-heading"');
  });

  it("labels each row with the 5-minute window agent_gate_5m counted, in CT", () => {
    const html = renderTile([
      row("2026-10-18T03:10:00Z", "ALLOW", 1),
      row("2026-10-18T03:10:00Z", "DENY", 2),
      row("2026-10-18T03:15:00Z", "DENY", 1),
    ]);
    const rows = [...html.matchAll(/<tr>(.*?)<\/tr>/g)].map((r) =>
      [...r[1].matchAll(/<td[^>]*>(.*?)<\/td>/g)].map((cell) => cell[1]),
    );
    expect(rows).toEqual([
      ["22:10 to 22:15", "1", "2"],
      ["22:15 to 22:20", "0", "1"],
    ]);
    expect(html).toContain("3 denied · 1 allowed");
  });

  it("counts one bucket once, however the instant is written", () => {
    const html = renderTile([
      row("2026-10-18T03:10:00Z", "ALLOW", 1),
      row("2026-10-18T03:10:00+00:00", "DENY", 1),
    ]);
    expect(html.match(/22:10 to 22:15/g)).toHaveLength(1);
  });
});
