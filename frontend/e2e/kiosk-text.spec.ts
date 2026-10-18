import { expect, test } from "@playwright/test";
import { BODY_TEXT_PX, fontSizePx, kioskTextBelow } from "./kioskText";

// Runs against the fixture adapter. The demo laptop shows FrontDesk at 1280x720.
test.use({ viewport: { width: 1280, height: 720 } });

const LANGUAGES = [
  {
    toggle: "English",
    use: "Use this",
    automatic: "automatic message",
    denied: "Denied by identity gate",
    approved: "Your chart is confirmed. Please wait to be called.",
  },
  {
    toggle: "Español",
    use: "Usar este",
    automatic: "mensaje automático",
    denied: "Denegado por el control de identidad",
    approved: "Su expediente está confirmado. Espere a que lo llamen.",
  },
];

for (const lang of LANGUAGES) {
  test(`kiosk text is 16 px or more in every state, patient lines at body size (${lang.toggle})`, async ({
    page,
  }) => {
    await page.goto("/frontdesk");
    await page.getByRole("button", { name: lang.toggle }).click();
    await expect(page.getByTestId("agent-mode-badge")).toBeVisible();
    expect(await kioskTextBelow(page)).toEqual([]);

    await page.getByRole("button", { name: lang.use }).click();
    await expect(page.getByTestId("kiosk-send")).toBeEnabled();
    await page.getByTestId("kiosk-send").click();
    await expect(page.getByTestId("gate-card")).toBeVisible();
    // The allowed search chip opens its gate details; the denied one has the gate card instead.
    await page.getByTestId("tool-call-chip").getByRole("button").first().click();
    expect(await kioskTextBelow(page)).toEqual([]);
    const outcome = page.getByTestId("tool-call-chip").getByText(lang.denied);
    expect(await fontSizePx(outcome)).toBeGreaterThanOrEqual(BODY_TEXT_PX);
    expect(await fontSizePx(page.getByText(lang.automatic).first())).toBeGreaterThanOrEqual(BODY_TEXT_PX);

    await page.getByTestId("approve-button").click();
    await page.getByTestId("review-submit-button").click();
    await expect(page.getByText(lang.approved)).toBeVisible();
    expect(await kioskTextBelow(page)).toEqual([]);
  });
}

test("the agent mode label follows the kiosk language; the mode stays as the source gives it", async ({
  page,
}) => {
  await page.goto("/frontdesk");
  await expect(page.getByTestId("agent-mode-badge")).toHaveText("Agent: REPLAY");
  await page.getByRole("button", { name: "Español" }).click();
  await expect(page.getByTestId("agent-mode-badge")).toHaveText("Agente: REPLAY");
});

test("the empty transcript line is centred between the transcript heading and the composer", async ({
  page,
}) => {
  await page.goto("/frontdesk");
  const region = page.getByRole("region", { name: "Check-in conversation" });
  const line = region.getByText("Your conversation will appear here.");
  await expect(line).toBeVisible();
  const text = await line.evaluate((el) => {
    const range = document.createRange();
    range.selectNodeContents(el);
    const { left, right, top, bottom } = range.getBoundingClientRect();
    return { left, right, top, bottom };
  });
  const regionBox = (await region.boundingBox())!;
  const headingRow = (await region.getByRole("heading", { name: "TRANSCRIPT" }).locator("..").boundingBox())!;
  const composer = (await page.getByTestId("kiosk-composer").boundingBox())!;

  const offCentre = (text.left + text.right) / 2 - (regionBox.x + regionBox.width / 2);
  expect(Math.abs(offCentre)).toBeLessThanOrEqual(1);
  const above = text.top - (headingRow.y + headingRow.height);
  const below = composer.y - text.bottom;
  expect(Math.abs(above - below)).toBeLessThanOrEqual(2);
});
