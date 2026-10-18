import { afterEach, describe, expect, it, vi } from "vitest";
import { requireApiOrigin } from "../e2e/apiOrigin";

// The API-mode e2e presses Reset demo, so it must never reach the live demo by default.
describe("e2e:api API origin", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("refuses to load the API-mode Playwright config when CHECKMATE_API_ORIGIN is unset", async () => {
    vi.stubEnv("CHECKMATE_API_ORIGIN", undefined);
    await expect(import("../playwright.api.config")).rejects.toThrow(/CHECKMATE_API_ORIGIN is not set/);
  });

  it("refuses a blank origin and never falls back to the live demo's 127.0.0.1:8000", () => {
    for (const env of [{}, { CHECKMATE_API_ORIGIN: "" }, { CHECKMATE_API_ORIGIN: "  " }]) {
      expect(() => requireApiOrigin(env)).toThrow(/will not default to http:\/\/127\.0\.0\.1:8000/);
    }
  });

  it("hands an explicit origin to the API-mode build", async () => {
    vi.stubEnv("CHECKMATE_API_ORIGIN", "http://127.0.0.1:8020");
    const { default: config } = await import("../playwright.api.config");
    const server = Array.isArray(config.webServer) ? config.webServer[0] : config.webServer;
    expect(server?.env?.CHECKMATE_API_ORIGIN).toBe("http://127.0.0.1:8020");
  });
});
