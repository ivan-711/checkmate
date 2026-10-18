import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { SourceCardView } from "@/components/case/SourceCardView";
import { scenario } from "@/data/scenario";
import type { CardField } from "@/lib/display";
import { CiteProvider } from "./CiteProvider";

const card = scenario.pair.recordA;
const render = (cite: "family" | "addr" | null) =>
  renderToStaticMarkup(
    createElement(CiteProvider, {
      initial: cite,
      children: createElement(SourceCardView, { card, differs: new Set<CardField>() }),
    }),
  );

describe("hover-to-cite on a source card", () => {
  it("washes the cited field and nothing else", () => {
    const html = render("family");
    expect(html).toMatch(/data-field="family"[^>]*data-cited="true"/);
    expect(html).toMatch(/data-field="given"[^>]*data-cited="false"/);
  });

  it("an address cite washes the street and the ZIP together", () => {
    const html = render("addr");
    expect(html.match(/data-field="addr"[^>]*data-cited="true"/g)).toHaveLength(2);
  });

  it("washes nothing when no row is cited, and renders without a provider", () => {
    expect(render(null)).not.toContain('data-cited="true"');
    const bare = renderToStaticMarkup(createElement(SourceCardView, { card, differs: new Set<CardField>() }));
    expect(bare).not.toContain('data-cited="true"');
  });
});
