import { expect, test } from "@playwright/test";
import { BODY_TEXT_PX, fontSizePx, kioskTextBelow } from "./kioskText";

// Runs against the fixture adapter. The demo laptop shows the Desk at 1280x720.
test.use({ viewport: { width: 1280, height: 720 } });

const LANGUAGES = [
  {
    toggle: "English",
    use: "Use this",
    held: "Checked with the identity gate: held",
    approved:
      "A registrar linked your check-in to your chart. Please have a seat; someone will call your name.",
  },
  {
    toggle: "Español",
    use: "Usar este",
    held: "Consultó el control de identidad: en espera",
    approved: "Admisión vinculó su registro a su expediente. Tome asiento; le llamarán por su nombre.",
  },
];

for (const lang of LANGUAGES) {
  test(`kiosk text is 18 px or more in every state, patient lines at body size (${lang.toggle})`, async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByRole("button", { name: lang.toggle }).click();
    await expect(page.getByTestId("kiosk-composer")).toBeVisible();
    expect(await kioskTextBelow(page)).toEqual([]);

    await page.getByRole("button", { name: lang.use }).click();
    await expect(page.getByTestId("kiosk-send")).toBeEnabled();
    await page.getByTestId("kiosk-send").click();
    await expect(page.getByTestId("gate-card")).toBeVisible();
    // A step opens its detail (the tool id lives there); the gate card's details open too.
    await page.getByTestId("tool-call-chip").getByRole("button").first().click();
    await page.getByTestId("gate-card").locator("summary").click();
    expect(await kioskTextBelow(page)).toEqual([]);
    expect(await fontSizePx(page.getByTestId("gate-fact").getByText(lang.held))).toBeGreaterThanOrEqual(
      BODY_TEXT_PX,
    );

    // The registrar approves on the Desk's stage; the kiosk reads the decision and says so.
    await page.getByTestId("resolve-button").click();
    await page.getByTestId("approve-button").click();
    await page.getByTestId("review-submit-button").click();
    await expect(page.getByText(lang.approved)).toBeVisible();
    expect(await kioskTextBelow(page)).toEqual([]);
  });
}
