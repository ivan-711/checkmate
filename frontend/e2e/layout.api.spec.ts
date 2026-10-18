import { expect, test, type Locator, type Page } from "@playwright/test";

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

/** Whether the focused element is on screen inside its pane once any smooth scroll has settled. */
const focusShown = (page: Page) => shownInPane(page.locator(":focus"));

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

/** Reset on Case, then Resolve: the hero pair waits for review. */
async function resolvedCase(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("app-mode-badge")).toHaveText(/LOCAL/);
  await reset(page);
  await expect(page.getByTestId("source-card")).toHaveCount(2, { timeout: RESET_MS });
  await page.getByTestId("resolve-button").click();
  await expect(page.getByTestId("candidate-pair")).toBeVisible({ timeout: 30_000 });
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

    test("FrontDesk: a held check-in comes into view in the staff pane, and the kiosk shows the registrar's answer", async ({
      page,
    }) => {
      await checkIn(page);
      // The first held pair's heading is brought to the top of the staff pane (or the pane is at its
      // end), and the kiosk keeps the focus.
      const staff = page.getByRole("region", { name: /Registrar workspace/ });
      // The id RegistrarPane gives the first held pair's heading.
      const heading = staff.locator("#held-heading-0");
      await expect
        .poll(() =>
          heading.evaluate((el) => {
            const pane = el.closest(".pane")!;
            const atTop = Math.abs(el.getBoundingClientRect().top - pane.getBoundingClientRect().top) <= 1;
            const atEnd = pane.scrollTop >= pane.scrollHeight - pane.clientHeight - 1;
            return atTop || atEnd;
          }),
        )
        .toBe(true);
      await expect(page.getByTestId("kiosk-composer")).toBeFocused();

      // Approve is reachable inside the staff pane's visible area.
      const approve = staff.getByTestId("approve-button").first();
      await approve.scrollIntoViewIfNeeded();
      await expect.poll(() => shownInPane(approve)).toBe(true);

      // The registrar's decision reaches the kiosk, and its line scrolls into view in the kiosk pane.
      await approve.click();
      await staff.getByTestId("review-submit-button").click();
      const confirmed = page
        .getByRole("region", { name: "Check-in conversation" })
        .getByText("Your chart is confirmed. Please wait to be called.");
      await expect(confirmed).toBeVisible({ timeout: 30_000 });
      await expect.poll(() => shownInPane(confirmed)).toBe(true);
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

    test("Case (G16 order): Approve sits in view beside the evidence; after Approve the flag card and the focus are in view", async ({
      page,
    }) => {
      await resolvedCase(page);
      await expect(page.getByTestId("evidence-rail")).toBeInViewport();
      await expect(page.getByTestId("approve-button")).toBeInViewport({ ratio: 1 });
      await expect(page.getByTestId("reject-button")).toBeInViewport({ ratio: 1 });
      expect(await pageScroll(page)).toEqual({ x: 0, y: 0, scrollY: 0 });

      // Reject first (no suppression), resolve again, then approve: the G16 path.
      await page.getByTestId("reject-button").click();
      await page.getByTestId("review-reason-select").selectOption("INSUFFICIENT_EVIDENCE");
      await page.getByTestId("review-submit-button").click();
      await expect(page.getByText(/^Rejected by/)).toBeVisible({ timeout: 30_000 });
      const rerun = page.waitForResponse(
        (r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/match-runs",
        { timeout: 30_000 },
      );
      await page.getByTestId("resolve-button").click();
      await rerun;
      await expect(page.getByTestId("approve-button")).toBeEnabled({ timeout: 30_000 });

      await page.getByTestId("approve-button").click();
      await expect(page.getByTestId("review-submit-button")).toBeInViewport({ ratio: 1 });
      await page.getByTestId("review-submit-button").click();
      await expect(page.getByTestId("golden-record")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId("flag-card")).toBeInViewport({ ratio: 1 });
      // The approval raised a flag: focus is on the flag's heading, on screen in its pane.
      await expect(page.getByRole("heading", { name: "Flagged for clinician review" })).toBeFocused();
      await expect.poll(() => focusShown(page)).toBe(true);
      await expect(page.locator('main [role="alert"]')).toHaveCount(0);
      expect(await pageScroll(page)).toEqual({ x: 0, y: 0, scrollY: 0 });
    });
  });
}

for (const size of LANDSCAPE.slice(0, 2)) {
  test.describe(`${size.width}x${size.height}`, () => {
    test.use({ viewport: size });

    test("Case: an Approve that raises no flag keeps focus on the golden record heading, on screen", async ({
      page,
    }) => {
      // The hero always flags; an empty alert list stands in for an approval the rule is silent on.
      await page.route(
        (url) => url.pathname === "/api/v1/alerts",
        (route) => route.fulfill({ json: { items: [], nextCursor: null } }),
      );
      await resolvedCase(page);
      await page.getByTestId("approve-button").click();
      await page.getByTestId("review-submit-button").click();
      await expect(page.getByTestId("golden-record")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId("flag-quiet")).toContainText("The rule did not flag this linked record");
      await expect(page.getByRole("heading", { name: "Golden record" })).toBeFocused();
      await expect.poll(() => focusShown(page)).toBe(true);
      expect(await pageScroll(page)).toEqual({ x: 0, y: 0, scrollY: 0 });
    });
  });
}
