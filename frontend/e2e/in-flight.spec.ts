import { expect, test, type Route } from "@playwright/test";

// Runs against the API-mode build (NEXT_PUBLIC_CHECKMATE_SOURCE=api) and a running API: the
// match-run response is held open with a route so the screen can be checked mid-run. The fixture
// adapter resolves without a request, so the test skips there.
test("Approve, Reject and Resolve are disabled while a match run is in flight", async ({ page }) => {
  await page.goto("/");
  const mode = page.getByTestId("app-mode-badge");
  await expect(mode).toBeVisible();
  test.skip(!/LOCAL/.test((await mode.textContent()) ?? ""), "needs the API-mode build and a running API");

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
