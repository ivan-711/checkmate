import { expect, test, type Route } from "@playwright/test";

// Run by `npm run e2e:api` (playwright.api.config.ts) against the API-mode build and a running API:
// the match-run response is held open with a route so the screen can be checked mid-run.
// It presses Reset demo on that API; the config refuses to run unless CHECKMATE_API_ORIGIN names it.
test("Resolve holds while its match run is in flight; Approve and Reject hold while a Reset is in flight", async ({
  page,
}) => {
  await page.goto("/");
  // Fails, never skips, if the build is not in API mode.
  await expect(page.getByTestId("app-mode-badge")).toHaveAttribute("data-mode", "LOCAL");

  // Wait for the reset itself: right after the click the button can still read enabled, and a
  // Resolve pressed during the reset is held, so no match run would start.
  await Promise.all([
    page.waitForResponse(
      (r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/sessions",
      { timeout: 60_000 },
    ),
    page.getByTestId("reset-button").click(),
  ]);
  await expect(page.getByTestId("reset-button")).toBeEnabled({ timeout: 30_000 });

  // The first Resolve in flight: the button holds and says so until the run answers. The Desk
  // offers no Resolve while the pair is under review (L4), so this is the match run a click can start.
  let held: Route | null = null;
  await page.route("**/api/v1/match-runs", (route) => {
    held = route;
  });
  await page.getByTestId("resolve-button").click();
  await expect.poll(() => held !== null).toBe(true);
  await expect(page.getByTestId("resolve-button")).toBeDisabled();
  await expect(page.getByTestId("resolve-button")).toContainText("Resolving…");
  await held!.continue();
  await page.unroute("**/api/v1/match-runs");
  await expect(page.getByTestId("candidate-pair")).toBeVisible({ timeout: 30_000 });
  for (const id of ["approve-button", "reject-button"]) {
    await expect(page.getByTestId(id)).toBeEnabled({ timeout: 30_000 });
  }

  // A Reset in flight while the pair is under review: no decision can be taken on a pair that is
  // about to change.
  let reset: Route | null = null;
  await page.route("**/api/v1/sessions", (route) => {
    reset = route;
  });
  await page.getByTestId("reset-button").click();
  await expect.poll(() => reset !== null).toBe(true);
  for (const id of ["approve-button", "reject-button"]) {
    await expect(page.getByTestId(id)).toBeDisabled();
  }
  await expect(page.getByTestId("candidate-pair")).toHaveAttribute("aria-busy", "true");
  await reset!.continue();
  await page.unroute("**/api/v1/sessions");
  await expect(page.getByTestId("resolve-button")).toBeEnabled({ timeout: 60_000 });
});
