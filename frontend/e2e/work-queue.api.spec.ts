import { expect, test, type Page } from "@playwright/test";

// Run by `npm run e2e:api` against the API-mode build and a running API. It presses Reset demo
// on that API; the config refuses to run unless CHECKMATE_API_ORIGIN names it.
// The queue is read-only: opening it, refocusing the window and reloading it send GETs only.
// Reset on a fresh corpus database ingests every record and can take about 40 s.
const RESET_MS = 90_000;
test.setTimeout(240_000);

function writes(page: Page): string[] {
  const seen: string[] = [];
  page.on("request", (request) => {
    const { pathname } = new URL(request.url());
    if (pathname.startsWith("/api/v1/") && request.method() !== "GET")
      seen.push(`${request.method()} ${pathname}`);
  });
  return seen;
}

async function refocus(page: Page) {
  await page.evaluate(() => {
    document.dispatchEvent(new Event("visibilitychange"));
    window.dispatchEvent(new Event("focus"));
  });
}

test("the work queue sends no POST on open, on window focus or on reload", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("app-mode-badge")).toHaveText(/LOCAL/);
  await page.getByTestId("reset-button").click();
  await expect(page.getByTestId("reset-button")).toBeEnabled({ timeout: RESET_MS });
  await page.getByTestId("resolve-button").click();
  await expect(page.getByTestId("candidate-pair")).toBeVisible({ timeout: 30_000 });

  const sent = writes(page);
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Work queue" }).click();
  // The funnel comes from the Resolve response this tab already holds.
  await expect(page.getByRole("list", { name: "Match run funnel" })).toContainText("all possible pairs");
  await expect(page.getByTestId("work-queue-row").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("work-queue-columns")).toContainText("Probability estimate");
  await refocus(page);
  await page.waitForTimeout(1_000);

  await page.reload();
  await expect(page.getByTestId("work-queue-no-funnel")).toHaveText(
    "Press Resolve identity on Case to see the match-run funnel.",
  );
  await expect(page.getByTestId("work-queue-row").first()).toBeVisible({ timeout: 30_000 });
  await refocus(page);
  await page.waitForTimeout(1_000);

  await page.getByTestId("work-queue-row").last().click();
  await expect(page.getByTestId("candidate-pair")).toBeVisible({ timeout: 30_000 });
  expect(sent).toEqual([]);
});
