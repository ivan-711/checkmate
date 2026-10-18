import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { inflateSync } from "node:zlib";
import { describe, expect, it } from "vitest";

// Brand files L5 renders from src/app/icon.svg (scripts/render-assets.mjs). These assertions fail
// if a file is missing, the wrong size, or no longer the mark in mulberry.
const APP_DIR = fileURLToPath(new URL(".", import.meta.url));
const PUBLIC_DIR = path.resolve(APP_DIR, "../../public");
const MULBERRY = "#8C1D7E";
const PNG_SIGNATURE = "\x89PNG";
const ICO_HEADER_BYTES = 6;
const ICO_ENTRY_BYTES = 16;
const FAVICON_PX = 32;
// The favicon mark fills about 0.85 of the box (scripts/render-assets.mjs); allow a pixel either way.
const FAVICON_MARK_SPAN = { min: 0.8, max: 0.9 };
// A maskable launcher icon may be cut to the central circle of 80 % of its width.
const MASKABLE_SAFE_RADIUS = 0.4;
// Launcher icons sit on porcelain; a channel more than this far from it is part of the mark.
const BACKGROUND_TOLERANCE = 8;
const PORCELAIN_RGB = [0xf5, 0xf3, 0xf4];
const PNG_CHANNELS: Record<number, number> = { 2: 3, 6: 4 }; // colour type -> RGB, RGBA

type Pixels = { width: number; height: number; channels: number; data: Uint8Array };
type Box = { left: number; top: number; right: number; bottom: number };

function pngSize(bytes: Buffer): { width: number; height: number } {
  expect(bytes.subarray(0, 4).toString("latin1")).toBe(PNG_SIGNATURE);
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

function publicFile(name: string): Buffer {
  return readFileSync(path.join(PUBLIC_DIR, name));
}

function paeth(a: number, b: number, c: number): number {
  const p = a + b - c;
  const [pa, pb, pc] = [Math.abs(p - a), Math.abs(p - b), Math.abs(p - c)];
  if (pa <= pb && pa <= pc) return a;
  return pb <= pc ? b : c;
}

/** Decodes the 8-bit, non-interlaced RGB or RGBA PNGs Chromium writes; enough to read the pixels. */
function decodePng(bytes: Buffer): Pixels {
  const { width, height } = pngSize(bytes);
  expect(bytes[24], "bit depth").toBe(8);
  expect(bytes[28], "interlace").toBe(0);
  const channels = PNG_CHANNELS[bytes[25]];
  expect(channels, "colour type").toBeDefined();
  const idat: Buffer[] = [];
  for (let at = 8; at < bytes.length;) {
    const length = bytes.readUInt32BE(at);
    if (bytes.toString("latin1", at + 4, at + 8) === "IDAT")
      idat.push(bytes.subarray(at + 8, at + 8 + length));
    at += length + 12; // length, type and CRC around the data
  }
  const raw = inflateSync(Buffer.concat(idat));
  const stride = width * channels;
  const data = new Uint8Array(height * stride);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    for (let x = 0; x < stride; x++) {
      const a = x >= channels ? data[y * stride + x - channels] : 0;
      const b = y > 0 ? data[(y - 1) * stride + x] : 0;
      const c = x >= channels && y > 0 ? data[(y - 1) * stride + x - channels] : 0;
      const predicted = [0, a, b, (a + b) >> 1, paeth(a, b, c)][filter];
      data[y * stride + x] = (raw[y * (stride + 1) + 1 + x] + predicted) & 0xff;
    }
  }
  return { width, height, channels, data };
}

/** Every pixel of the mark, as [x, y]. */
function markPixels(pixels: Pixels, isMark: (rgba: Uint8Array) => boolean): [number, number][] {
  const found: [number, number][] = [];
  for (let y = 0; y < pixels.height; y++) {
    for (let x = 0; x < pixels.width; x++) {
      const at = (y * pixels.width + x) * pixels.channels;
      if (isMark(pixels.data.subarray(at, at + pixels.channels))) found.push([x, y]);
    }
  }
  return found;
}

function boundingBox(points: [number, number][]): Box {
  const xs = points.map(([x]) => x);
  const ys = points.map(([, y]) => y);
  return { left: Math.min(...xs), top: Math.min(...ys), right: Math.max(...xs), bottom: Math.max(...ys) };
}

function icoPng(ico: Buffer): Buffer {
  const entry = ico.subarray(ICO_HEADER_BYTES, ICO_HEADER_BYTES + ICO_ENTRY_BYTES);
  const offset = entry.readUInt32LE(12);
  return ico.subarray(offset, offset + entry.readUInt32LE(8));
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

  it("favicon.ico shows the whole mark, centred, about 0.85 of the box wide", () => {
    const pixels = decodePng(icoPng(publicFile("favicon.ico")));
    const box = boundingBox(markPixels(pixels, (rgba) => rgba[3] > 0));
    const last = FAVICON_PX - 1;
    // A clear pixel on every edge: nothing of the mark is cut off.
    expect(box.left).toBeGreaterThan(0);
    expect(box.top).toBeGreaterThan(0);
    expect(box.right).toBeLessThan(last);
    expect(box.bottom).toBeLessThan(last);
    expect(Math.abs(box.left - (last - box.right)), "left and right margins").toBeLessThanOrEqual(1);
    expect(Math.abs(box.top - (last - box.bottom)), "top and bottom margins").toBeLessThanOrEqual(1);
    const span = (box.right - box.left + 1) / FAVICON_PX;
    expect(span).toBeGreaterThanOrEqual(FAVICON_MARK_SPAN.min);
    expect(span).toBeLessThanOrEqual(FAVICON_MARK_SPAN.max);
  });

  it.each(["icon-192.png", "icon-512.png"])("%s keeps the mark inside the maskable safe zone", (name) => {
    const pixels = decodePng(publicFile(name));
    const points = markPixels(pixels, (rgba) =>
      PORCELAIN_RGB.some((value, i) => Math.abs(rgba[i] - value) > BACKGROUND_TOLERANCE),
    );
    expect(points.length).toBeGreaterThan(0);
    const centre = (pixels.width - 1) / 2;
    const farthest = Math.max(...points.map(([x, y]) => Math.hypot(x - centre, y - centre)));
    expect(farthest).toBeLessThanOrEqual(MASKABLE_SAFE_RADIUS * pixels.width);
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

  it("manifest lists each launcher icon once as any and once as maskable", () => {
    // "any maskable" in one entry makes browsers show the padded maskable art as the plain icon too.
    const manifest = JSON.parse(publicFile("manifest.webmanifest").toString("utf8"));
    const entries = manifest.icons.map(
      (icon: { src: string; purpose: string }) => `${icon.src} ${icon.purpose}`,
    );
    expect(entries.sort()).toEqual([
      "/icon-192.png any",
      "/icon-192.png maskable",
      "/icon-512.png any",
      "/icon-512.png maskable",
    ]);
  });
});
