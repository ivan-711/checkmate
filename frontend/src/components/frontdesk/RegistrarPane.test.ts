import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { CandidatePairDetail, IntakeSession } from "@/api/types";
import { DataSourceProvider } from "@/data/DataSourceProvider";
import { scenario } from "@/data/scenario";
import { handoffPairKey } from "./intake";
import { RegistrarPane } from "./RegistrarPane";

// The server renderer reads the session's server snapshot, which is always empty, so the test
// hands the pane its held check-in directly; everything else in the pane renders for real.
const held = vi.hoisted(() => ({ pairIds: [] as string[] }));
vi.mock("./intake", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./intake")>()),
  useIntakeSession: () => ({ registration: { handoffPairIds: held.pairIds } }) as unknown as IntakeSession,
}));

function renderHeld(detail: CandidatePairDetail): string {
  held.pairIds = [detail.pair.id];
  const queryClient = new QueryClient();
  queryClient.setQueryData(handoffPairKey(detail.pair.id), detail);
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(DataSourceProvider, null, createElement(RegistrarPane)),
    ),
  );
}

describe("RegistrarPane", () => {
  it("names the band with the kiosk's label, never the enum", () => {
    const fixture = scenario.pair;
    const html = renderHeld({
      ...fixture,
      pair: { ...fixture.pair, decision: { ...fixture.pair.decision, band: "AUTO_LINK" } },
    });
    expect(html).toContain("(AUTO-LINK)");
    expect(html).not.toContain("AUTO_LINK");
  });
});
