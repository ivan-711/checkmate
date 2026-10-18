import { defineConfig, devices } from "@playwright/test";

// `npm run e2e:api`: the specs that need the real API (a request held open with page.route).
// Builds the app in API mode into its own folder and serves it on its own port; the API must
// already be running at CHECKMATE_API_ORIGIN (default http://127.0.0.1:8000).
const PORT = Number(process.env.CHECKMATE_UI_API_PORT ?? 3012);
const DIST = ".next/e2e-api";

export default defineConfig({
  testDir: "e2e",
  testMatch: "**/*.api.spec.ts",
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    viewport: { width: 1440, height: 800 },
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium-api", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 800 } } },
  ],
  webServer: {
    // next build points next-env.d.ts at the folder it built; put the tracked file back after.
    // This discards any local edit to next-env.d.ts (Next owns that file) and needs git.
    command: `npm run build && git checkout -- next-env.d.ts && npx next start -H 127.0.0.1 -p ${PORT}`,
    env: { NEXT_PUBLIC_CHECKMATE_SOURCE: "api", CHECKMATE_DIST_DIR: DIST },
    url: `http://127.0.0.1:${PORT}/`,
    reuseExistingServer: false,
    timeout: 180_000,
  },
});
