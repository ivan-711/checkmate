import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Entity, GoldenField } from "@/api/types";
import { scenario } from "@/data/scenario";
import { Joined, type JoinedProps } from "./Joined";

const entity = scenario.entityIfApproved;
const cards = scenario.session.sources;
const alert = scenario.alertIfApproved;
const render = (props: Partial<JoinedProps> = {}) =>
  renderToStaticMarkup(
    createElement(Joined, { entity, cards, flag: { kind: "raised", alert }, mode: "instant", ...props }),
  );

describe("Joined", () => {
  it("is the golden record, headed by the patient's name from the API, focusable after a link", () => {
    const html = render();
    expect(html).toContain('data-testid="golden-record"');
    expect(html).toMatch(
      /<h2[^>]*id="golden-heading"[^>]*tabindex="-1"[^>]*>PLACEHOLDER-GIVEN PLACEHOLDER FAMILY</,
    );
    expect(html).toContain('aria-labelledby="golden-heading"');
    expect(html).toContain("Patient record · linked");
  });

  it("names the other spelling and the source that holds it", () => {
    expect(render()).toContain("Also recorded as PLACEHOLDER-FAMILY (Emergency room)");
  });

  it("shows the merged values: born, sex, phone, address", () => {
    const html = render();
    expect(html).toMatch(/Born[\s\S]*?1985-07-03/);
    expect(html).toMatch(/Phone[\s\S]*?\+1 555 555 0100/);
  });

  it("hangs one crosswalk tab per source under the record, each with its local record id", () => {
    const html = render();
    const tabs = html.match(/data-testid="crosswalk-chip"/g);
    expect(tabs).toHaveLength(2);
    expect(html).toMatch(
      /data-testid="crosswalk-chip"[^>]*data-source-system="ER_FHIR"[\s\S]*?PLACEHOLDER-1/,
    );
    expect(html).toMatch(
      /data-testid="crosswalk-chip"[^>]*data-source-system="CLINIC_CSV"[\s\S]*?PLACEHOLDER-2/,
    );
  });

  it("counts what the record holds when the golden fields carry clinical rows, and says nothing otherwise", () => {
    expect(render()).not.toContain("Holds");
    const clinical: GoldenField[] = [
      {
        field: "allergy",
        value: { display: "penicillin V", status: "active" },
        rule: "UNION",
        crosswalk: { sourceSystem: "CLINIC_CSV", sourceRecordId: "PLACEHOLDER-2" },
      },
      {
        field: "activeMedicationOrder",
        value: { display: "amoxicillin", status: "active" },
        rule: "UNION",
        crosswalk: { sourceSystem: "ER_FHIR", sourceRecordId: "PLACEHOLDER-1" },
      },
      {
        field: "activeMedicationOrder",
        value: { display: "lisinopril", status: "active" },
        rule: "UNION",
        crosswalk: { sourceSystem: "ER_FHIR", sourceRecordId: "PLACEHOLDER-1" },
      },
    ];
    const withClinical: Entity = { ...entity, golden: [...(entity.golden ?? []), ...clinical] };
    expect(render({ entity: withClinical })).toMatch(/Holds[\s\S]*?1 allergy · 2 active orders/);
  });

  it("carries the constructed-scenario chip when a member is constructed", () => {
    expect(render()).toContain('data-testid="constructed-scenario-chip"');
  });

  it("holds the notice when the rule flagged the record, and a quiet line when it did not", () => {
    expect(render()).toContain('data-testid="flag-card"');
    const none = render({ flag: { kind: "none" } });
    expect(none).not.toContain('data-testid="flag-card"');
    expect(none).toMatch(/data-testid="flag-quiet"[\s\S]*?The rule did not flag this linked record/);
    const unavailable = render({ flag: { kind: "unavailable" } });
    expect(unavailable).toMatch(/data-testid="flag-quiet"[\s\S]*?not available on this screen/);
  });

  it("never alarms", () => {
    expect(render()).not.toContain('role="alert"');
  });
});
