import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { WORK_QUEUE_KEY } from "@/components/ui/ResetButton";
import { DataSourceProvider } from "@/data/DataSourceProvider";
import { scenario } from "@/data/scenario";
import { WorkQueue } from "./WorkQueue";

/** The queue with an empty first page (no band or status filter) already loaded. */
function renderEmptyQueue(): string {
  const queryClient = new QueryClient();
  queryClient.setQueryData([...WORK_QUEUE_KEY, "pairs", "", "", null], { items: [], nextCursor: null });
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(DataSourceProvider, null, createElement(WorkQueue)),
    ),
  );
}

describe("WorkQueue", () => {
  it("says nothing is waiting for review when the queue is empty, not that no pair exists yet", () => {
    const html = renderEmptyQueue();
    expect(html).toContain("Nothing is waiting for review.");
    expect(html).not.toContain("No candidate pairs yet");
    expect(html).not.toMatch(/flagged/i); // that word belongs to the clinical flag card
  });
});

/** The queue with one loaded page holding the fixture pair and its detail. */
function renderQueueWith(detail = scenario.pair): string {
  const queryClient = new QueryClient();
  queryClient.setQueryData([...WORK_QUEUE_KEY, "pairs", "", "", null], { items: [detail.pair], nextCursor: null });
  queryClient.setQueryData([...WORK_QUEUE_KEY, "pair", detail.pair.id], detail);
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(DataSourceProvider, null, createElement(WorkQueue)),
    ),
  );
}

describe("WorkQueue rows", () => {
  it("names each record with its source's display label and the band's display label", () => {
    const html = renderQueueWith();
    const row = html.slice(html.indexOf('data-testid="work-queue-row"'));
    expect(row).toContain("ER FHIR");
    expect(row).toContain("Clinic CSV");
    expect(row).toContain("REVIEW");
    expect(row).toContain("0.73");
    expect(row).toContain("Proposed");
    expect(row).toContain("Match run");
    const text = row.replace(/<[^>]+>/g, " ");
    expect(text).not.toMatch(/ER_FHIR|CLINIC_CSV|MATCH_RUN|PROPOSED/);
  });

  it("marks the demo session's own pairs so the hero pair is findable at a glance", () => {
    const html = renderQueueWith();
    expect(html).toMatch(/data-testid="work-queue-row"[^>]*data-session-pair="true"/);
    expect(html).toContain("This session");
  });
});
