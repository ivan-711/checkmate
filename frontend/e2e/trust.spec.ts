import { expect, test, type Page } from "@playwright/test";

// Lane F: the calm, trustworthy layer on the kiosk, on the redesign's living-record kiosk.
// Fixture mode (the default data source).
const COPY = {
  en: {
    toggle: "English",
    use: "Use this",
    promise: "FrontDesk gets it ready. A registrar confirms.",
    held: "Held for a registrar. Please have a seat; they’ll confirm it with you.",
    steps: [
      "Read your check-in",
      "Found a chart that may be yours",
      "Asked to open a new chart",
      "Checked with the identity gate: held",
    ],
    fact: "held",
    title: "A chart may already be yours",
  },
  es: {
    toggle: "Español",
    use: "Usar este",
    promise: "FrontDesk lo prepara. Admisión lo confirma.",
    held: "En espera de admisión. Tome asiento; confirmarán sus datos con usted.",
    steps: [
      "Leyó su mensaje",
      "Encontró un expediente que podría ser suyo",
      "Pidió abrir un expediente nuevo",
      "Consultó el control de identidad: en espera",
    ],
    fact: "en espera",
    title: "Puede que ya tenga un expediente",
  },
} as const;

const INK = "rgb(27, 20, 25)"; // --ink, the living-record tokens
const INK_2 = "rgb(92, 82, 89)"; // --ink-2, the agent's own words

async function checkIn(page: Page, lang: keyof typeof COPY) {
  await page.goto("/");
  await page.getByRole("button", { name: COPY[lang].toggle }).click();
  await expect(page.getByTestId("kiosk-promise")).toHaveText(COPY[lang].promise);
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

      const steps = page.getByTestId("turn-steps");
      for (const step of c.steps) await expect(steps).toContainText(step);
      const fact = steps.getByTestId("gate-fact");
      await expect(fact).toHaveAttribute("data-outcome", "HELD");
      await expect(fact).toHaveAttribute("data-reason", "CANDIDATE_IN_REVIEW_OR_HIGHER");
      await expect(fact).toHaveAttribute("data-policy", "frontdesk-gate/1");
      await expect(fact).toContainText(c.fact);
      // No system code on the patient's screen: the reason is the gate card's body.
      await expect(fact).not.toContainText("CANDIDATE_IN_REVIEW_OR_HIGHER");
      await expect(page.getByTestId("kiosk")).not.toContainText("frontdesk-gate/1");
      // The fact is the checklist's last line.
      await expect(steps.locator("li").last()).toHaveAttribute("data-testid", "gate-fact");
      // The checklist is one voice, ink-2 like the prototype's steps; the gate card carries the weight.
      await expect(fact).toHaveCSS("color", INK_2);
      await expect(page.getByTestId("rule-result-tag")).toHaveCount(0);
      await expect(page.getByTestId("tool-call-chip")).toHaveCount(2);

      const card = page.getByTestId("gate-card");
      await expect(card).toContainText(c.title);
      await expect(card).toContainText(c.held);

      // Kiosk text is 18 px or larger; the page never scrolls sideways.
      const small = await page.getByTestId("kiosk").evaluate((root) =>
        [...root.querySelectorAll("*")]
          .filter((el) => el.checkVisibility({ visibilityProperty: true }))
          .filter((el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent!.trim()))
          .filter((el) => parseFloat(getComputedStyle(el).fontSize) < 18)
          .map((el) => el.outerHTML.slice(0, 80)),
      );
      expect(small).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

      // Once a registrar links the chart, the held line no longer applies.
      await page.getByTestId("resolve-button").click();
      await page.getByTestId("approve-button").click();
      await page.getByTestId("review-submit-button").click();
      await expect(page.getByTestId("kiosk")).toHaveAttribute("data-k", "done");
      await expect(page.getByTestId("gate-card")).toHaveCount(0);
    });
  }
}

test("the agent's own words are gray; system text stays ink", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("kiosk-composer").fill("I have an appointment at three.");
  await page.keyboard.press("Enter");
  // The fixture answers off-script text with the system template, which is a fact.
  await expect(page.locator('[data-voice="system"]').first()).toHaveCSS("color", INK);
  // The agent tone itself, checked on the token the agent line uses.
  const gray = await page.evaluate(() => {
    const probe = document.createElement("p");
    probe.className = "text-ink-2";
    document.body.append(probe);
    return getComputedStyle(probe).color;
  });
  expect(gray).toBe(INK_2);
});

for (const reduced of [false, true]) {
  test(`kiosk edge glows while the agent works${reduced ? ", as a still ring under reduced motion" : ""}`, async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: reduced ? "reduce" : "no-preference" });
    await page.goto("/");
    const kiosk = page.getByTestId("kiosk");
    await expect(kiosk).toHaveAttribute("data-k", "idle");
    const glow = () =>
      kiosk.evaluate((el) => {
        const after = getComputedStyle(el, "::after");
        return {
          opacity: after.opacity,
          animation: after.animationName,
          shadow: after.boxShadow,
          border: after.borderColor,
        };
      });
    expect((await glow()).opacity).toBe("0");
    await kiosk.evaluate((el) => el.setAttribute("data-k", "working"));
    await expect.poll(async () => (await glow()).opacity).toBe("1");
    const { animation, shadow, border } = await glow();
    if (reduced) expect(animation).toBe("none");
    else expect(animation).not.toBe("none");
    for (const [r, g, b] of [...`${shadow} ${border}`.matchAll(/rgba?\((\d+), (\d+), (\d+)/g)].map((m) =>
      m.slice(1).map(Number),
    ))
      expect(r > 150 && g < 90 && b < 90, `${shadow} ${border} has no red`).toBe(false);
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
