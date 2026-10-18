import { expect, test, type Locator, type Page } from "@playwright/test";

// Run by `npm run e2e:api` against the API-mode build and a running API. It presses Reset demo
// on that API; the config refuses to run unless CHECKMATE_API_ORIGIN names it.
// The Desk (CONCEPT.md §3): the kiosk and the registrar's stage share one screen. At every size the
// page never scrolls sideways, nor does any pane, with a chip's tooltip open or closed; on a
// landscape screen the page does not scroll at all and the demo's key moments stay in view.
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

/** How far the page or any scrolling pane scrolls sideways: 0 when nothing does. */
function sideways(page: Page) {
  return page.evaluate(() => {
    const root = document.documentElement;
    const panes = [...document.querySelectorAll<HTMLElement>("body *")]
      .filter((el) => ["auto", "scroll"].includes(getComputedStyle(el).overflowX))
      .map((el) => el.scrollWidth - el.clientWidth);
    return Math.max(root.scrollWidth - root.clientWidth, ...panes);
  });
}

/** Opens each chip tooltip on screen in turn; none may make the page or a pane scroll sideways. */
async function openEachTooltip(page: Page) {
  for (const chip of await page.getByTestId("constructed-scenario-chip").all()) {
    if (!(await chip.isVisible())) continue; // a pane this size does not show
    await chip.hover();
    await expect(chip.locator('[role="tooltip"]')).toBeVisible();
    expect(await sideways(page), "with a tooltip open").toBe(0);
  }
}

/** Whether an element sits fully inside the visible part of the pane that scrolls it (the window
 * where no pane scrolls) and inside the window. */
function shownInPane(locator: Locator) {
  return locator.evaluate((el) => {
    let pane = el.parentElement;
    while (pane && !["auto", "scroll"].includes(getComputedStyle(pane).overflowY)) pane = pane.parentElement;
    const box = el.getBoundingClientRect();
    const port = pane?.getBoundingClientRect() ?? { top: 0, bottom: window.innerHeight };
    const inside = (top: number, bottom: number) => box.top >= top - 1 && box.bottom <= bottom + 1;
    return inside(port.top, port.bottom) && inside(0, window.innerHeight);
  });
}

/** Waits for the reset itself: right after the click the button can still read enabled. */
async function reset(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("app-mode-badge")).toHaveAttribute("data-mode", "LOCAL");
  const done = page.waitForResponse(
    (r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/sessions",
    { timeout: RESET_MS },
  );
  await page.getByTestId("reset-button").click();
  await done;
  await expect(page.getByTestId("source-card")).toHaveCount(2, { timeout: RESET_MS });
}

/** Sends the demo line: the gate denies the new chart and the Desk holds the check-in. */
async function checkIn(page: Page, language: "EN" | "ES" = "EN") {
  if (language === "ES") {
    // The toggle starts a new check-in in Spanish; the demo line goes in once it exists.
    const started = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        new URL(r.url()).pathname === "/api/v1/intake-sessions" &&
        r.request().postDataJSON()?.language === "ES",
      { timeout: 30_000 },
    );
    await page.getByRole("button", { name: "Español" }).click();
    await started;
  }
  await page
    .getByRole("button", { name: language === "ES" ? "Usar este" : "Use this" })
    .first()
    .click({ timeout: 30_000 });
  await page.getByTestId("kiosk-send").click();
  await expect(page.getByTestId("gate-card")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('[data-pane="held"]')).toBeVisible({ timeout: 30_000 });
}

// Long enough for a smooth scroll or the morph to finish, so a check sees where things come to rest.
const SETTLE_MS = 1_500;

for (const size of [...PORTRAIT, ...LANDSCAPE]) {
  test.describe(`${size.width}x${size.height}`, () => {
    test.use({ viewport: size });

    test("Desk: no sideways scroll on the page or in a pane, closed or open, before and after a check-in", async ({
      page,
    }) => {
      await reset(page);
      expect(await sideways(page), "before a check-in").toBe(0);
      await openEachTooltip(page);
      await checkIn(page);
      expect(await sideways(page), "after a check-in").toBe(0);
      await openEachTooltip(page);
    });
  });
}

for (const size of LANDSCAPE) {
  test.describe(`${size.width}x${size.height}`, () => {
    test.use({ viewport: size });

    test("Desk (demo order): gate card and Resolve, then Approve, then the flag and the focus stay in view; the page never scrolls", async ({
      page,
    }) => {
      await reset(page);
      await checkIn(page);
      await expect.poll(() => shownInPane(page.getByTestId("gate-card"))).toBe(true);
      await expect(page.getByTestId("resolve-button")).toBeInViewport({ ratio: 1 });
      expect(await pageScroll(page)).toEqual({ x: 0, y: 0, scrollY: 0 });

      await page.getByTestId("resolve-button").click();
      await expect(page.getByTestId("candidate-pair")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId("evidence-rail")).toBeInViewport();
      await expect(page.getByTestId("approve-button")).toBeInViewport({ ratio: 1 });
      await expect(page.getByTestId("reject-button")).toBeInViewport({ ratio: 1 });

      await page.getByTestId("approve-button").click();
      await expect(page.getByTestId("attach-checkin")).toBeChecked();
      await expect(page.getByTestId("review-submit-button")).toBeInViewport({ ratio: 1 });
      await page.getByTestId("review-submit-button").click();
      await expect(page.getByTestId("flag-card")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByRole("heading", { name: "Flagged for clinician review" })).toBeFocused();
      await page.waitForTimeout(SETTLE_MS);
      await expect.poll(() => shownInPane(page.locator(":focus"))).toBe(true);
      expect(await pageScroll(page)).toEqual({ x: 0, y: 0, scrollY: 0 });
      expect(await sideways(page), "after Approve").toBe(0);
      await openEachTooltip(page);
    });
  });
}

for (const size of [LANDSCAPE[0], LANDSCAPE[2]]) {
  test.describe(`${size.width}x${size.height}`, () => {
    test.use({ viewport: size });

    test("Desk (ES): once the gate fires, the gate card and Resolve are both in view", async ({ page }) => {
      await reset(page);
      await checkIn(page, "ES");
      await expect.poll(() => shownInPane(page.getByTestId("gate-card"))).toBe(true);
      await expect(page.getByTestId("resolve-button")).toBeInViewport({ ratio: 1 });
      expect(await pageScroll(page)).toEqual({ x: 0, y: 0, scrollY: 0 });
    });
  });
}

for (const size of [{ width: 1440, height: 900 }, { width: 1512, height: 982 }, LANDSCAPE[0]]) {
  test.describe(`${size.width}x${size.height}`, () => {
    test.use({ viewport: size });

    test("Desk: the crosswalk tabs stay inside the record, the check-in's id short with the full id in its tooltip", async ({
      page,
    }) => {
      await reset(page);
      await checkIn(page);
      await page.getByTestId("resolve-button").click();
      await page.getByTestId("approve-button").click({ timeout: 30_000 });
      await expect(page.getByTestId("attach-checkin")).toBeChecked();
      await page.getByTestId("review-submit-button").click();
      const golden = page.getByTestId("golden-record");
      await expect(golden).toBeVisible({ timeout: 30_000 });
      const intake = page.locator('[data-testid="crosswalk-chip"][data-source-system="FRONTDESK_INTAKE"]');
      await expect(intake).toHaveCount(1, { timeout: 30_000 });
      await expect(intake.locator("code")).toHaveText(/^[0-9a-f]{8}$/);
      await expect(intake).toHaveAttribute("title", /^Source record \S{20,}$/);

      const record = (await golden.boundingBox())!;
      const history = (await page.getByTestId("timeline").boundingBox())!;
      for (const chip of await page.getByTestId("crosswalk-chip").all()) {
        const box = (await chip.boundingBox())!;
        expect(box.height, "a tab is one line").toBeLessThan(48);
        expect(box.x + box.width, "tab inside the record").toBeLessThanOrEqual(record.x + record.width + 1);
        expect(box.x + box.width, "tab clear of History").toBeLessThanOrEqual(history.x);
      }
      expect(await sideways(page), "after Approve").toBe(0);
    });
  });
}
