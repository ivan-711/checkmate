import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Mark } from "./Mark";

// The two half-discs from CONCEPT.md §5: a 9 px radius each, vertical edges at x=11 and x=13 (2 px gap).
const LEFT_HALF = 'd="M11 3A9 9 0 0 0 11 21Z"';
const RIGHT_HALF = 'd="M13 3A9 9 0 0 1 13 21Z"';

function paths(html: string): string[] {
  return [...html.matchAll(/<path[^>]*>/g)].map((m) => m[0]);
}

describe("Mark", () => {
  it("draws two half-discs with a 2 px gap in currentColor, open by default", () => {
    const html = renderToStaticMarkup(createElement(Mark));
    const [left, right] = paths(html);
    expect(left).toContain(LEFT_HALF);
    expect(right).toContain(RIGHT_HALF);
    expect(html).toContain('fill="currentColor"');
    expect(html).toContain('data-state="open"');
    expect(html).not.toMatch(/translate-x-px/);
  });

  it("closes when a link is approved: each half moves 1 px toward the seam", () => {
    const html = renderToStaticMarkup(createElement(Mark, { state: "closed" }));
    expect(html).toContain('data-state="closed"');
    const [left, right] = paths(html);
    expect(left).toMatch(/class="[^"]*(^|\s)translate-x-px(\s|")/);
    expect(right).toMatch(/class="[^"]*(^|\s)-translate-x-px(\s|")/);
  });

  it("transitions each half on the fuse tokens and has no transition under reduced motion", () => {
    for (const path of paths(renderToStaticMarkup(createElement(Mark)))) {
      expect(path).toContain("transition-transform");
      expect(path).toContain("--t-fuse");
      expect(path).toContain("--ease-fuse");
      expect(path).toContain("motion-reduce:transition-none");
    }
  });

  it("takes its size from the caller and is decorative unless given a title", () => {
    const plain = renderToStaticMarkup(createElement(Mark, { size: 26 }));
    expect(plain).toContain('width="26"');
    expect(plain).toContain('height="26"');
    expect(plain).toContain('aria-hidden="true"');
    expect(plain).not.toContain("<title>");
    const titled = renderToStaticMarkup(createElement(Mark, { title: "CheckMate" }));
    expect(titled).toContain('role="img"');
    expect(titled).toContain("<title>CheckMate</title>");
    expect(titled).not.toContain("aria-hidden");
  });
});
