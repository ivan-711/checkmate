import { expect, test, type Page } from "@playwright/test";

// Run by `npm run e2e:api` against the API-mode build and an API in REPLAY with the corpus hero.
// It presses Reset demo on that API; the config refuses to run unless CHECKMATE_API_ORIGIN names it.
// The idle kiosk offers two scripted lines: the hero's (Sofia, first and unchanged) and a new
// patient's. Both Use this buttons sit fully above the message box, without the kiosk scrolling.
const RESET_MS = 90_000;
test.setTimeout(240_000);

const SIZES = [
  { width: 1512, height: 982 },
  { width: 1440, height: 900 },
  { width: 1512, height: 760 },
  { width: 1280, height: 650 },
];
const LANGS = [
  { toggle: "English", use: "Use this" },
  { toggle: "Español", use: "Usar este" },
] as const;

async function reset(page: Page) {
  await page.goto("/");
  const done = page.waitForResponse(
    (r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/sessions",
    { timeout: RESET_MS },
  );
  await page.getByTestId("reset-button").click();
  await done;
  await expect(page.getByTestId("source-card")).toHaveCount(2, { timeout: RESET_MS });
}

for (const size of SIZES) {
  for (const lang of LANGS) {
    test(`both demo lines' Use this fit above the message box at ${size.width}x${size.height} (${lang.toggle})`, async ({
      page,
    }) => {
      await page.setViewportSize(size);
      await reset(page);
      if (lang.toggle === "Español") await page.getByRole("button", { name: "Español" }).click();
      const uses = page.getByRole("button", { name: lang.use, exact: true });
      await expect(uses).toHaveCount(2, { timeout: 30_000 });
      // Sofia's line stays first.
      const kiosk = (await page.getByTestId("kiosk").innerText()).replace(/\s+/g, " ");
      expect(kiosk.indexOf("Sofia Mesa-López")).toBeGreaterThan(-1);
      expect(kiosk.indexOf("Sofia Mesa-López")).toBeLessThan(kiosk.indexOf("Teodoro Quintanilla Abasolo"));

      const composerTop = (await page.getByTestId("kiosk-composer").boundingBox())!.y;
      for (const use of await uses.all()) {
        await expect(use).toBeInViewport({ ratio: 1 });
        const box = (await use.boundingBox())!;
        expect(box.y + box.height, "Use this above the message box").toBeLessThanOrEqual(composerTop);
      }
      const overflow = await page.locator(".k-swap").evaluate((el) => el.scrollHeight - el.clientHeight);
      expect(overflow, "the idle kiosk does not scroll").toBeLessThanOrEqual(1);
    });
  }
}

const NEW_PATIENT = [
  {
    toggle: "English",
    use: "Use this",
    line: "My name is Teodoro Quintanilla Abasolo, born November 9, 1951, my phone is 555-012-7734.",
    reply: "We have started your registration",
  },
  {
    toggle: "Español",
    use: "Usar este",
    line: "Me llamo Teodoro Quintanilla Abasolo, nací el 9 de noviembre de 1951, mi teléfono es 555-012-7734.",
    reply: "Hemos iniciado su registro",
  },
] as const;

for (const lang of NEW_PATIENT) {
  test(`the new patient's line opens a chart and the Desk stays calm (${lang.toggle})`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const failures: string[] = [];
    page.on("response", (r) => {
      if (r.status() >= 500) failures.push(`${r.status()} ${r.request().method()} ${r.url()}`);
    });
    page.on("pageerror", (e) => failures.push(String(e)));
    await reset(page);
    if (lang.toggle === "Español") await page.getByRole("button", { name: "Español" }).click();
    await page.getByRole("button", { name: lang.use, exact: true }).nth(1).click({ timeout: 30_000 });
    // The replay accepts only the transcript's exact text.
    await expect(page.getByTestId("kiosk-composer")).toHaveValue(lang.line);
    await page.getByTestId("kiosk-send").click();
    await expect(page.getByTestId("kiosk")).toContainText(lang.reply, { timeout: 30_000 });
    // No gate card: the gate allowed a new chart, so nothing is held for a registrar.
    await expect(page.getByTestId("gate-card")).toHaveCount(0);
    await expect(page.locator('[data-pane="held"]')).toHaveCount(0);
    await expect(page.locator('[data-pane="idle"]')).toBeVisible();
    await expect(page.getByText(/Records unavailable/)).toHaveCount(0);
    expect(failures).toEqual([]);
  });
}
