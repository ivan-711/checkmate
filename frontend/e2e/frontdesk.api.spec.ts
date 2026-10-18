import { expect, test, type Page, type Response, type Route } from "@playwright/test";
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
  await page.goto("/frontdesk");
  await expect(page.getByTestId("agent-mode-badge")).toBeVisible();

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
  await expect(page.getByTestId("registrar-held")).toContainText("Held check-ins (2)");
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
  test(`waiting, then a failed first turn: kiosk text at 16 px or more at 1280x720 (${lang.toggle})`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto("/frontdesk");
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

const isReset = (r: Response) =>
  r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/sessions";

/** Reset demo, waited for: the first Reset after an API start can take 20 s on the corpus. */
async function resetDemo(page: Page) {
  await Promise.all([
    page.waitForResponse(isReset, { timeout: 60_000 }),
    page.getByTestId("reset-button").click(),
  ]);
  await expect(page.getByTestId("reset-button")).toBeEnabled({ timeout: 30_000 });
}

test("Start over in LOCAL resets the demo: the next check-in meets the hero's ER chart, not its own earlier entry", async ({
  page,
}) => {
  test.setTimeout(120_000); // two resets on the corpus (the first can take 20 s) and two turns
  await page.goto("/frontdesk");
  await expect(page.getByTestId("agent-mode-badge")).toBeVisible();
  await resetDemo(page);
  const useThis = page.getByRole("button", { name: "Use this" });
  await expect(useThis).toBeEnabled({ timeout: 30_000 });
  await useThis.click();
  await page.keyboard.press("Enter");
  const gate = page.getByTestId("gate-card");
  await expect(gate).toBeVisible({ timeout: 30_000 });
  await expect(gate).toContainText("ER FHIR");
  await expect(page.getByTestId("registrar-held")).toContainText("Held check-ins (2)");

  // Every check-in leaves an intake record on the server. Only a reset removes it: without one,
  // the next check-in's gate matches this check-in's own record (AUTO-LINK, sorted first) and
  // shows it instead of the hero chart, the registrar holds three pairs, one of them
  // intake-to-intake, and the replay diverges.
  await Promise.all([
    page.waitForResponse(isReset, { timeout: 60_000 }),
    page.getByRole("button", { name: "Start over" }).click(),
  ]);
  await expect(page.getByText("Your conversation will appear here.")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("No held check-ins.")).toBeVisible();
  await expect(useThis).toBeEnabled({ timeout: 30_000 });
  await useThis.click();
  await page.keyboard.press("Enter");
  await expect(gate).toBeVisible({ timeout: 30_000 });
  await expect(gate).toContainText("ER FHIR");
  await expect(gate).not.toContainText("Frontdesk Intake");
  await expect(page.getByTestId("registrar-held")).toContainText("Held check-ins (2)");
});

test("Use this is locked while the first turn is being read, and gone once the turn has landed", async ({
  page,
}) => {
  test.setTimeout(90_000); // a reset on the corpus, then a turn
  await page.goto("/frontdesk");
  await resetDemo(page);
  const useThis = page.getByRole("button", { name: "Use this" });
  await expect(useThis).toBeEnabled({ timeout: 30_000 });
  await useThis.click();
  await expect(page.getByTestId("kiosk-send")).toBeEnabled({ timeout: 30_000 });

  let held: Route | null = null;
  await page.route("**/api/v1/intake-sessions/*/turns", (route) => {
    held = route;
  });
  await page.getByTestId("kiosk-send").click();
  await expect.poll(() => held !== null).toBe(true);
  await expect(page.getByText("Reading your message")).toBeVisible();
  // Pressed now, it would refill the composer with the line a later Enter sends again as turn 1,
  // which the replay cannot play: the same check-in would then end on the template reply.
  await expect(useThis).toBeDisabled();

  await held!.continue();
  await page.unroute("**/api/v1/intake-sessions/*/turns");
  await expect(page.getByTestId("gate-card")).toBeVisible({ timeout: 30_000 });
  await expect(useThis).toHaveCount(0);
});
