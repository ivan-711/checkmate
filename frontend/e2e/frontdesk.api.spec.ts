import { expect, test } from "@playwright/test";

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
