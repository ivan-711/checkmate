// Renders the brand files under public/ from src/app/icon.svg with the Chromium that
// @playwright/test already installs. No image service, no key, no network: the fonts are read from
// node_modules (the @fontsource packages CONCEPT.md §9 names) or from CHECKMATE_FONT_DIR.
//
//   node scripts/render-assets.mjs
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const ROOT = path.resolve(fileURLToPath(new URL(".", import.meta.url)), "..");
const MARK_SVG = path.join(ROOT, "src/app/icon.svg");
const PUBLIC_DIR = path.join(ROOT, "public");
const OG_TEMPLATE = path.join(ROOT, "scripts/assets/og.html");

// CONCEPT.md §4. Declared once here because the render runs outside the app's stylesheet.
const TOKENS = { mulberry: "#8C1D7E", porcelain: "#F5F3F4", ink: "#1B1419", ink2: "#5C5259" };

// icon.svg draws the disc (radius 9) in a viewBox 22 units wide, so the disc is 18/22 of the box.
const DISC_PER_BOX = 18 / 22;
// Launcher icons keep the disc inside the maskable safe zone (the central 80 % circle).
const LAUNCHER_DISC_FRACTION = 0.62;
const LAUNCHER_ICONS = [
  { file: "icon-192.png", px: 192 },
  { file: "icon-512.png", px: 512 },
  { file: "apple-touch-icon.png", px: 180 },
];
// The tab icon has no background, so the disc can nearly fill the box.
const FAVICON = { file: "favicon.ico", px: 32, discFraction: 0.94 };
const OG = { file: "og.png", width: 1200, height: 630 };

// Variable fonts from the @fontsource packages CONCEPT.md §9 names (the "standard" file carries
// every axis). L1 adds the packages; until then CHECKMATE_FONT_DIR may hold the same two files.
// They go into the page as data: URLs because Chromium will not fetch file:// fonts into a page
// built with setContent.
const FONTS = {
  fontDisplay: [
    "@fontsource-variable/bricolage-grotesque",
    "bricolage-grotesque-latin-standard-normal.woff2",
  ],
  fontText: ["@fontsource-variable/instrument-sans", "instrument-sans-latin-standard-normal.woff2"],
};

// ICO container: a 6-byte header, one 16-byte directory entry, then a PNG (valid since Vista).
const ICO_HEADER_BYTES = 6;
const ICO_ENTRY_BYTES = 16;
const ICO_PNG_BITS_PER_PIXEL = 32;

function fontDataUrl([pkg, file]) {
  const candidates = [path.join(ROOT, "node_modules", pkg, "files", file)];
  if (process.env.CHECKMATE_FONT_DIR) candidates.push(path.join(process.env.CHECKMATE_FONT_DIR, file));
  const found = candidates.find((p) => existsSync(p));
  if (!found) {
    throw new Error(`${file} not found. Install ${pkg} or set CHECKMATE_FONT_DIR to a folder holding it.`);
  }
  return `data:font/woff2;base64,${readFileSync(found).toString("base64")}`;
}

function fill(template, values) {
  return template.replace(/\{\{(\w+)\}\}/g, (_, key) => {
    if (!(key in values)) throw new Error(`template has no value for {{${key}}}`);
    return values[key];
  });
}

/** The mark alone, centred in a square box, on a background or on nothing. */
function iconPage(svg, px, discFraction, background) {
  const size = Math.round((px * discFraction) / DISC_PER_BOX);
  const sized = svg.replace("<svg ", `<svg width="${size}" height="${size}" `);
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    html, body { margin: 0; }
    body { width: ${px}px; height: ${px}px; display: grid; place-items: center; background: ${background}; }
  </style></head><body>${sized}</body></html>`;
}

function icoFromPng(png, px) {
  const header = Buffer.alloc(ICO_HEADER_BYTES);
  header.writeUInt16LE(0, 0); // reserved
  header.writeUInt16LE(1, 2); // type: icon
  header.writeUInt16LE(1, 4); // one image
  const entry = Buffer.alloc(ICO_ENTRY_BYTES);
  entry[0] = px;
  entry[1] = px;
  entry[2] = 0; // no palette
  entry[3] = 0; // reserved
  entry.writeUInt16LE(1, 4); // colour planes
  entry.writeUInt16LE(ICO_PNG_BITS_PER_PIXEL, 6);
  entry.writeUInt32LE(png.length, 8);
  entry.writeUInt32LE(ICO_HEADER_BYTES + ICO_ENTRY_BYTES, 12);
  return Buffer.concat([header, entry, png]);
}

async function shoot(browser, html, width, height, { transparent = false } = {}) {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
  try {
    await page.setContent(html);
    await page.evaluate(() => document.fonts.ready);
    return await page.screenshot({ type: "png", omitBackground: transparent });
  } finally {
    await page.close();
  }
}

async function main() {
  const svg = readFileSync(MARK_SVG, "utf8").trim();
  const browser = await chromium.launch();
  const written = [];
  try {
    for (const { file, px } of LAUNCHER_ICONS) {
      const png = await shoot(browser, iconPage(svg, px, LAUNCHER_DISC_FRACTION, TOKENS.porcelain), px, px);
      writeFileSync(path.join(PUBLIC_DIR, file), png);
      written.push(file);
    }

    const faviconPng = await shoot(
      browser,
      iconPage(svg, FAVICON.px, FAVICON.discFraction, "transparent"),
      FAVICON.px,
      FAVICON.px,
      { transparent: true },
    );
    writeFileSync(path.join(PUBLIC_DIR, FAVICON.file), icoFromPng(faviconPng, FAVICON.px));
    written.push(FAVICON.file);

    const og = fill(readFileSync(OG_TEMPLATE, "utf8"), {
      ...TOKENS,
      width: String(OG.width),
      height: String(OG.height),
      fontDisplay: fontDataUrl(FONTS.fontDisplay),
      fontText: fontDataUrl(FONTS.fontText),
      mark: svg,
    });
    writeFileSync(path.join(PUBLIC_DIR, OG.file), await shoot(browser, og, OG.width, OG.height));
    written.push(OG.file);
  } finally {
    await browser.close();
  }
  console.log(`rendered ${written.join(", ")} into ${path.relative(ROOT, PUBLIC_DIR)}/`);
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
