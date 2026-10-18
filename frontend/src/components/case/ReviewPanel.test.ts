import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { CandidatePairDetail } from "@/api/types";
import { DeskProvider } from "@/components/desk/DeskContext";
import { DataSourceProvider } from "@/data/DataSourceProvider";
import { scenario } from "@/data/scenario";
import type { Sheet } from "@/lib/desk";
import { ReviewPanel } from "./ReviewPanel";

const hero = scenario.pair;
const kiosk = "kiosk-record";

function handoff(id: string, p: number): CandidatePairDetail {
  return {
    ...hero,
    pair: {
      ...hero.pair,
      id,
      origin: "FRONTDESK_HANDOFF",
      recordAId: kiosk,
      recordBId: hero.pair.recordAId,
      decision: { ...hero.pair.decision, p },
    },
  };
}

function render(sheet: Sheet, handoffPairs: CandidatePairDetail[] = []): string {
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: new QueryClient() },
      createElement(
        DataSourceProvider,
        null,
        createElement(
          DeskProvider,
          null,
          createElement(ReviewPanel, {
            detail: hero,
            handoffPairs,
            sheet,
            onSheetChange: () => {},
            onConfirmed: () => {},
            onDecided: () => {},
          }),
        ),
      ),
    ),
  );
}

describe("ReviewPanel", () => {
  it("offers Approve link and Reject while no sheet is open, and no confirm button", () => {
    const html = render(null);
    expect(html).toMatch(/data-testid="approve-button"[^>]*>Approve link/);
    expect(html).toMatch(/data-testid="reject-button"[^>]*>Reject/);
    expect(html).not.toContain('data-testid="review-submit-button"');
    expect(html).not.toContain('data-testid="review-reason-select"');
  });

  it("the approve sheet asks the question, takes the registrar and a note, and confirms the link", () => {
    const html = render("approve");
    expect(html).toContain("Link these two records?");
    for (const name of scenario.registrarLabels)
      expect(html).toMatch(new RegExp(`<option[^>]*>${name}</option>`));
    expect(html).toContain('data-testid="review-note-input"');
    expect(html).toMatch(/data-testid="review-submit-button"[^>]*>Confirm link/);
    expect(html).not.toContain('data-testid="review-reason-select"');
    expect(html).not.toContain('data-testid="approve-button"');
  });

  it("the reject sheet requires a reason in plain words and confirms the reject", () => {
    const html = render("reject");
    expect(html).toContain("Keep these records apart?");
    expect(html).toMatch(/data-testid="review-reason-select"/);
    expect(html).toContain('value="INSUFFICIENT_EVIDENCE">Not enough evidence<');
    expect(html).toContain('value="DIFFERENT_PERSON">Different person<');
    expect(html).toMatch(/data-testid="review-submit-button"[^>]*>Confirm reject/);
    expect(html).not.toContain("Also attach the kiosk check-in");
  });

  it("offers to attach the kiosk check-in, on by default, when a hand-off pair is waiting", () => {
    const html = render("approve", [handoff("h-low", 0.66), handoff("h-high", 0.98)]);
    expect(html).toContain('data-testid="attach-checkin"');
    expect(html).toMatch(/data-testid="attach-checkin"[^>]*checked/);
    expect(html).toContain("Also attach the kiosk check-in");
    expect(html).toContain("Matches the ER FHIR record at 0.98. Saved as a second approval.");
  });

  it("offers no attach row when no check-in is held, or when the held pair is the one under review", () => {
    expect(render("approve", [])).not.toContain("Also attach the kiosk check-in");
    expect(render("approve", [hero])).not.toContain("Also attach the kiosk check-in");
    const linked = {
      ...handoff("h", 0.98),
      pair: { ...handoff("h", 0.98).pair, decision: { ...hero.pair.decision, status: "LINKED" as const } },
    };
    expect(render("approve", [linked])).not.toContain("Also attach the kiosk check-in");
  });

  it("never shows a reason code or decision status as visible text", () => {
    for (const sheet of [null, "approve", "reject"] as Sheet[]) {
      const text = render(sheet, [handoff("h", 0.98)]).replace(/<[^>]+>/g, " ");
      expect(text).not.toMatch(/INSUFFICIENT_EVIDENCE|DIFFERENT_PERSON|PROPOSED|FRONTDESK_HANDOFF/);
    }
  });
});
