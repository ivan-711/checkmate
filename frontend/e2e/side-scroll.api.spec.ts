import { expect, test, type Page } from "@playwright/test";

// Run by `npm run e2e:api` against the API-mode build and an API in REPLAY with the corpus hero.
// It presses Reset demo on that API; the config refuses to run unless CHECKMATE_API_ORIGIN names it.
// The hero shows constructed-scenario chips on the kiosk's suggested check-in, the registrar's
// source cards and the flag summary. No tooltip, open or closed, may add sideways scroll.
const RESET_MS = 90_000;
test.setTimeout(240_000);

const VIEWPORTS = [
  { width: 1280, height: 720 },
  { width: 1440, height: 900 },
  { width: 768, height: 1024 },
  { width: 390, height: 844 },
];
const STAFF_VIEWPORT = { width: 1280, height: 720 };

const sideScroll = (page: Page) =>
  page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);

async function expectEveryOpenTooltipInside(page: Page, width: number) {
  for (const chip of await page.getByTestId("constructed-scenario-chip").all()) {
    if (!(await chip.isVisible())) continue; // a pane this size does not show
    await chip.hover();
    const tip = chip.locator('[role="tooltip"]');
    await expect(tip).toBeVisible();
    const box = (await tip.boundingBox())!;
    expect(box.x, "tooltip starts inside the window").toBeGreaterThanOrEqual(0);
    expect(box.x + box.width, "tooltip ends inside the window").toBeLessThanOrEqual(width);
    expect(await sideScroll(page), "with a tooltip open").toBeLessThanOrEqual(0);
  }
}

for (const viewport of VIEWPORTS) {
  test(`FrontDesk at ${viewport.width}x${viewport.height}: no sideways scroll before a turn, after a turn, after Approve, with each chip open`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto("/frontdesk");
    const reset = page.waitForResponse(
      (r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/sessions",
      { timeout: RESET_MS },
    );
    await page.getByTestId("reset-button").click();
    await reset;
    await expect(page.getByRole("button", { name: "Use this" })).toBeEnabled({ timeout: RESET_MS });
    expect(await sideScroll(page), "before a turn").toBeLessThanOrEqual(0);
    await expectEveryOpenTooltipInside(page, viewport.width);

    await page.getByRole("button", { name: "Use this" }).click();
    await page.getByTestId("kiosk-send").click();
    await expect(page.getByTestId("gate-card")).toBeVisible({ timeout: 30_000 });
    const held = page.getByTestId("registrar-held");
    await expect(held).toContainText("Held check-ins (2)");
    expect(await sideScroll(page), "after a turn").toBeLessThanOrEqual(0);
    await expectEveryOpenTooltipInside(page, viewport.width);

    // The staff pane is a landscape surface: approve both held pairs there, then look again.
    await page.setViewportSize(STAFF_VIEWPORT);
    for (let i = 0; i < 2; i++) {
      await held.getByTestId("approve-button").first().click();
      await held.getByTestId("review-submit-button").click();
      await expect(held.getByText(/Approved by /)).toHaveCount(i + 1, { timeout: 30_000 });
    }
    await expect(page.getByTestId("registrar-flag-summary")).toBeVisible();
    await page.setViewportSize(viewport);
    expect(await sideScroll(page), "after Approve").toBeLessThanOrEqual(0);
    await expectEveryOpenTooltipInside(page, viewport.width);
  });
}
