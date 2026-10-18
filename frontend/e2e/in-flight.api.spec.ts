import { expect, test, type Route } from "@playwright/test";

// Run by `npm run e2e:api` (playwright.api.config.ts) against the API-mode build and a running API:
// the match-run response is held open with a route so the screen can be checked mid-run.
// It presses Reset demo on that API; the config refuses to run unless CHECKMATE_API_ORIGIN names it.
test("Approve, Reject and Resolve are disabled while a match run is in flight", async ({ page }) => {
  await page.goto("/");
  // Fails, never skips, if the build is not in API mode.
  await expect(page.getByTestId("app-mode-badge")).toHaveText(/LOCAL/);

  await page.getByTestId("reset-button").click();
  await expect(page.getByTestId("reset-button")).toBeEnabled({ timeout: 30_000 });
  await page.getByTestId("resolve-button").click();
  await expect(page.getByTestId("candidate-pair")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("approve-button")).toBeEnabled();

  let held: Route | null = null;
  await page.route("**/api/v1/match-runs", (route) => {
    held = route;
  });
  await page.getByTestId("resolve-button").click();
  await expect.poll(() => held !== null).toBe(true);

  for (const id of ["approve-button", "reject-button", "resolve-button"]) {
    await expect(page.getByTestId(id)).toBeDisabled();
  }
  await expect(page.getByTestId("candidate-pair")).toHaveAttribute("aria-busy", "true");

  await held!.continue();
  await page.unroute("**/api/v1/match-runs");
  for (const id of ["approve-button", "reject-button", "resolve-button"]) {
    await expect(page.getByTestId(id)).toBeEnabled({ timeout: 30_000 });
  }
  await expect(page.getByTestId("candidate-pair")).toHaveAttribute("aria-busy", "false");
});
