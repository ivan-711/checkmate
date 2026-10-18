import { expect, test, type Route } from "@playwright/test";
import { BODY_TEXT_PX, fontSizePx, kioskTextBelow } from "./kioskText";

// Run by `npm run e2e:api` against the API-mode build and an API in REPLAY with the corpus hero.
// It presses Reset demo on that API; the config refuses to run unless CHECKMATE_API_ORIGIN names it.
const isTurn = (url: string) => /\/intake-sessions\/[^/]+\/turns$/.test(url);
const isStart = (url: string, method: string) =>
  method === "POST" && new URL(url).pathname === "/api/v1/intake-sessions";

test("Send is held during Reset; Español before the first turn plays the recorded ES reply", async ({
  page,
}) => {
  const starts: string[] = [];
  page.on("request", (r) => {
    if (isStart(r.url(), r.method())) starts.push(r.postDataJSON()?.language);
  });
  await page.goto("/");
  await expect(page.getByTestId("kiosk-composer")).toBeVisible();

  // Reset on the corpus takes seconds: nothing can be sent until it has finished.
  let resetDone = false;
  const reset = page
    .waitForResponse(
      (r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/sessions",
      {
        timeout: 60_000,
      },
    )
    .then(() => (resetDone = true));
  const startsBeforeReset = starts.length;
  await page.getByTestId("reset-button").click();
  await page.getByTestId("kiosk-composer").fill("hello");
  await expect(page.getByTestId("kiosk-send")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Use this" })).toBeDisabled();
  await reset;
  expect(resetDone).toBe(true);
  // The new check-in starts only after the reset completed.
  await expect.poll(() => starts.length).toBeGreaterThan(startsBeforeReset);
  await page.getByTestId("kiosk-composer").fill("");

  await page.getByRole("button", { name: "Español" }).click();
  await expect.poll(() => starts.at(-1)).toBe("ES");
  await page.getByRole("button", { name: "Usar este" }).click();
  const [res] = await Promise.all([
    page.waitForResponse((r) => isTurn(r.url()), { timeout: 30_000 }),
    page.keyboard.press("Enter"),
  ]);
  const turn = await res.json();
  expect(turn.degraded ?? null).toBeNull();
  expect(turn.assistantTextSource).toBe("MODEL");
  await expect(page.getByTestId("gate-card")).toBeVisible();
  // The hero holds two pairs for the registrar (the ER and the Clinic record); the Desk knows.
  expect(turn.registration.handoffPairIds).toHaveLength(2);
  await expect(page.locator('[data-kiosk="held"]')).toHaveCount(1);
});

// BUILD-SPEC decision 5: on the API a second check-in without a reset would find the first one's
// own intake record, so Start over performs the same Reset as the top bar's Reset demo.
test("Start over after a held check-in resets the demo, then starts a new check-in", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("kiosk-composer")).toBeVisible();
  await page.getByRole("button", { name: "Use this" }).click();
  await expect(page.getByTestId("kiosk-send")).toBeEnabled({ timeout: 30_000 });
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("gate-card")).toBeVisible({ timeout: 30_000 });
  // The demo line runs once per check-in.
  await expect(page.getByRole("button", { name: "Use this" })).toHaveCount(0);

  const starts: string[] = [];
  page.on("request", (r) => {
    if (isStart(r.url(), r.method())) starts.push(r.url());
  });
  const [reset] = await Promise.all([
    page.waitForResponse(
      (r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/sessions",
      { timeout: 60_000 },
    ),
    page.getByRole("button", { name: "Start over" }).click(),
  ]);
  expect(reset.status()).toBe(201);
  await expect(page.getByTestId("kiosk")).toHaveAttribute("data-k", "idle", { timeout: 30_000 });
  await expect.poll(() => starts.length, { timeout: 30_000 }).toBeGreaterThan(0);
  await expect(page.getByRole("button", { name: "Use this" })).toBeEnabled({ timeout: 30_000 });
});

for (const lang of [
  {
    toggle: "English",
    use: "Use this",
    reading: "Reading your message",
    wait: "Wait for FrontDesk to finish",
    failed: "FrontDesk could not reach the agent service. Your message was not sent.",
  },
  {
    toggle: "Español",
    use: "Usar este",
    reading: "Leyendo su mensaje",
    wait: "Espere a que FrontDesk termine",
    failed: "FrontDesk no pudo conectar con el servicio del agente. Su mensaje no se envió.",
  },
]) {
  test(`waiting, then a failed first turn: kiosk text at 18 px or more at 1280x720 (${lang.toggle})`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto("/");
    await page.getByRole("button", { name: lang.toggle }).click();
    await page.getByRole("button", { name: lang.use }).click();
    await expect(page.getByTestId("kiosk-send")).toBeEnabled({ timeout: 30_000 });

    let held: Route | null = null;
    await page.route("**/api/v1/intake-sessions/*/turns", (route) => {
      held = route;
    });
    await page.getByTestId("kiosk-send").click();
    await expect.poll(() => held !== null).toBe(true);
    await expect(page.getByText(lang.reading)).toBeVisible();
    await expect(page.getByText(lang.wait)).toBeVisible();
    expect(await kioskTextBelow(page)).toEqual([]);
    expect(await fontSizePx(page.getByText(lang.reading))).toBeGreaterThanOrEqual(BODY_TEXT_PX);

    // The turn never reaches the API, so this check writes no check-in record. The kiosk then shows
    // its failed-turn automatic message, the other state a waiting patient can see.
    await held!.abort();
    await page.unroute("**/api/v1/intake-sessions/*/turns");
    await expect(page.getByText(lang.failed)).toBeVisible();
    expect(await kioskTextBelow(page)).toEqual([]);
  });
}
