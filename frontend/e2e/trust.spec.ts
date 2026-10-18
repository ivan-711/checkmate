import { expect, test, type Page } from "@playwright/test";

// Lane F: the calm, trustworthy layer on the kiosk. Fixture mode (the default data source).
const COPY = {
  en: {
    toggle: "English",
    use: "Use this",
    promise: "Nothing is linked to your chart until a staff member approves.",
    held: "Held for review. No records were linked.",
    steps: ["Read your check-in", "Searched for an existing chart", "Asked to create a new chart"],
    fact: "HELD",
    ruleResult: "Rule result",
    reason: "An existing chart may be yours",
  },
  es: {
    toggle: "Español",
    use: "Usar este",
    promise: "No se vincula nada a su expediente hasta que un miembro del personal lo apruebe.",
    held: "En espera de revisión. No se vinculó ningún expediente.",
    steps: ["Se leyó su registro", "Se buscó un expediente existente", "Se pidió crear un expediente nuevo"],
    fact: "EN ESPERA",
    ruleResult: "Resultado de regla",
    reason: "Un expediente existente podría ser suyo",
  },
} as const;

const NEAR_BLACK = "rgb(17, 24, 39)"; // --ink-1, light theme
const AGENT_GRAY = "rgb(55, 65, 81)"; // --ink-2, light theme

async function checkIn(page: Page, lang: keyof typeof COPY) {
  await page.goto("/frontdesk");
  await page.getByRole("button", { name: COPY[lang].toggle }).click();
  await page.getByRole("button", { name: COPY[lang].use }).click();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("gate-card")).toBeVisible();
}

for (const viewport of [
  { width: 1280, height: 720 },
  { width: 1366, height: 768 },
]) {
  for (const lang of ["en", "es"] as const) {
    test(`held check-in reads calm and true at ${viewport.width}x${viewport.height} (${lang})`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await checkIn(page, lang);
      const c = COPY[lang];

      await expect(page.getByTestId("kiosk-promise")).toHaveText(c.promise);

      const steps = page.getByTestId("turn-steps");
      for (const step of c.steps) await expect(steps).toContainText(step);
      const fact = steps.getByTestId("gate-fact");
      await expect(fact).toHaveAttribute("data-outcome", "HELD");
      await expect(fact).toContainText(c.fact);
      await expect(fact).toContainText(c.reason);
      await expect(fact).not.toContainText("CANDIDATE_IN_REVIEW_OR_HIGHER");
      await expect(fact).toContainText(c.ruleResult);
      // The fact is the checklist's last line.
      await expect(steps.locator("li").last()).toHaveAttribute("data-testid", "gate-fact");
      await expect(fact).toHaveCSS("color", NEAR_BLACK);
      await expect(page.getByTestId("gate-card")).toContainText(c.ruleResult);
      // Every rule-result tag reads on one line, in both languages.
      await expect(page.getByTestId("rule-result-tag")).toHaveCount(2); // the fact line and the gate card
      for (const tag of await page.getByTestId("rule-result-tag").all()) {
        expect((await tag.boundingBox())!.height).toBeLessThan(32);
      }
      await expect(page.getByTestId("tool-call-chip")).toHaveCount(2);

      await expect(page.getByTestId("kiosk-finish-held")).toHaveText(c.held);
      await expect(page.getByTestId("kiosk-finish-held")).toHaveCSS("color", NEAR_BLACK);

      // Kiosk text is 16 px or larger; the page never scrolls sideways.
      const small = await page.locator('section[aria-labelledby="kiosk-label"]').evaluate((root) =>
        [...root.querySelectorAll("*")]
          .filter((el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent!.trim()))
          .filter((el) => parseFloat(getComputedStyle(el).fontSize) < 16)
          .map((el) => el.outerHTML.slice(0, 80)),
      );
      expect(small).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

      // Once a registrar links the chart, the held line no longer applies.
      await page.getByTestId("approve-button").click();
      await page.getByTestId("review-submit-button").click();
      await expect(page.getByTestId("kiosk-finish-held")).toHaveCount(0);
    });
  }
}

test("the agent's own words are gray; system text stays near-black", async ({ page }) => {
  await page.goto("/frontdesk");
  await page.getByTestId("kiosk-composer").fill("I have an appointment at three.");
  await page.keyboard.press("Enter");
  // The fixture answers off-script text with the system template, which is a fact.
  await expect(page.locator('[data-voice="system"]').first()).toHaveCSS("color", NEAR_BLACK);
  // The agent tone itself, checked on the token the agent line uses.
  const gray = await page.evaluate(() => {
    const probe = document.createElement("p");
    probe.className = "text-ink-2";
    document.body.append(probe);
    return getComputedStyle(probe).color;
  });
  expect(gray).toBe(AGENT_GRAY);
});

for (const reduced of [false, true]) {
  test(`kiosk edge glows while the agent works${reduced ? ", never under reduced motion" : ""}`, async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: reduced ? "reduce" : "no-preference" });
    await page.goto("/frontdesk");
    const frame = page.locator(".kiosk-frame");
    await expect(frame).toHaveAttribute("data-working", "false");
    await expect(frame).toHaveCSS("box-shadow", "none");
    await frame.evaluate((el) => el.setAttribute("data-working", "true"));
    if (reduced) {
      await expect(frame).toHaveCSS("box-shadow", "none");
    } else {
      await expect(frame).not.toHaveCSS("box-shadow", "none");
      await expect(frame).toHaveCSS("transition-timing-function", "cubic-bezier(0.23, 1, 0.32, 1)");
      await expect(frame).toHaveCSS("transition-duration", "0.3s");
      const shadow = await frame.evaluate((el) => getComputedStyle(el).boxShadow);
      for (const [r, g, b] of [...shadow.matchAll(/rgba?\((\d+), (\d+), (\d+)/g)].map((m) =>
        m.slice(1).map(Number),
      ))
        expect(r > 150 && g < 90 && b < 90, `${shadow} has no red`).toBe(false);
    }
  });
}

test("the flag card on Case is a rule result, neutral and never an alert", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("resolve-button").click();
  await page.getByTestId("approve-button").click();
  await page.getByTestId("review-submit-button").click();
  const card = page.getByTestId("flag-card");
  await expect(card.locator("header")).toContainText("Rule result");
  await expect(card).not.toContainText("Verified");
  await expect(card).not.toHaveAttribute("role", "alert");
  await expect(card.getByTestId("flag-card-rule-id")).toHaveText("BL-AMOX-01");
});
