import { describe, expect, it } from "vitest";
import { DEFAULT_SITE_ORIGIN, siteOrigin } from "./siteOrigin";

describe("siteOrigin", () => {
  it("defaults to the local dev server when NEXT_PUBLIC_SITE_ORIGIN is unset or blank", () => {
    expect(DEFAULT_SITE_ORIGIN).toBe("http://localhost:3000");
    expect(siteOrigin(undefined).href).toBe("http://localhost:3000/");
    expect(siteOrigin("  ").href).toBe("http://localhost:3000/");
  });

  it("uses the configured origin, so link previews point at the hosted copy", () => {
    expect(siteOrigin("https://checkmate.example.org").href).toBe("https://checkmate.example.org/");
    expect(new URL("/og.png", siteOrigin("https://checkmate.example.org")).href).toBe(
      "https://checkmate.example.org/og.png",
    );
  });

  it("fails the build on a value that is not a URL instead of shipping a broken og:image", () => {
    expect(() => siteOrigin("checkmate.example.org")).toThrow();
  });
});
