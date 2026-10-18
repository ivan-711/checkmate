import { expect, test, type Locator, type Page } from "@playwright/test";

const LANGS = {
  EN: { toggle: "English", use: "Use this" },
  ES: { toggle: "Español", use: "Usar este" },
} as const;

async function openDesk(page: Page, language: keyof typeof LANGS = "EN") {
  await page.goto("/");
  await page.getByRole("button", { name: LANGS[language].toggle }).click();
}

async function holdAtGate(page: Page, language: keyof typeof LANGS) {
  await openDesk(page, language);
  await page.getByRole("button", { name: LANGS[language].use }).click();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("gate-card")).toBeVisible();
}

function currentStep(page: Page) {
  return page.getByTestId("story-stepper").locator('[aria-current="step"]');
}

async function expectNoOverlap(a: Locator, b: Locator) {
  const [one, two] = await Promise.all([a.boundingBox(), b.boundingBox()]);
  expect(one).not.toBeNull();
  expect(two).not.toBeNull();
  const separate =
    one!.x + one!.width <= two!.x ||
    two!.x + two!.width <= one!.x ||
    one!.y + one!.height <= two!.y ||
    two!.y + two!.height <= one!.y;
  expect(separate).toBe(true);
}

function pageMeasurements(page: Page) {
  return page.evaluate(() => ({
    sideways: document.documentElement.scrollWidth - innerWidth,
    scrollY: window.scrollY,
  }));
}

test("the story follows check-in, gate, compare, link and flag state", async ({ page }) => {
  await openDesk(page);
  await page.getByTestId("reset-button").click();
  await expect(page.getByTestId("reset-button")).toBeEnabled();
  await expect(currentStep(page)).toContainText("Check-in");

  await page.getByRole("button", { name: "Use this" }).click();
  await page.keyboard.press("Enter");
  await expect(currentStep(page)).toContainText("Rules gate");

  await page.getByTestId("resolve-button").click();
  await expect(page.getByTestId("approve-button")).toBeVisible();
  await expect(currentStep(page)).toContainText("Compare");

  await page.getByTestId("approve-button").click();
  await page.getByTestId("review-submit-button").click();
  await expect(currentStep(page)).toContainText("Clinician flag");
});

test("the Desk header exposes its visible command label and a sequential heading outline", async ({
  page,
}) => {
  await openDesk(page);
  const commands = page.getByRole("button", { name: /Commands/ });
  const visibleWords = (await commands.innerText()).split(/\s+/).filter(Boolean);
  const accessibleName = (await commands.getAttribute("aria-label")) ?? "";
  for (const word of visibleWords) expect(accessibleName).toContain(word);

  const levels = await page
    .locator("main h1, main h2, main h3, main h4, main h5, main h6")
    .evaluateAll((nodes) =>
      nodes
        .filter((node) => {
          const style = getComputedStyle(node);
          return style.display !== "none" && style.visibility !== "hidden";
        })
        .map((node) => Number(node.tagName.slice(1))),
    );
  expect(levels.length).toBeGreaterThan(0);
  for (let index = 0, previous = 0; index < levels.length; previous = levels[index], index += 1) {
    expect(levels[index] - previous, `heading sequence ${levels.join(" → ")}`).toBeLessThanOrEqual(1);
  }

  await commands.click();
  const ratio = await page
    .locator("[cmdk-item] kbd")
    .first()
    .evaluate((hint) => {
      const rgb = (value: string) =>
        value
          .match(/[\d.]+/g)!
          .slice(0, 3)
          .map(Number);
      const linear = (value: number) => {
        const channel = value / 255;
        return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
      };
      const luminance = (color: number[]) =>
        0.2126 * linear(color[0]) + 0.7152 * linear(color[1]) + 0.0722 * linear(color[2]);
      const style = getComputedStyle(hint);
      const foreground = rgb(style.color);
      const opacity = Number(style.opacity);
      const background = rgb(getComputedStyle(hint.parentElement!).backgroundColor);
      const painted = foreground.map(
        (channel, index) => channel * opacity + background[index] * (1 - opacity),
      );
      const [light, dark] = [luminance(painted), luminance(background)].sort((a, b) => b - a);
      return (light + 0.05) / (dark + 0.05);
    });
  expect(ratio).toBeGreaterThanOrEqual(4.5);
});

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
  { width: 1080, height: 1920 },
]) {
  for (const language of ["EN", "ES"] as const) {
    test(`Desk measurements at ${viewport.width}x${viewport.height} (${language})`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await holdAtGate(page, language);
      await page.getByTestId("resolve-button").click();
      const approve = page.getByTestId("approve-button");
      await expect(approve).toBeVisible();
      await expect
        .poll(() => page.getByTestId("gate-card").evaluate((card) => getComputedStyle(card).opacity))
        .toBe("1");

      expect(await pageMeasurements(page)).toEqual({ sideways: 0, scrollY: 0 });
      await expect(page.getByTestId("gate-card")).toBeInViewport({ ratio: 0.99 });
      await expect(approve).toBeInViewport({ ratio: 0.99 });

      const subtitle = (await page.getByTestId("stage-subtitle").boundingBox())!;
      const record = (await page.getByTestId("organism-slot").boundingBox())!;
      expect(record.y).toBeGreaterThanOrEqual(subtitle.y + subtitle.height);

      if (viewport.width === 1080) {
        await expectNoOverlap(page.getByTestId("synthetic-notice"), page.getByTestId("story-stepper"));
        await expectNoOverlap(page.getByTestId("story-stepper"), page.getByTestId("hero-provisional-badge"));
        const decision = (await page.getByTestId("decision-column").boundingBox())!;
        expect(decision.x).toBeGreaterThanOrEqual(0);
        expect(decision.x + decision.width).toBeLessThanOrEqual(viewport.width);
        expect(decision.width).toBeGreaterThanOrEqual(240);
      }
    });
  }
}

for (const width of [768, 390]) {
  test(`the Desk has no sideways scroll at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 768 ? 1024 : 844 });
    await openDesk(page);
    expect((await pageMeasurements(page)).sideways).toBe(0);
  });
}
