// Copies the vitallens browser bundle and its face-detection model into public/vendor/vitallens
// (gitignored). The kiosk loads the bundle from this origin with a native import, never through
// webpack, so the bundle's import.meta.url points here and the model loads from here as well.
// Served from anywhere else, the library falls back to fetching the model from a public CDN.
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dist = join(root, "node_modules", "vitallens", "dist");
const out = join(root, "public", "vendor", "vitallens");

if (process.env.NEXT_PUBLIC_VITALS !== "on") {
  rmSync(out, { recursive: true, force: true });
  console.log("vitallens: flag is off; browser bundle and model were not copied");
  process.exit(0);
}

const bundle = join(dist, "vitallens.browser.js");
if (!existsSync(bundle)) {
  throw new Error(`vitallens is not installed (${bundle} is missing); run npm ci in frontend/`);
}
rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
cpSync(bundle, join(out, "vitallens.browser.js"));
cpSync(join(dist, "models"), join(out, "models"), { recursive: true });
console.log(`vitallens: copied the browser bundle and model to ${out}`);
