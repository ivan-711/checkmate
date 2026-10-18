import { afterEach, describe, expect, it, vi } from "vitest";

// layout.tsx reads NEXT_PUBLIC_SITE_ORIGIN when the module loads, so each case imports it afresh.
async function loadMetadata() {
  vi.resetModules();
  return (await import("./layout")).metadata;
}

describe("root metadata", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("links the web manifest, the apple touch icon and still the SVG tab icon", async () => {
    const metadata = await loadMetadata();
    expect(metadata.manifest).toBe("/manifest.webmanifest");
    // Once metadata.icons is set, Next drops the app/icon.svg link it would add by file convention
    // (next/dist/lib/metadata/resolve-metadata.js), so the SVG has to be named here too.
    expect(metadata.icons).toEqual({
      icon: { url: "/icon.svg", type: "image/svg+xml", sizes: "any" },
      apple: "/apple-touch-icon.png",
    });
  });

  it("resolves og:image against NEXT_PUBLIC_SITE_ORIGIN, defaulting to the local dev server", async () => {
    vi.stubEnv("NEXT_PUBLIC_SITE_ORIGIN", "");
    expect((await loadMetadata()).metadataBase?.href).toBe("http://localhost:3000/");
    vi.stubEnv("NEXT_PUBLIC_SITE_ORIGIN", "https://checkmate.example.org");
    expect((await loadMetadata()).metadataBase?.href).toBe("https://checkmate.example.org/");
  });
});
