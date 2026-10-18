import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { CandidatePairDetail, IntakeSession, SafetyAlert } from "@/api/types";
import { DataSourceProvider } from "@/data/DataSourceProvider";
import { scenario } from "@/data/scenario";
import { handoffPairKey, raisedAlertsKey } from "./intake";
import { RegistrarPane } from "./RegistrarPane";

// The server renderer reads the session's server snapshot, which is always empty, so the test
// hands the pane its held check-in directly; everything else in the pane renders for real.
const held = vi.hoisted(() => ({ pairIds: [] as string[] }));
vi.mock("./intake", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./intake")>()),
  useIntakeSession: () => ({ registration: { handoffPairIds: held.pairIds } }) as unknown as IntakeSession,
}));

/** `raised` stands for the alerts the approval's review response returned, kept per pair. */
function renderHeld(detail: CandidatePairDetail, raised?: SafetyAlert[]): string {
  held.pairIds = [detail.pair.id];
  const queryClient = new QueryClient();
  queryClient.setQueryData(handoffPairKey(detail.pair.id), detail);
  if (raised) queryClient.setQueryData(raisedAlertsKey(detail.pair.id), raised);
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

  const linked = {
    ...scenario.pair,
    pair: { ...scenario.pair.pair, decision: { ...scenario.pair.pair.decision, status: "LINKED" as const } },
  };

  it("after an approval that raised a flag, shows its headline, sources, count and a link to the case", () => {
    const html = renderHeld(linked, [scenario.alertIfApproved]);
    const summary = html.slice(html.indexOf('data-testid="registrar-flag-summary"'));
    expect(html).toContain('data-testid="registrar-flag-summary"');
    expect(summary).toMatch(/flagged for clinician review/i);
    expect(summary).toMatch(
      /Penicillin V allergy \(anaphylaxis\).*Clinic CSV.*·.*active amoxicillin order.*ER FHIR/s,
    );
    expect(summary).toContain("1 allergy surfaced");
    expect(summary).toMatch(new RegExp(`<a[^>]*href="/queue/${linked.pair.id}"[^>]*>Open case</a>`));
    expect(html).not.toContain('role="alert"');
    expect(summary).not.toContain("aria-live");
  });

  it("counts every alert the approval raised", () => {
    const second = { ...scenario.alertIfApproved, id: "00000000-0000-4000-8000-000000000951" };
    const html = renderHeld(linked, [scenario.alertIfApproved, second]);
    expect(html).toContain("2 allergies surfaced");
    expect(html.match(/data-testid="registrar-flag-headline"/g)).toHaveLength(2);
  });

  it("after an approval that raised nothing, shows nothing extra", () => {
    for (const html of [renderHeld(linked, []), renderHeld(linked)]) {
      expect(html).toMatch(/Approved by /);
      expect(html).not.toContain('data-testid="registrar-flag-summary"');
      expect(html).not.toContain("Open case");
      expect(html).not.toContain("surfaced");
    }
  });
});
