import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// Brand files L5 renders from src/app/icon.svg (scripts/render-assets.mjs). These assertions fail
// if a file is missing, the wrong size, or no longer the mark in mulberry.
const APP_DIR = fileURLToPath(new URL(".", import.meta.url));
const PUBLIC_DIR = path.resolve(APP_DIR, "../../public");
const MULBERRY = "#8C1D7E";
const PNG_SIGNATURE = "\x89PNG";
const ICO_HEADER_BYTES = 6;
const ICO_ENTRY_BYTES = 16;

function pngSize(bytes: Buffer): { width: number; height: number } {
  expect(bytes.subarray(0, 4).toString("latin1")).toBe(PNG_SIGNATURE);
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

function publicFile(name: string): Buffer {
  return readFileSync(path.join(PUBLIC_DIR, name));
}

describe("brand assets", () => {
  it("icon.svg is the mark: two half-discs in mulberry, no raster, no script", () => {
    const svg = readFileSync(path.join(APP_DIR, "icon.svg"), "utf8");
    expect(svg).toContain('d="M11 3A9 9 0 0 0 11 21Z"');
    expect(svg).toContain('d="M13 3A9 9 0 0 1 13 21Z"');
    expect(svg).toContain(MULBERRY);
    expect(svg).not.toMatch(/<image|<script|href=/i);
  });

  it.each([
    ["icon-192.png", 192],
    ["icon-512.png", 512],
    ["apple-touch-icon.png", 180],
  ])("%s is a %i px square PNG", (name, px) => {
    expect(pngSize(publicFile(name))).toEqual({ width: px, height: px });
  });

  it("og.png is 1200x630", () => {
    expect(pngSize(publicFile("og.png"))).toEqual({ width: 1200, height: 630 });
  });

  it("favicon.ico holds one 32 px PNG entry", () => {
    const ico = publicFile("favicon.ico");
    expect([...ico.subarray(0, ICO_HEADER_BYTES)]).toEqual([0, 0, 1, 0, 1, 0]);
    const entry = ico.subarray(ICO_HEADER_BYTES, ICO_HEADER_BYTES + ICO_ENTRY_BYTES);
    expect(entry[0]).toBe(32);
    expect(entry[1]).toBe(32);
    const size = entry.readUInt32LE(8);
    const offset = entry.readUInt32LE(12);
    expect(offset).toBe(ICO_HEADER_BYTES + ICO_ENTRY_BYTES);
    expect(pngSize(ico.subarray(offset, offset + size))).toEqual({ width: 32, height: 32 });
  });

  it("manifest names icons that exist, with the mulberry theme and a porcelain background", () => {
    const manifest = JSON.parse(publicFile("manifest.webmanifest").toString("utf8"));
    expect(manifest.name).toBe("CheckMate");
    expect(manifest.theme_color).toBe(MULBERRY);
    expect(manifest.background_color).toBe("#F5F3F4");
    expect(manifest.icons.length).toBeGreaterThanOrEqual(2);
    for (const icon of manifest.icons) {
      const file = path.join(PUBLIC_DIR, icon.src.replace(/^\//, ""));
      expect(existsSync(file), `${icon.src} exists`).toBe(true);
      const px = Number(icon.sizes.split("x")[0]);
      expect(pngSize(readFileSync(file))).toEqual({ width: px, height: px });
    }
  });
});
