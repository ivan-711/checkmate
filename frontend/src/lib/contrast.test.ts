import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// WCAG 2.2 AA on the shipped tokens: 4.5:1 for text, 3:1 for UI parts and marks.
const TEXT = 4.5;
const UI = 3;

const css = readFileSync(path.join(__dirname, "../app/globals.css"), "utf8");

function block(selector: string): Record<string, string> {
  const start = css.indexOf(selector);
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

const PAIRS: [fg: string, bg: string, min: number][] = [
  ["ink-1", "page", TEXT],
  ["ink-1", "surface", TEXT],
  ["ink-2", "surface", TEXT],
  ["ink-3", "surface", TEXT],
  ["ink-3", "page", TEXT],
  ["ink-3", "sunken", TEXT],
  ["ink-3", "kiosk-bg", TEXT],
  // The agent tone (gray) and verified facts (near-black) on the kiosk pane.
  ["ink-2", "kiosk-bg", TEXT],
  ["ink-1", "kiosk-bg", TEXT],
  ["on-accent", "accent", TEXT],
  ["accent", "surface", TEXT],
  ["denied-ink", "denied-bg", TEXT],
  ["error-ink", "error-bg", TEXT],
  ["allowed-ink", "allowed-bg", TEXT],
  ["ink-1", "gate-bg", TEXT],
  ["info", "surface", TEXT],
  ["on-banner", "banner-bg", TEXT],
  ["on-band-auto", "band-auto", TEXT],
  ["on-band-review", "band-review", TEXT],
  ["on-band-keep", "band-keep", TEXT],
  ["border-strong", "surface", UI],
  ["denied-border", "surface", UI],
  ["gate-bar", "surface", UI],
  ["allowed-border", "surface", UI],
  ["evidence-for", "surface", UI],
  ["evidence-against", "surface", UI],
  ["focus", "page", UI],
];

const light = block(":root {");
const themes = { light, dark: { ...light, ...block(':root[data-theme="dark"]') } };

describe.each(Object.entries(themes))("%s tokens", (_, tokens) => {
  it.each(PAIRS)("%s on %s meets %s:1", (fg, bg, min) => {
    expect(tokens[fg], fg).toBeDefined();
    expect(tokens[bg], bg).toBeDefined();
    expect(ratio(tokens[fg], tokens[bg])).toBeGreaterThanOrEqual(min);
  });
});
