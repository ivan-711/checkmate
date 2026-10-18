import { afterEach, describe, expect, it, vi } from "vitest";

// layout.tsx reads NEXT_PUBLIC_SITE_ORIGIN when the module loads, so each case imports it afresh.
async function loadMetadata() {
  vi.resetModules();
  return (await import("./layout")).metadata;
}

describe("root metadata", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("links the web manifest and the apple touch icon", async () => {
    const metadata = await loadMetadata();
    expect(metadata.manifest).toBe("/manifest.webmanifest");
    expect(metadata.icons).toMatchObject({ apple: "/apple-touch-icon.png" });
  });

  it("resolves og:image against NEXT_PUBLIC_SITE_ORIGIN, defaulting to the local dev server", async () => {
    vi.stubEnv("NEXT_PUBLIC_SITE_ORIGIN", "");
    expect((await loadMetadata()).metadataBase?.href).toBe("http://localhost:3000/");
    vi.stubEnv("NEXT_PUBLIC_SITE_ORIGIN", "https://checkmate.example.org");
    expect((await loadMetadata()).metadataBase?.href).toBe("https://checkmate.example.org/");
  });
});
