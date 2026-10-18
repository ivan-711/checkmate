import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { TimelineEvent } from "@/api/types";
import { scenario } from "@/data/scenario";
import { HISTORY_ROWS, Timeline, historyRows } from "./Timeline";

const cards = scenario.session.sources;
const decision = {
  ...scenario.pair.pair.decision,
  status: "LINKED" as const,
  actor: "registrar:Registrar B",
};
const events = scenario.timelineIfApproved;

function event(
  year: number,
  system: "ER_FHIR" | "CLINIC_CSV",
  display: string,
  extra: Partial<TimelineEvent> = {},
): TimelineEvent {
  return {
    ...events[0],
    occurredAt: `${year}-06-01T00:00:00Z`,
    sourceSystem: system,
    display,
    isConstructed: false,
    resourceId: `${year}-${system}`,
    ...extra,
  };
}

const render = (list: TimelineEvent[] | null | undefined) =>
  renderToStaticMarkup(createElement(Timeline, { events: list, cards, decision }));

describe("Timeline (History)", () => {
  it("is the History pane: both sources, who linked them, one row per event with its source", () => {
    const html = render(events);
    expect(html).toContain('data-testid="timeline"');
    expect(html).toContain("History");
    expect(html).toContain("both sources");
    expect(html).toContain("Linked by Registrar B");
    expect(html).toMatch(/data-testid="timeline-event"[^>]*data-source-system="CLINIC_CSV"/);
    expect(html).toMatch(/data-testid="timeline-event"[^>]*data-source-system="ER_FHIR"/);
    for (const e of events) {
      expect(html).toContain(e.occurredAt.slice(0, 10));
      expect(html).toContain(e.display);
    }
    expect(html).toContain("Clinic CSV");
    expect(html).toContain("ER FHIR");
  });

  it("keeps the newest rows on screen and folds the rest under Earlier entries with the oldest year", () => {
    const many = [
      event(2026, "ER_FHIR", "Amoxicillin order"),
      event(2024, "CLINIC_CSV", "Allergy to penicillin"),
      event(2003, "ER_FHIR", "General examination"),
      event(2002, "ER_FHIR", "Hydrochlorothiazide stopped"),
      event(1998, "ER_FHIR", "Hypertension follow-up"),
      event(1990, "ER_FHIR", "Immunization"),
      event(1982, "ER_FHIR", "Birth record"),
    ];
    const html = render(many);
    const shown = html.slice(0, html.indexOf("<details"));
    expect(shown.match(/data-testid="timeline-event"/g)).toHaveLength(HISTORY_ROWS);
    expect(shown).toContain("Amoxicillin order");
    expect(shown).not.toContain("Birth record");
    expect(html).toContain("Earlier entries, oldest 1982");
    expect(html.slice(html.indexOf("<details"))).toContain("Birth record");
  });

  it("always shows at least one row from each source, and never folds a constructed-scenario row", () => {
    const list = [
      event(2026, "ER_FHIR", "a"),
      event(2025, "ER_FHIR", "b"),
      event(2024, "ER_FHIR", "c"),
      event(2023, "ER_FHIR", "d"),
      event(2022, "ER_FHIR", "e"),
      event(2021, "ER_FHIR", "f"),
      event(2001, "CLINIC_CSV", "Old clinic visit"),
      event(1995, "ER_FHIR", "Constructed order", { isConstructed: true }),
    ];
    const { shown, hidden } = historyRows(list, HISTORY_ROWS);
    expect(shown.some((e) => e.sourceSystem === "CLINIC_CSV")).toBe(true);
    expect(shown.some((e) => e.display === "Constructed order")).toBe(true);
    expect(hidden.length).toBe(list.length - shown.length);
    // Newest first, so the eye lands on the order the flag is about.
    expect(shown[0].display).toBe("a");
  });

  it("says when the history is loading or not available, without inventing rows", () => {
    expect(render(undefined)).toContain("Loading history");
    expect(render(null)).toContain("not available");
    expect(render(null)).not.toContain('data-testid="timeline-event"');
  });
});
