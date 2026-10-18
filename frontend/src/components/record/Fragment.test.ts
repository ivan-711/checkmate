import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { SourceCard } from "@/api/types";
import { scenario } from "@/data/scenario";
import {
  bodyVariants,
  contentVariants,
  fillVariants,
  Fragment,
  fragmentVariants,
  type FragmentCustom,
  type FragmentProps,
} from "./Fragment";

const [er, cl] = scenario.session.sources;
const render = (props: FragmentProps) => renderToStaticMarkup(createElement(Fragment, props));

describe("Fragment", () => {
  it("keeps the source-card hooks: testid, source system and a labelled article", () => {
    const html = render({ card: er, side: "er" });
    expect(html).toContain('data-testid="source-card"');
    expect(html).toContain('data-source-system="ER_FHIR"');
    expect(html).toContain('data-side="er"');
    expect(html).toContain('aria-label="Emergency room record"');
  });

  it("names the source in plain words with its format, and shows the record id to copy", () => {
    const html = render({ card: cl, side: "cl" });
    expect(html).toContain("Clinic");
    expect(html).toContain("CSV export");
    expect(html).toMatch(/title="Copy record ID"[^>]*>PLACEHOLDER-2/);
  });

  it("marks every cited field so a thread and a cite can find it", () => {
    const html = render({ card: er, side: "er" });
    expect(html).toMatch(/data-field="given"[^>]*>PLACEHOLDER-GIVEN</);
    expect(html).toMatch(/data-field="family"[^>]*>PLACEHOLDER-FAMILY</);
    expect(html).toMatch(/data-field="dob"[\s\S]*?1985-07-03/);
    expect(html).toMatch(/data-field="addr"[\s\S]*?100 Placeholder St, 54311/);
    expect(html).toMatch(/Phone[\s\S]*?\+1 555 555 0100/);
    expect(html).toMatch(/Sex[\s\S]*?Female/);
  });

  it("says when a value is not given, and never says differs: the thread's mark carries that", () => {
    const noPhone: SourceCard = { ...cl, normalized: { ...cl.normalized, phoneE164: null } };
    const html = render({ card: noPhone, side: "cl" });
    expect(html).toContain("Not given");
    expect(html).not.toContain("differs");
  });

  it("carries the constructed-scenario chip only when the record is constructed", () => {
    expect(render({ card: er, side: "er" })).toContain('data-testid="constructed-scenario-chip"');
    expect(render({ card: cl, side: "cl" })).not.toContain('data-testid="constructed-scenario-chip"');
  });

  it("underlines the spelling this record has and the other lacks, or shows a gap where it is missing", () => {
    const hyphen: SourceCard = { ...er, normalized: { ...er.normalized, familyName: "Ana-Lu" } };
    const underlined = render({ card: hyphen, side: "er", diff: { side: "a", start: 3, end: 4 } });
    expect(underlined).toMatch(/data-field="family"[^>]*>Ana<i class="org-d">-<\/i>Lu</);
    const bare: SourceCard = { ...cl, normalized: { ...cl.normalized, familyName: "AnaLu" } };
    const gapped = render({ card: bare, side: "cl", diff: { side: "a", start: 3, end: 4 } });
    expect(gapped).toMatch(/data-field="family"[^>]*>Ana<i class="org-gap" aria-hidden="true"><\/i>Lu</);
  });

  it("falls back to the API's own label for a source it does not know", () => {
    const kiosk: SourceCard = {
      ...er,
      displayLabel: "Kiosk check-in",
      record: { ...er.record, sourceSystem: "KIOSK", kind: "FRONTDESK_INTAKE" },
    };
    const html = render({ card: kiosk, side: "er" });
    expect(html).toContain('aria-label="Kiosk check-in record"');
    expect(html).toContain("Kiosk check-in");
  });
});

describe("fragment variants", () => {
  // Motion resolves an inherited label with each node's own `custom`; a node without one passes
  // undefined. That must never throw (it took the whole Desk down on Approve).
  it("resolve every stage without a custom, as an instant change", () => {
    for (const variants of [fragmentVariants("er"), bodyVariants("cl"), contentVariants, fillVariants]) {
      for (const value of Object.values(variants)) {
        if (typeof value === "function") expect(() => value(undefined, {}, {})).not.toThrow();
      }
    }
    const linked = fragmentVariants("er").linked as (c?: FragmentCustom) => { opacity?: number };
    expect(linked()).toMatchObject({ opacity: 0 });
  });
});
