import { expect, test } from "@playwright/test";

test("the app stays in the light theme when the system asks for dark", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/frontdesk");
  const light = await page.locator("body").evaluate((el) => getComputedStyle(el).backgroundColor);
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.locator("body")).toHaveCSS("background-color", light);
});

test("the app declares an icon the server serves, so the tab icon request never 404s", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const href = await page.locator('link[rel="icon"]').first().getAttribute("href");
  expect(href).toBeTruthy();
  const icon = await request.get(href!);
  expect(icon.status()).toBe(200);
  expect(icon.headers()["content-type"]).toMatch(/^image\//);
});

test("the header carries the synthetic-data sentence and the story stepper, and no tabs", async ({
  page,
}) => {
  await page.goto("/frontdesk");
  await expect(page).toHaveURL(/\/$/);
  const header = page.locator("header");
  await expect(header.getByText("Synthetic data. Not for clinical use.")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
  await expect(page.getByRole("tab")).toHaveCount(0);
  const steps = header.getByTestId("story-stepper").getByRole("listitem");
  await expect(steps).toHaveText([/Check-in/, /Rules gate/, /Compare/, /Link/, /Clinician flag/]);
  await expect(header.locator('[aria-current="step"]')).toHaveCount(1);
});

for (const [width, height] of [
  [1440, 900],
  [1280, 720],
] as const) {
  test(`the Desk never scrolls the window at ${width}x${height}; the header fits on one row`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height });
    await page.goto("/");
    await expect(page.getByTestId("organism-slot")).toBeVisible();
    const overflow = await page.evaluate(() => {
      const se = document.scrollingElement!;
      return { y: se.scrollHeight - window.innerHeight, x: se.scrollWidth - window.innerWidth };
    });
    expect(overflow).toEqual({ y: 0, x: 0 });
    // Each stepper label stays on one line (a wrapped label doubles its height).
    for (const label of await page.getByTestId("story-stepper").getByRole("listitem").all()) {
      expect((await label.boundingBox())!.height).toBeLessThan(24);
    }
    const notice = (await page.getByTestId("synthetic-notice").boundingBox())!;
    const stepper = (await page.getByTestId("story-stepper").boundingBox())!;
    expect(notice.x + notice.width).toBeLessThanOrEqual(stepper.x);
  });
}
