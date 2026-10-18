import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// WCAG 2.2 AA on the shipped tokens: 4.5:1 for text, 3:1 for UI parts and marks.
const TEXT = 4.5;
const UI = 3;

const css = readFileSync(path.join(__dirname, "../app/globals.css"), "utf8");

function block(selector: string): Record<string, string> {
  const start = css.indexOf(selector);
  if (start < 0) throw new Error(`globals.css has no "${selector}" block`);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start));
  return Object.fromEntries([...body.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})/g)].map((m) => [m[1], m[2]]));
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function ratio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

// The living-record tokens (CONCEPT.md §4). The venue runs light; dark is reserved, not built.
const PAIRS: [fg: string, bg: string, min: number][] = [
  ["ink", "porcelain", TEXT],
  ["ink", "paper", TEXT],
  ["ink-2", "porcelain", TEXT],
  ["ink-2", "paper", TEXT],
  ["ink-2", "mulberry-tint", TEXT],
  ["ink-3", "porcelain", TEXT],
  ["ink-3", "paper", TEXT],
  ["paper", "mulberry", TEXT],
  ["paper", "mulberry-deep", TEXT],
  ["mulberry-deep", "mulberry-tint", TEXT],
  ["mulberry-deep", "paper", TEXT],
  ["ink", "mulberry-tint", TEXT],
  ["ink", "mulberry-cite", TEXT],
  ["amber-ink", "amber-surface", TEXT],
  ["ink", "amber-surface", TEXT],
  ["paper", "ink", TEXT],
  ["hair-strong", "paper", UI],
  ["hair-strong", "porcelain", UI],
  ["mulberry", "paper", UI],
  ["mulberry", "porcelain", UI],
  ["ink", "porcelain", UI],
];

const light = block(":root {");

describe("light tokens", () => {
  it.each(PAIRS)("%s on %s meets %s:1", (fg, bg, min) => {
    expect(light[fg], fg).toBeDefined();
    expect(light[bg], bg).toBeDefined();
    expect(ratio(light[fg], light[bg])).toBeGreaterThanOrEqual(min);
  });

  it("has no red anywhere: every token hue stays off pure red", () => {
    for (const [name, hex] of Object.entries(light)) {
      const n = parseInt(hex.slice(1), 16);
      const [r, g, b] = [n >> 16, (n >> 8) & 255, n & 255];
      expect(r > 150 && g < 90 && b < 90, `${name} ${hex} reads as red`).toBe(false);
    }
  });
});
