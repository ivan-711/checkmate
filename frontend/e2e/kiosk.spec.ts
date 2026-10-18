import { expect, test, type Page } from "@playwright/test";

// The living-record kiosk on the Desk (BUILD-SPEC L2 row). Fixture mode (the default data source).
const LANGS = {
  en: { toggle: "English", use: "Use this" },
  es: { toggle: "Español", use: "Usar este" },
} as const;

async function heldCheckIn(page: Page, lang: keyof typeof LANGS) {
  await page.goto("/");
  await page.getByRole("button", { name: LANGS[lang].toggle }).click();
  await expect(page.getByTestId("kiosk")).toHaveAttribute("lang", lang);
  await page.getByRole("button", { name: LANGS[lang].use }).click();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("kiosk")).toHaveAttribute("data-k", "held");
}

/** The gate card's box inside the kiosk's scrolling middle and inside the window, the window's
 * scroll, and whether the page scrolls sideways. */
function gateFit(page: Page) {
  return page.evaluate(() => {
    const card = document.querySelector('[data-testid="gate-card"]')!.getBoundingClientRect();
    const swap = document.querySelector(".k-swap")!.getBoundingClientRect();
    const inside = (outer: { top: number; bottom: number; left: number; right: number }) =>
      card.top >= outer.top - 0.5 &&
      card.bottom <= outer.bottom + 0.5 &&
      card.left >= outer.left - 0.5 &&
      card.right <= outer.right + 0.5;
    return {
      inSwap: inside(swap),
      inWindow: inside({ top: 0, left: 0, bottom: innerHeight, right: innerWidth }),
      scrollY: window.scrollY,
      sideways: document.documentElement.scrollWidth > innerWidth,
    };
  });
}

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
]) {
  for (const lang of ["en", "es"] as const) {
    test(`the gate card is fully in view, the window never scrolls, at ${viewport.width}x${viewport.height} (${lang})`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await heldCheckIn(page, lang);
      await expect(page.getByTestId("gate-card")).toBeVisible();
      // The drop-in and the stagger settle first; the card's final box is what a judge sees.
      await expect
        .poll(() => gateFit(page))
        .toEqual({ inSwap: true, inWindow: true, scrollY: 0, sideways: false });
    });
  }
}

test("the kiosk walks idle, held, done as the registrar approves on the stage", async ({ page }) => {
  await page.goto("/");
  const kiosk = page.getByTestId("kiosk");
  await expect(kiosk).toHaveAttribute("data-k", "idle");
  await page.getByRole("button", { name: "Use this" }).click();
  await page.keyboard.press("Enter");
  await expect(kiosk).toHaveAttribute("data-k", "held");
  // The demo line runs once per check-in.
  await expect(page.getByRole("button", { name: "Use this" })).toHaveCount(0);
  await page.getByTestId("resolve-button").click();
  await page.getByTestId("approve-button").click();
  await page.getByTestId("review-submit-button").click();
  await expect(kiosk).toHaveAttribute("data-k", "done");
  await expect(kiosk).toContainText("You’re checked in");
  await expect(page.locator('[data-kiosk="done"]')).toHaveCount(1);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
});

test("the language toggle flips the kiosk's lang attribute both ways", async ({ page }) => {
  await page.goto("/");
  const kiosk = page.getByTestId("kiosk");
  await expect(kiosk).toHaveAttribute("lang", "en");
  await page.getByRole("button", { name: "Español" }).click();
  await expect(kiosk).toHaveAttribute("lang", "es");
  await expect(page.getByRole("button", { name: "Español" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "English" }).click();
  await expect(kiosk).toHaveAttribute("lang", "en");
});

test("under reduced motion the gate card arrives as a still", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await heldCheckIn(page, "en");
  const motion = await page.locator(".k-gate").evaluate((el) => {
    const style = getComputedStyle(el);
    return { animation: style.animationName, opacity: style.opacity, transform: style.transform };
  });
  expect(motion).toEqual({ animation: "none", opacity: "1", transform: "none" });
});

// PC audit (REBOOT-0731 item 5): on a portrait kiosk screen the demo line reads as lines of
// text, not one word per line.
test("at 1080x1920 the demo line wraps as prose, one line holding several words", async ({ page }) => {
  await page.setViewportSize({ width: 1080, height: 1920 });
  await page.goto("/");
  const q = page.locator(".k-demo-q");
  await expect(q).toBeVisible();
  const { lines, words, width } = await q.evaluate((el) => {
    const range = document.createRange();
    range.selectNodeContents(el);
    const tops = new Set([...range.getClientRects()].map((r) => Math.round(r.top)));
    return {
      lines: tops.size,
      words: el.textContent!.trim().split(/\s+/).length,
      width: el.getBoundingClientRect().width,
    };
  });
  expect(width).toBeGreaterThan(240);
  // The fixture line has long placeholder tokens; prose still averages well over two words a line.
  expect(words / lines).toBeGreaterThanOrEqual(2.5);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

// PC audit (REBOOT-0731 item 4): nothing at the kiosk's top edge is cut off by its rounded frame.
for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
  { width: 1080, height: 1920 },
]) {
  test(`the kiosk head is not clipped at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto("/");
    const clipped = await page.getByTestId("kiosk").evaluate((root) => {
      const frame = root.getBoundingClientRect();
      return [...root.querySelectorAll(".k-head *")]
        .filter((el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent!.trim()))
        .filter((el) => {
          const r = el.getBoundingClientRect();
          return (
            r.left < frame.left ||
            r.right > frame.right ||
            r.top < frame.top ||
            el.scrollWidth > el.clientWidth + 1
          );
        })
        .map((el) => el.textContent);
    });
    expect(clipped).toEqual([]);
  });
}
