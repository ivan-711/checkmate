import { defineConfig, devices } from '@playwright/test';

// The script reuses the running dev server and database (CLAUDE.md rule 4): no webServer block.
// UI origin and API origin are overridable for CI; defaults match the G16 path.
export const UI_BASE = process.env.CHECKMATE_UI_BASE ?? 'http://127.0.0.1:3000';
export const API_BASE = process.env.CHECKMATE_API_BASE ?? 'http://127.0.0.1:8000';

export default defineConfig({
  testDir: '.',
  testMatch: /.*\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: UI_BASE,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome'],
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
