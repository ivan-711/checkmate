import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { WORK_QUEUE_KEY } from "@/components/ui/ResetButton";
import { DataSourceProvider } from "@/data/DataSourceProvider";
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
