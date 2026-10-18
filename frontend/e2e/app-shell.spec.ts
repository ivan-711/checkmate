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
