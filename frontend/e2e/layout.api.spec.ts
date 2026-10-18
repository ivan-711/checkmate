import { expect, test, type Page } from "@playwright/test";

// Run by `npm run e2e:api` against the API-mode build and a running API. It presses Reset demo
// on that API; the config refuses to run unless CHECKMATE_API_ORIGIN names it.
// UI audit lane D: on a landscape screen the Case and FrontDesk panes scroll on their own, so the
// page never scrolls and the demo's key moments stay in view; a portrait kiosk shows no staff pane.
// Reset on a fresh corpus database ingests every record and can take about 40 s.
const RESET_MS = 90_000;
test.setTimeout(240_000);

const LANDSCAPE = [
  { width: 1280, height: 720 },
  { width: 1366, height: 768 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
];
const PORTRAIT = [
  { width: 768, height: 1024 },
  { width: 390, height: 844 },
];

/** The page itself: no horizontal scroll, and (on a landscape desktop) no vertical scroll either. */
function pageScroll(page: Page) {
  return page.evaluate(() => {
    const root = document.documentElement;
    return {
      x: root.scrollWidth - root.clientWidth,
      y: root.scrollHeight - root.clientHeight,
      scrollY: window.scrollY,
    };
  });
}

/** Waits for the reset itself: right after the click the button can still read enabled. */
async function reset(page: Page) {
  const done = page.waitForResponse(
    (r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/sessions",
    { timeout: RESET_MS },
  );
  await page.getByTestId("reset-button").click();
  await done;
  await expect(page.getByTestId("reset-button")).toBeEnabled({ timeout: RESET_MS });
}

/** Reset, then send the demo line: the gate denies the new chart and hands it to a registrar. */
async function checkIn(page: Page) {
  await page.goto("/frontdesk");
  await expect(page.getByTestId("agent-mode-badge")).toBeVisible({ timeout: 30_000 });
  await reset(page);
  await page.getByRole("button", { name: "Use this" }).click();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("gate-card")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("registrar-held")).toHaveCount(1, { timeout: 30_000 });
}

for (const size of PORTRAIT) {
  test.describe(`${size.width}x${size.height} portrait`, () => {
    test.use({ viewport: size });

    test("FrontDesk: the patient-facing kiosk shows no staff pane", async ({ page }) => {
      await checkIn(page);
      await expect(page.getByTestId("registrar-held")).toBeHidden();
      await expect(page.getByRole("heading", { name: /Registrar workspace/ })).toBeHidden();
      expect((await pageScroll(page)).x).toBe(0);
    });
  });
}

test.describe("1024x768 landscape, stacked", () => {
  test.use({ viewport: { width: 1024, height: 768 } });

  test("FrontDesk: a landscape screen below the side-by-side width still shows the staff pane", async ({
    page,
  }) => {
    await checkIn(page);
    await expect(page.getByTestId("registrar-held")).toBeVisible();
  });
});

for (const size of LANDSCAPE) {
  test.describe(`${size.width}x${size.height}`, () => {
    test.use({ viewport: size });

    test("FrontDesk: kiosk and registrar panes scroll on their own; the page does not", async ({ page }) => {
      await checkIn(page);
      // The new gate card scrolls fully into view inside the kiosk pane; the page stays put.
      await expect(page.getByTestId("gate-card")).toBeInViewport({ ratio: 1 });
      expect(await pageScroll(page)).toEqual({ x: 0, y: 0, scrollY: 0 });

      // Keyboard focus on the registrar's Approve scrolls the registrar pane, not the kiosk.
      const approve = page.getByTestId("approve-button").first();
      await approve.focus();
      await expect(approve).toBeInViewport({ ratio: 1 });
      await expect(page.getByTestId("gate-card")).toBeInViewport();

      // The latest kiosk message is reachable inside the kiosk pane.
      const latest = page.getByRole("region", { name: "Check-in conversation" }).getByRole("listitem").last();
      await latest.scrollIntoViewIfNeeded();
      await expect(latest).toBeInViewport();
      await expect(approve).toBeInViewport({ ratio: 1 });
      expect(await pageScroll(page)).toEqual({ x: 0, y: 0, scrollY: 0 });
    });
  });
}

// Lane B owns the constructed-scenario chip and is fixing its tooltip, which is laid out while
// hidden and widens the page. Un-fixme once that fix is on main.
test.describe("constructed-scenario tooltip", () => {
  test.fixme(true, "needs lane B's ConstructedChip fix (UI audit #9)");

  for (const size of [...PORTRAIT, ...LANDSCAPE]) {
    test(`never scrolls FrontDesk sideways at ${size.width}x${size.height}`, async ({ page }) => {
      await page.setViewportSize(size);
      await page.goto("/frontdesk");
      await expect(page.getByTestId("agent-mode-badge")).toBeVisible({ timeout: 30_000 });
      // Before the first turn the kiosk's suggestion row carries a chip.
      expect((await pageScroll(page)).x).toBe(0);
      if (size.width < size.height) return;
      await checkIn(page);
      const staff = page.getByRole("region", { name: /Registrar workspace/ });
      await staff.getByTestId("constructed-scenario-chip").first().hover();
      await expect(staff.getByRole("tooltip").first()).toBeVisible();
      expect(await staff.evaluate((pane) => pane.scrollWidth - pane.clientWidth)).toBe(0);
      expect((await pageScroll(page)).x).toBe(0);
    });
  }
});

// Last, so the file leaves the API as the Case path does (the next spec presses Reset again).
for (const size of LANDSCAPE) {
  test.describe(`${size.width}x${size.height}`, () => {
    test.use({ viewport: size });

    test("Case: Approve sits in view beside the evidence, and the flag card is in view after Approve", async ({
      page,
    }) => {
      await page.goto("/");
      await expect(page.getByTestId("app-mode-badge")).toHaveText(/LOCAL/);
      await reset(page);
      await expect(page.getByTestId("source-card")).toHaveCount(2, { timeout: RESET_MS });
      await page.getByTestId("resolve-button").click();
      await expect(page.getByTestId("candidate-pair")).toBeVisible({ timeout: 30_000 });

      await expect(page.getByTestId("evidence-rail")).toBeInViewport();
      await expect(page.getByTestId("approve-button")).toBeInViewport({ ratio: 1 });
      await expect(page.getByTestId("reject-button")).toBeInViewport({ ratio: 1 });
      expect(await pageScroll(page)).toEqual({ x: 0, y: 0, scrollY: 0 });

      await page.getByTestId("approve-button").click();
      await expect(page.getByTestId("review-submit-button")).toBeInViewport({ ratio: 1 });
      await page.getByTestId("review-submit-button").click();
      await expect(page.getByTestId("golden-record")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId("flag-card")).toBeInViewport({ ratio: 1 });
      // Focus still lands on the combined record's heading (DESIGN.md, Focus).
      await expect(page.getByRole("heading", { name: "Golden record" })).toBeFocused();
      expect(await pageScroll(page)).toEqual({ x: 0, y: 0, scrollY: 0 });
    });
  });
}
