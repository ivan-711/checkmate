import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { CandidatePairDetail, IntakeSession, SafetyAlert } from "@/api/types";
import { DataSourceProvider } from "@/data/DataSourceProvider";
import { scenario } from "@/data/scenario";
import { approvalAlertsKey, handoffPairKey } from "./intake";
import { RegistrarPane } from "./RegistrarPane";

// The server renderer reads the session's server snapshot, which is always empty, so the test
// hands the pane its held check-in directly; everything else in the pane renders for real.
const held = vi.hoisted(() => ({ pairIds: [] as string[] }));
vi.mock("./intake", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./intake")>()),
  useIntakeSession: () => ({ registration: { handoffPairIds: held.pairIds } }) as unknown as IntakeSession,
}));

/** `alerts` stands for the review response's alerts: every active flag on the linked chart. */
function renderHeld(detail: CandidatePairDetail, alerts?: SafetyAlert[]): string {
  held.pairIds = [detail.pair.id];
  const queryClient = new QueryClient();
  queryClient.setQueryData(handoffPairKey(detail.pair.id), detail);
  if (alerts) queryClient.setQueryData(approvalAlertsKey(detail.pair.decision.id), alerts);
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

  it("after an approval whose chart has a flag, shows its headline, sources, count and a link to the case", () => {
    const html = renderHeld(linked, [scenario.alertIfApproved]);
    const summary = html.slice(html.indexOf('data-testid="registrar-flag-summary"'));
    expect(html).toContain('data-testid="registrar-flag-summary"');
    expect(summary).toMatch(/flagged for clinician review/i);
    expect(summary).toMatch(
      /Penicillin V allergy \(anaphylaxis\).*Clinic CSV.*·.*active amoxicillin order.*ER FHIR/s,
    );
    expect(summary).toContain("1 safety flag on the linked chart");
    expect(summary).toMatch(new RegExp(`<a[^>]*href="/queue/${linked.pair.id}"[^>]*>Open case</a>`));
    expect(html).not.toContain('role="alert"');
    expect(summary).not.toContain("aria-live");
  });

  it("never shows a flag kept for an earlier decision on the same pair (after Reset)", () => {
    const relinked = {
      ...linked,
      pair: { ...linked.pair, decision: { ...linked.pair.decision, id: "later" } },
    };
    held.pairIds = [relinked.pair.id];
    const queryClient = new QueryClient();
    queryClient.setQueryData(handoffPairKey(relinked.pair.id), relinked);
    queryClient.setQueryData(approvalAlertsKey(linked.pair.decision.id), [scenario.alertIfApproved]);
    const html = renderToStaticMarkup(
      createElement(
        QueryClientProvider,
        { client: queryClient },
        createElement(DataSourceProvider, null, createElement(RegistrarPane)),
      ),
    );
    expect(html).toMatch(/Approved by /);
    expect(html).not.toContain('data-testid="registrar-flag-summary"');
  });

  // One alert is one allergy-and-order flag, so the line counts flags, never allergies.
  const base = scenario.alertIfApproved;
  const summaryOf = (html: string) => {
    const start = html.indexOf('data-testid="registrar-flag-summary"');
    return html.slice(start, html.indexOf("</section>", start));
  };

  it("one allergy against two orders is two flags, one line each, not two allergies", () => {
    const secondOrder = {
      ...base,
      id: "00000000-0000-4000-8000-000000000951",
      orderRef: { ...base.orderRef, resourceId: "MedicationRequest/second-order" },
      cardText: base.cardText.replace("amoxicillin 500 MG Oral Tablet", "ampicillin 500 MG Oral Capsule"),
    };
    const summary = summaryOf(renderHeld(linked, [base, secondOrder]));
    expect(summary).toContain("2 safety flags on the linked chart");
    expect(summary).toMatch(/active amoxicillin order.*active ampicillin order/s);
    expect(summary).not.toMatch(/\d+ allerg/); // never a count of allergies
  });

  it("two allergies against one order are two flags", () => {
    const secondAllergy = {
      ...base,
      id: "00000000-0000-4000-8000-000000000952",
      allergyRef: { ...base.allergyRef, resourceId: "allergies.csv:second-allergy" },
      cardText: base.cardText.replace("coded penicillin V", "coded penicillin G"),
    };
    const summary = summaryOf(renderHeld(linked, [base, secondAllergy]));
    expect(summary).toContain("2 safety flags on the linked chart");
    expect(summary).toMatch(/Penicillin V allergy.*Penicillin G allergy/s);
  });

  it("a flag the chart already had reads as on the chart, never as new from this approval", () => {
    // The review response returns every current flag on the entity, kept ones included.
    const kept = { ...base, identifiedAt: "2026-10-17T09:00:00Z" };
    const summary = summaryOf(renderHeld(linked, [kept]));
    expect(summary).toContain("1 safety flag on the linked chart");
    expect(summary).not.toMatch(/surfaced|raised|\bnew\b/i);
  });

  it("after an approval whose chart has no flag, shows nothing extra", () => {
    for (const html of [renderHeld(linked, []), renderHeld(linked)]) {
      expect(html).toMatch(/Approved by /);
      expect(html).not.toContain('data-testid="registrar-flag-summary"');
      expect(html).not.toContain("Open case");
      expect(html).not.toContain("safety flag");
    }
  });
});
