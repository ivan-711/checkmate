"use client";

import { useQuery } from "@tanstack/react-query";
import { useDataSource } from "@/data/DataSourceProvider";

/** The HUMAN_REVIEW tile from review_outcomes_5m: how many decisions registrars recorded. */
export function HumanReviewTile() {
  const source = useDataSource();
  const tiles = useQuery({ queryKey: ["tiles"], queryFn: () => source.getTiles() });
  const tile = tiles.data?.tiles.find((t) => t.id === "HUMAN_REVIEW");
  return (
    <section
      data-testid="tile-human-review"
      aria-labelledby="human-review-heading"
      className="rounded-lg border border-border-subtle bg-surface p-4"
    >
      <h2 id="human-review-heading" className="text-[16px] font-semibold uppercase tracking-wider">
        Human reviews
      </h2>
      {tiles.isPending && <p aria-busy="true">-</p>}
      {tiles.isError && <p className="text-error-ink">Tile unavailable: {tiles.error.message}</p>}
      {tiles.isSuccess && !tile && <p className="text-ink-3">No human-review tile in this response.</p>}
      {tile && (
        <>
          <p className="text-[32px] font-semibold tabular-nums">
            <span data-testid="tile-human-review-total">{tile.total}</span>
          </p>
          <p className="text-[14px] text-ink-3">
            decisions in the last {tile.windowMinutes} minutes · every link requires recorded human approval
          </p>
        </>
      )}
    </section>
  );
}
