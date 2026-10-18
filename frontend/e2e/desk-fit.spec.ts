import { expect, test, type Page } from "@playwright/test";

// Runs against the fixture adapter. The Desk at the demo and projector sizes: the kiosk head's
// mode badge never covers the language toggle, and the decision column fits beside the record.
const SIZES = [
  { width: 1280, height: 720 },
  { width: 1366, height: 768 },
  { width: 1440, height: 900 },
];

/** How far the stage (record and decision column) scrolls sideways: 0 when it fits. */
const stageSideways = (page: Page) =>
  page.locator(".stage-body").evaluate((el) => el.scrollWidth - el.clientWidth);

for (const size of SIZES) {
  test.describe(`${size.width}x${size.height}`, () => {
    test.use({ viewport: size });

    test("the kiosk's mode badge sits clear of the language toggle", async ({ page }) => {
      await page.goto("/");
      const badge = page.getByTestId("agent-mode-badge");
      await expect(badge).toBeVisible();
      const b = (await badge.boundingBox())!;
      const lang = (await page.getByRole("group", { name: "Language" }).boundingBox())!;
      const overlaps =
        b.x < lang.x + lang.width &&
        lang.x < b.x + b.width &&
        b.y < lang.y + lang.height &&
        lang.y < b.y + b.height;
      expect(overlaps, "badge and language toggle overlap").toBe(false);
      // Nor does it reach the content under the head (the welcome, or the checklist once held).
      const next = await page.locator(".k-head + *").boundingBox();
      expect(b.y + b.height, "badge reaches the content under the head").toBeLessThanOrEqual(next!.y);
    });

    test("the decision column fits: Resolve, then Approve and Reject, fully on screen", async ({ page }) => {
      await page.goto("/");
      await expect(page.getByTestId("resolve-button")).toBeInViewport({ ratio: 1 });
      expect(await stageSideways(page), "stage scrolls sideways").toBe(0);
      await page.getByTestId("resolve-button").click();
      await expect(page.getByTestId("approve-button")).toBeInViewport({ ratio: 1 });
      await expect(page.getByTestId("reject-button")).toBeInViewport({ ratio: 1 });
      expect(await stageSideways(page), "stage scrolls sideways").toBe(0);
    });
  });
}
