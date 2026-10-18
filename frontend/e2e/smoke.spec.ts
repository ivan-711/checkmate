import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

// Runs against the fixture adapter (the default data source).
const scenario = JSON.parse(
  readFileSync(path.join(__dirname, "../../contracts/fixtures/scenario.json"), "utf8"),
);

// The confirm sheet (L4) holds the reason, the registrar and the note.
const reviewPanel = (page: Page) => page.getByTestId("confirm-sheet");

/** Reset, then Resolve: the pair panel waits for Resolve identity, as the G16 path does. */
async function resolved(page: Page) {
  await page.goto("/");
  await page.getByTestId("reset-button").click();
  await page.getByTestId("resolve-button").click();
  await expect(page.getByTestId("candidate-pair")).toBeVisible();
}

async function review(page: Page, kind: "approve" | "reject", reason?: string, note = "", registrar = "") {
  await page.getByTestId(kind === "approve" ? "approve-button" : "reject-button").click();
  if (registrar) await reviewPanel(page).getByLabel("Registrar").selectOption(registrar);
  if (reason) await page.getByTestId("review-reason-select").selectOption(reason);
  if (note) await page.getByTestId("review-note-input").fill(note);
  await page.getByTestId("review-submit-button").click();
}

test("case path: reject keeps the rule silent, then approve links and flags", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Synthetic data. Not for clinical use.")).toBeVisible();
  await expect(page.getByTestId("app-mode-badge")).toHaveText(/Replay/);
  await expect(page.getByTestId("source-card")).toHaveCount(2);
  await expect(page.getByTestId("candidate-pair")).toHaveCount(0);
  await page.getByTestId("resolve-button").click();
  await expect(page.getByTestId("candidate-pair")).toBeVisible();
  await expect(page.getByTestId("pair-band")).toHaveText(/REVIEW/);

  // The Desk names sources in plain words (record/labels.ts): "Emergency room", "Clinic".
  const er = page.getByRole("article", { name: "Emergency room record" });
  await expect(er).toBeVisible();
  await expect(er.getByText("constructed scenario")).toBeVisible();
  await expect(page.getByRole("article", { name: "Clinic record" })).toBeVisible();
  // The rail leads with the match score (L4); the probability caption left with the old rail.
  await expect(page.getByRole("heading", { name: "Match score" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Top evidence" }).getByRole("listitem")).toHaveCount(5);
  // The stage holds no notice until a link is approved (the quiet pre-link lines left with the old card).
  await expect(page.getByTestId("flag-card")).toHaveCount(0);

  // "Not enough evidence" keeps the pair open to Resolve again; "different person" would close it.
  await review(page, "reject", "INSUFFICIENT_EVIDENCE", "", "Registrar B");
  await expect(page.getByText("Rejected by Registrar B")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Kept apart" })).toBeVisible();
  await expect(page.getByTestId("flag-card")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Flagged for clinician review" })).toHaveCount(0);
  await expect(page.locator('[data-testid="event-row"][data-event-type="LINK_REJECTED"]')).toHaveCount(1);

  await page.getByTestId("resolve-button").click();
  await review(page, "approve", undefined, "second review approves", "Registrar B");
  // The approval raised the flag: focus lands on the flag card's heading.
  await expect(page.getByRole("heading", { name: "Flagged for clinician review" })).toBeFocused();
  // The joined record is headed by the patient's name; its tabs name both sources.
  const goldenRegion = page.getByTestId("golden-record");
  await expect(
    goldenRegion.locator('[data-testid="crosswalk-chip"][data-source-system="CLINIC_CSV"]'),
  ).toContainText("Clinic");
  await expect(
    goldenRegion.locator('[data-testid="crosswalk-chip"][data-source-system="ER_FHIR"]'),
  ).toContainText("Emergency room");
  await expect(page.getByRole("article", { name: "Emergency room record" })).toHaveCount(0);

  const timeline = page.getByTestId("timeline");
  for (const event of scenario.timelineIfApproved) {
    await expect(timeline.getByText(event.display)).toBeVisible();
  }

  const flag = page.getByRole("article", { name: "Flagged for clinician review" });
  await expect(flag).toBeVisible();
  await expect(flag.getByText("constructed scenario")).toBeVisible();
  // The card leads with one line; the full text and the rule's limits sit under Details.
  await expect(flag.getByTestId("flag-card-headline")).toHaveText(
    "Penicillin V allergy (anaphylaxis) on the Clinic record, and an active amoxicillin order on the Emergency room record. A clinician decides.",
  );
  const { cardFooter, ruleId, ruleVersion } = scenario.alertIfApproved;
  const footer = flag.getByText(cardFooter.replace(`Rule ${ruleId} ${ruleVersion}.`, "").trim());
  await expect(footer).toBeHidden();
  await flag.getByText("Details", { exact: true }).click();
  // The footer's limits stay; its "Rule <id> <version>." prefix moved to the header, so the id shows once.
  await expect(footer).toBeVisible();
  expect(((await flag.textContent()) ?? "").split(ruleId).length - 1).toBe(1);
  await expect(page.getByTestId("flag-card-rule-id")).toHaveText("BL-AMOX-01");
  await expect(flag.getByTestId("constructed-scenario-chip")).toBeVisible();
  expect(await page.getByTestId("crosswalk-chip").count()).toBeGreaterThan(0);
  await expect(page.locator('[data-testid="timeline-event"][data-source-system="ER_FHIR"]')).not.toHaveCount(
    0,
  );
  await expect(page.locator('[data-testid="event-row"][data-event-type="LINK_APPROVED"]')).toHaveCount(1);
  await expect(page.locator('[data-testid="event-row"][data-event-type="ALERT_RAISED"]')).toHaveCount(1);
  await expect(page.getByTestId("tile-human-review-total")).toHaveText("2");
  await expect(timeline.getByText(/^Linked by Registrar B/)).toBeVisible();
  // Scoped to main: Next.js keeps its own empty route announcer outside it.
  await expect(page.locator('main [role="alert"]')).toHaveCount(0);
});

test("after Approve the flag card is on screen under the golden record, with History beside it", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await resolved(page);
  await review(page, "approve");
  const golden = await page.getByTestId("golden-record").boundingBox();
  const flag = page.getByTestId("flag-card");
  await expect(flag).toBeInViewport();
  const flagBox = await flag.boundingBox();
  const timelineBox = await page.getByTestId("timeline").boundingBox();
  expect(flagBox!.y).toBeGreaterThan(golden!.y);
  // History lives in the decision column (L4), to the right of the record and its notice.
  expect(timelineBox!.x).toBeGreaterThanOrEqual(flagBox!.x + flagBox!.width);
});

test("reject without a reason asks for one and records nothing", async ({ page }) => {
  await resolved(page);
  await page.getByTestId("reject-button").click();
  await page.getByTestId("review-submit-button").click();
  await expect(page.getByText("Select a reason to keep these records apart.")).toBeVisible();
  await expect(reviewPanel(page).getByLabel("Reason")).toBeFocused();
  await expect(page.getByText(/Rejected by/)).toHaveCount(0);
});

test("Cancel returns focus to the button that opened the step", async ({ page }) => {
  await resolved(page);
  for (const id of ["reject-button", "approve-button"]) {
    await page.getByTestId(id).click();
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByTestId(id)).toBeFocused();
  }
});

test("a recorded reject moves focus to the decision line", async ({ page }) => {
  await resolved(page);
  await review(page, "reject", "INSUFFICIENT_EVIDENCE");
  await expect(page.getByText(/^Rejected by/)).toBeFocused();
});

for (const { width, height } of [
  { width: 1440, height: 800 },
  { width: 1366, height: 650 },
]) {
  test(`both confirm steps fit above the fold at ${width}x${height}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await resolved(page);
    for (const id of ["reject-button", "approve-button"]) {
      await page.evaluate(() => window.scrollTo(0, 0));
      const opener = await page.getByTestId(id).boundingBox();
      expect(opener!.y + opener!.height, `${id} bottom`).toBeLessThanOrEqual(height);
      await page.getByTestId(id).click();
      await page.evaluate(() => window.scrollTo(0, 0));
      const submit = await page.getByTestId("review-submit-button").boundingBox();
      expect(submit!.y + submit!.height, `submit bottom after ${id}`).toBeLessThanOrEqual(height);
      await page.getByRole("button", { name: "Cancel" }).click();
    }
  });
}

test("a short screen shows the top 4 evidence rows with Show all for the rest", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 650 });
  await resolved(page);
  const rows = page.getByTestId("evidence-feature-row");
  await expect(rows.filter({ visible: true })).toHaveCount(4);
  await page.getByRole("button", { name: "Show all (5)" }).click();
  await expect(rows.filter({ visible: true })).toHaveCount(5);
  await page.setViewportSize({ width: 1440, height: 800 });
  await expect(page.getByRole("button", { name: /Show all/ })).toBeHidden();
});

test("reset returns to the separate records and Undo reset brings the link back", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("resolve-button").click();
  await review(page, "approve");
  await expect(page.getByTestId("golden-record")).toBeVisible();

  await page.getByRole("button", { name: "Reset demo" }).click();
  await expect(page.getByRole("article", { name: "Emergency room record" })).toBeVisible();
  await page.getByRole("button", { name: "Undo reset" }).click();
  await expect(page.getByTestId("golden-record")).toBeVisible();
  const golden = page.locator("#golden-heading");
  // Focus moves to the golden record only after an approval made here, not after Undo.
  await expect(golden).not.toBeFocused();
});

test("keyboard path reaches Approve link and moves focus to the raised flag", async ({ page }) => {
  await resolved(page);
  const approve = page.getByTestId("approve-button");
  for (let i = 0; i < 60 && !(await approve.evaluate((el) => el === document.activeElement)); i++) {
    await page.keyboard.press("Tab");
  }
  await expect(approve).toBeFocused();
  await page.keyboard.press("Enter");
  // The sheet opens with focus on the note. The note is a textarea (Enter is a new line), so the
  // keyboard path tabs on to Confirm and presses Enter there.
  await expect(page.getByTestId("review-note-input")).toBeFocused();
  const confirm = page.getByTestId("review-submit-button");
  for (let i = 0; i < 10 && !(await confirm.evaluate((el) => el === document.activeElement)); i++) {
    await page.keyboard.press("Tab");
  }
  await expect(confirm).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Flagged for clinician review" })).toBeFocused();
});

test("FrontDesk shell: the kiosk starts idle and switches ES/EN; the gate tile starts empty", async ({
  page,
}) => {
  await page.goto("/");
  const kiosk = page.getByTestId("kiosk");
  await expect(kiosk).toHaveAttribute("data-k", "idle");
  await page.getByRole("button", { name: "Español" }).click();
  await expect(page.getByText("Le damos la bienvenida. Registremos su llegada.")).toBeVisible();
  await expect(page.locator('[data-testid="kiosk"][lang="es"]')).toHaveCount(1);
  await page.getByRole("button", { name: "English" }).click();
  await expect(page.getByText("Welcome. Let’s get you checked in.")).toBeVisible();
  await expect(page.locator('[data-testid="kiosk"][lang="en"]')).toHaveCount(1);

  // The gate tile lives in the Activity strip: counts in words, the window in the caption.
  const tile = page.getByTestId("tile-agent-gate");
  await expect(tile).toContainText("0 denied · 0 allowed");
  await expect(tile).toContainText(/Gate, last \d+ min/);
});

test("FrontDesk check-in: the gate denies a new chart at REVIEW and hands it to a registrar", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Use this" }).click();
  await expect(page.getByTestId("kiosk-composer")).toBeFocused();
  await page.keyboard.press("Enter");

  const chips = page.getByTestId("tool-call-chip");
  await expect(chips).toHaveCount(2);
  await expect(chips.nth(0)).toHaveAttribute("data-outcome", "ALLOW");
  await expect(chips.nth(1)).toHaveAttribute("data-outcome", "DENY");
  const gate = page.getByTestId("gate-card");
  await expect(gate).toBeInViewport({ ratio: 1 });
  await expect(gate).toContainText("A chart may already be yours");
  await expect(gate).toHaveAttribute("data-policy", "frontdesk-gate/1");
  await expect(gate).not.toContainText("frontdesk-gate/1");
  await expect(gate).not.toHaveAttribute("role", "alert");
  await gate.locator("summary").click();
  await expect(gate).toContainText("Values hidden on this screen.");
  // The kiosk never shows the other chart's values.
  const masked = scenario.pair.recordB.normalized;
  for (const value of [masked.birthDate, masked.addressLine]) await expect(gate).not.toContainText(value!);
  await expect(gate).toContainText("Held for a registrar. Please have a seat");
  await expect(page.getByRole("status")).toContainText("New chart request denied by the identity gate.");
  // The Desk knows the check-in is held.
  await expect(page.locator('[data-kiosk="held"]')).toHaveCount(1);

  const tile = page.getByTestId("tile-agent-gate");
  await expect(tile).toContainText("1 denied · 1 allowed");

  await page.getByRole("button", { name: "Start over" }).click();
  await expect(page.getByTestId("kiosk")).toHaveAttribute("data-k", "idle");
  await expect(tile).toContainText("1 denied · 1 allowed"); // the audit history stays
});

test("FrontDesk in Spanish: the gate card, band and evidence fields are in Spanish", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Español" }).click();
  await page.getByRole("button", { name: "Usar este" }).click();
  await page.keyboard.press("Enter");
  const gate = page.getByTestId("gate-card");
  await expect(gate).toContainText("Puede que ya tenga un expediente");
  await gate.locator("summary").click();
  await expect(gate).toContainText("REVISIÓN");
  await expect(gate).toContainText("Fecha de nacimiento");
  await expect(gate).not.toContainText("REVIEW ");
  await page.getByRole("button", { name: "Empezar de nuevo" }).click();
  await expect(page.getByTestId("kiosk-composer")).toBeFocused();
  await expect(page.getByTestId("kiosk-composer")).toHaveValue("");
});

/** The demo check-in on the Desk: the gate holds it and the decision column offers Resolve. */
async function heldCheckIn(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Use this" }).click();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("gate-card")).toBeVisible();
  await expect(page.locator('[data-pane="held"]')).toBeVisible();
}

test("FrontDesk registrar: the held check-in is decided on the Desk and the kiosk says what is next", async ({
  page,
}) => {
  await heldCheckIn(page);
  const kiosk = page.getByTestId("kiosk");
  await expect(kiosk).toHaveAttribute("data-k", "held");
  await page.getByTestId("resolve-button").click();

  // Approve beside the held check-in: one Confirm links the records and attaches the check-in.
  // In REPLAY the hand-off pair is the hero pair, so this Confirm decides the check-in too and no
  // separate attach row shows; decision.api.spec.ts covers the attach row on the API.
  await page.getByTestId("approve-button").click();
  await expect(page.getByTestId("attach-checkin")).toHaveCount(0);
  await page.getByTestId("review-submit-button").click();
  await expect(page.getByTestId("golden-record")).toBeVisible();
  await expect(kiosk).toHaveAttribute("data-k", "done");
  await expect(page.getByTestId("attach-checkin-button")).toHaveCount(0);
  // The kiosk never shows the allergy or the flag card.
  await expect(kiosk.getByTestId("flag-card")).toHaveCount(0);
  await expect(kiosk).not.toContainText("amoxicillin");
});

test("FrontDesk registrar: the approval that raises the flag shows it on the Desk, said once, never an alert", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  await heldCheckIn(page);
  await page.getByTestId("resolve-button").click();
  await expect(page.getByTestId("flag-card")).toHaveCount(0);

  await review(page, "approve");
  const flag = page.getByTestId("flag-card");
  await expect(flag).toBeVisible();
  await expect(flag.getByTestId("flag-card-headline")).toHaveText(
    "Penicillin V allergy (anaphylaxis) on the Clinic record, and an active amoxicillin order on the Emergency room record. A clinician decides.",
  );
  await expect(page.getByRole("heading", { name: "Flagged for clinician review" })).toBeFocused();
  await expect(flag).toBeInViewport();
  // Said once, politely: the notice itself is not a live region and nothing is an alert.
  await expect(page.getByRole("status")).toHaveText(
    "Link approved. The two records are one record now. Flagged for clinician review: a rule found a documented allergy beside an active order.",
  );
  await expect(flag.locator("[aria-live], [role=alert], [role=status]")).toHaveCount(0);
  await expect(page.locator('main [role="alert"]')).toHaveCount(0);
});

// Landscape demo sizes and portrait kiosk sizes: no tooltip, open or closed, may add sideways scroll.
const SIDE_SCROLL_VIEWPORTS = [
  { width: 1280, height: 720 },
  { width: 1440, height: 900 },
  { width: 768, height: 1024 },
  { width: 390, height: 844 },
];
const sideScroll = (page: Page) =>
  page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);

for (const viewport of SIDE_SCROLL_VIEWPORTS) {
  test(`FrontDesk at ${viewport.width}x${viewport.height}: no sideways scroll before a turn, after a turn, after Approve, with each chip open`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await expect(page.getByRole("button", { name: "Use this" })).toBeVisible();
    expect(await sideScroll(page), "before a turn").toBeLessThanOrEqual(0);

    await page.getByRole("button", { name: "Use this" }).click();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("gate-card")).toBeVisible();
    await expect(page.locator('[data-pane="held"]')).toBeVisible();
    expect(await sideScroll(page), "after a turn").toBeLessThanOrEqual(0);

    // The Desk is a landscape surface: approve there, then look again at this size.
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.getByTestId("resolve-button").click();
    await review(page, "approve");
    await expect(page.getByTestId("flag-card")).toBeVisible();
    await page.setViewportSize(viewport);
    expect(await sideScroll(page), "after Approve").toBeLessThanOrEqual(0);

    for (const chip of await page.getByTestId("constructed-scenario-chip").all()) {
      if (!(await chip.isVisible())) continue; // a pane this size does not show
      await chip.hover();
      const tip = chip.locator('[role="tooltip"]');
      await expect(tip).toBeVisible();
      const box = (await tip.boundingBox())!;
      expect(box.x, "tooltip starts inside the window").toBeGreaterThanOrEqual(0);
      expect(box.x + box.width, "tooltip ends inside the window").toBeLessThanOrEqual(viewport.width);
      expect(await sideScroll(page), "with a tooltip open").toBeLessThanOrEqual(0);
    }
  });
}

test("FrontDesk registrar: with reduced motion the flag notice fades in place, without rising", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await heldCheckIn(page);
  await page.getByTestId("resolve-button").click();
  await review(page, "approve");
  const card = page.getByTestId("flag-card").locator(".org-notice-card");
  await expect(card).toBeVisible();
  // Under reduced motion the morph is a crossfade (record/motion.ts): no rise, no clip, at any frame.
  const style = await card.evaluate((el) => {
    const s = getComputedStyle(el);
    return { transform: s.transform, clipPath: s.clipPath };
  });
  expect(style).toEqual({ transform: "none", clipPath: "none" });
});

test("FrontDesk Start over: a new check-in starts at once and the next message is sent", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Use this" }).click();
  await page.keyboard.press("Enter");
  await expect(page.locator('[data-kiosk="held"]')).toHaveCount(1);
  await page.getByRole("button", { name: "Start over" }).click();
  await expect(page.getByTestId("kiosk")).toHaveAttribute("data-k", "idle");
  await expect(page.locator('[data-kiosk="idle"]')).toHaveCount(1);
  await page.getByTestId("kiosk-composer").fill("I have an appointment at three.");
  await expect(page.getByTestId("kiosk-send")).toBeEnabled();
  await page.getByTestId("kiosk-send").click();
  await expect(page.getByText("automatic message")).toBeVisible();
  await expect(page.getByTestId("kiosk-start-error")).toHaveCount(0);
  await expect(page.getByText("could not reach the agent service")).toHaveCount(0);
});

test("FrontDesk Reset demo: clears the kiosk and the held check-in; the next message starts a new check-in", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Use this" }).click();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("gate-card")).toBeVisible();
  await expect(page.locator('[data-kiosk="held"]')).toHaveCount(1);
  await page.getByRole("button", { name: "Reset demo" }).click();
  await expect(page.getByTestId("kiosk")).toHaveAttribute("data-k", "idle");
  await expect(page.getByTestId("gate-card")).toHaveCount(0);
  await expect(page.locator('[data-kiosk="held"]')).toHaveCount(0);
  await page.getByRole("button", { name: "Use this" }).click();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("gate-card")).toBeVisible();
  await expect(page.locator('[data-kiosk="held"]')).toHaveCount(1);
  await expect(page.getByText("could not reach the agent service")).toHaveCount(0);
});

test("FrontDesk tool chips carry no mode-specific suffix", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Use this" }).click();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("tool-call-chip")).toHaveCount(2);
  await expect(page.getByTestId("tool-call-chip").filter({ hasText: "recorded" })).toHaveCount(0);
});

test("FrontDesk: other text gets the template answer and no tool runs", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("kiosk-composer").fill("I have an appointment at three.");
  await page.getByTestId("kiosk-send").click();
  await expect(page.getByText("automatic message")).toBeVisible();
  await expect(page.getByTestId("tool-call-chip")).toHaveCount(0);
  await expect(page.getByTestId("gate-card")).toHaveCount(0);
});

for (const scheme of ["light", "dark"] as const) {
  test(`nothing on either screen renders in red (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    for (const route of ["/", "/frontdesk"]) {
      await page.goto(route);
      await page.getByRole("button", { name: "Reset demo" }).waitFor();
      if (route === "/") await page.getByTestId("resolve-button").click();
      const reds = await page.evaluate(() => {
        const isRed = (css: string) => {
          const m = css.match(/rgba?\((\d+), (\d+), (\d+)/);
          if (!m) return false;
          const [r, g, b] = m.slice(1).map(Number);
          return r > 150 && g < 90 && b < 90;
        };
        return [...document.querySelectorAll("*")]
          .filter((el) => {
            const s = getComputedStyle(el);
            return [s.color, s.backgroundColor, s.borderTopColor, s.borderLeftColor].some(isRed);
          })
          .map((el) => el.outerHTML.slice(0, 80));
      });
      expect(reds, route).toEqual([]);
      // The colour tokens themselves, not just what the fixture happens to draw: the record's
      // mulberry family, the working glow, the gate's amber and the ink the evidence is drawn in.
      const tokens = await page.evaluate(() => {
        const cs = getComputedStyle(document.documentElement);
        return [
          "--mulberry",
          "--mulberry-deep",
          "--mulberry-tint",
          "--mulberry-cite",
          "--glow",
          "--amber-surface",
          "--amber-line",
          "--amber-ink",
          "--ink",
          "--ink-3",
        ].map((name) => cs.getPropertyValue(name).trim());
      });
      for (const token of tokens) {
        const m = token.match(/^#([0-9a-f]{6})$/i);
        expect(m, `${token} is a hex token`).not.toBeNull();
        const n = parseInt(m![1], 16);
        const [r, g, b] = [n >> 16, (n >> 8) & 255, n & 255];
        expect(r > 150 && g < 90 && b < 90, `${token} is not red`).toBe(false);
      }
    }
  });
}
