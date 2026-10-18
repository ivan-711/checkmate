import { defineConfig, devices } from "@playwright/test";

// CHECKMATE_UI_PORT lets a reviewer run the suite against a build on another port.
const PORT = Number(process.env.CHECKMATE_UI_PORT ?? 3000);

export default defineConfig({
  testDir: "e2e",
  // *.api.spec.ts need the API-mode build and a running API: playwright.api.config.ts runs them.
  testIgnore: "**/*.api.spec.ts",
  fullyParallel: false,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    viewport: { width: 1440, height: 800 },
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 800 } } },
  ],
  // Reuses a running server (the shared dev server rule); otherwise serves the production build.
  webServer: {
    command: `npm run start -- -p ${PORT}`,
    url: `http://127.0.0.1:${PORT}/`,
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
