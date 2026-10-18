import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

// Runs against the fixture adapter (the default data source).
const scenario = JSON.parse(
  readFileSync(path.join(__dirname, "../../contracts/fixtures/scenario.json"), "utf8"),
);

const reviewPanel = (page: Page) => page.getByRole("region", { name: "Review" });

/** Reset, then Resolve: the pair panel waits for Resolve identity, as the G16 path does. */
async function resolved(page: Page) {
  await page.goto("/");
  await page.getByTestId("reset-button").click();
  await page.getByTestId("resolve-button").click();
  await expect(page.getByTestId("candidate-pair")).toBeVisible();
}

async function review(page: Page, kind: "approve" | "reject", reason?: string, note = "") {
  await page.getByTestId(kind === "approve" ? "approve-button" : "reject-button").click();
  if (reason) await page.getByTestId("review-reason-select").selectOption(reason);
  if (note) await page.getByTestId("review-note-input").fill(note);
  await page.getByTestId("review-submit-button").click();
}

test("case path: reject keeps the rule silent, then approve links and flags", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Synthetic data. Not for clinical use.")).toBeVisible();
  await expect(page.getByTestId("app-mode-badge")).toHaveText(/REPLAY/);
  await expect(page.getByTestId("source-card")).toHaveCount(2);
  await expect(page.getByTestId("candidate-pair")).toHaveCount(0);
  await page.getByTestId("resolve-button").click();
  await expect(page.getByTestId("candidate-pair")).toBeVisible();
  await expect(page.getByTestId("pair-band")).toHaveText(/REVIEW/);

  const er = page.getByRole("article", { name: "ER FHIR record" });
  await expect(er).toBeVisible();
  await expect(er.getByText("constructed scenario")).toBeVisible();
  await expect(page.getByRole("article", { name: "Clinic CSV record" })).toBeVisible();
  await expect(
    page.getByText("Probability estimate fitted on our synthetic development distribution"),
  ).toBeVisible();
  await expect(page.getByRole("list", { name: "Top evidence" }).getByRole("listitem")).toHaveCount(5);
  await expect(page.getByText("No safety check yet. It runs after a link is approved.")).toBeVisible();

  await reviewPanel(page).getByLabel("Registrar").selectOption("Registrar B");
  await review(page, "reject", "DIFFERENT_PERSON");
  await expect(
    page.getByText(/Rejected by Registrar B at \d\d:\d\d:\d\d CT\. Reason: Different person\./),
  ).toBeVisible();
  await expect(page.getByText("No safety check ran: no link was approved.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Flagged for clinician review" })).toHaveCount(0);
  await expect(page.locator('[data-testid="event-row"][data-event-type="LINK_REJECTED"]')).toHaveCount(1);

  await review(page, "approve", undefined, "second review approves");
  const golden = page.getByRole("heading", { name: "Golden record" });
  await expect(golden).toBeFocused();
  const goldenRegion = page.getByRole("region", { name: "Golden record" });
  await expect(goldenRegion.getByText("Clinic CSV").first()).toBeVisible();
  await expect(goldenRegion.getByText("ER FHIR").first()).toBeVisible();
  await expect(page.getByRole("article", { name: "ER FHIR record" })).toHaveCount(0);

  const timeline = page.getByRole("region", { name: "Timeline" });
  for (const event of scenario.timelineIfApproved) {
    await expect(timeline.getByText(event.display)).toBeVisible();
  }

  const flag = page.getByRole("article", { name: "Flagged for clinician review" });
  await expect(flag).toBeVisible();
  await expect(flag.getByText("constructed scenario")).toBeVisible();
  await expect(flag.getByText(scenario.alertIfApproved.cardFooter)).toBeVisible();
  await expect(page.getByTestId("flag-card-rule-id")).toHaveText("BL-AMOX-01");
  await expect(flag.getByTestId("constructed-scenario-chip")).toBeVisible();
  expect(await page.getByTestId("crosswalk-chip").count()).toBeGreaterThan(0);
  await expect(page.locator('[data-testid="timeline-event"][data-source-system="ER_FHIR"]')).not.toHaveCount(
    0,
  );
  await expect(page.locator('[data-testid="event-row"][data-event-type="LINK_APPROVED"]')).toHaveCount(1);
  await expect(page.locator('[data-testid="event-row"][data-event-type="ALERT_RAISED"]')).toHaveCount(1);
  await expect(page.getByTestId("tile-human-review-total")).toHaveText("2");
  await expect(page.getByText(/Approved by Registrar B at \d\d:\d\d:\d\d CT\./)).toBeVisible();
  // Scoped to main: Next.js keeps its own empty route announcer outside it.
  await expect(page.locator('main [role="alert"]')).toHaveCount(0);
});

test("after Approve the flag card is on screen, under the golden record and above the timeline", async ({
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
  expect(flagBox!.y).toBeLessThan(timelineBox!.y);
});

test("reject without a reason asks for one and records nothing", async ({ page }) => {
  await resolved(page);
  await page.getByTestId("reject-button").click();
  await page.getByTestId("review-submit-button").click();
  await expect(page.getByText("Select a reason to reject the link.")).toBeVisible();
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
  await expect(page.getByRole("heading", { name: "Golden record" })).toBeVisible();

  await page.getByRole("button", { name: "Reset demo" }).click();
  await expect(page.getByRole("article", { name: "ER FHIR record" })).toBeVisible();
  await page.getByRole("button", { name: "Undo reset" }).click();
  const golden = page.getByRole("heading", { name: "Golden record" });
  await expect(golden).toBeVisible();
  // Focus moves to the golden record only after an approval made here, not after Undo.
  await expect(golden).not.toBeFocused();
});

test("keyboard path reaches Approve link and moves focus to the golden record", async ({ page }) => {
  await resolved(page);
  const approve = page.getByTestId("approve-button");
  for (let i = 0; i < 60 && !(await approve.evaluate((el) => el === document.activeElement)); i++) {
    await page.keyboard.press("Tab");
  }
  await expect(approve).toBeFocused();
  await page.keyboard.press("Enter");
  // The dialog opens with focus on the note; Enter in the form submits it.
  await expect(page.getByTestId("review-note-input")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Golden record" })).toBeFocused();
});

test("FrontDesk shell: empty chat pane, ES/EN switch and the agent gate tile", async ({ page }) => {
  await page.goto("/frontdesk");
  await expect(page.getByText("Your conversation will appear here.")).toBeVisible();
  await page.getByRole("button", { name: "Español" }).click();
  await expect(page.getByText("Le damos la bienvenida. Registremos su llegada.")).toBeVisible();
  await expect(page.getByRole("region", { name: "Conversación de registro" })).toBeVisible();
  await expect(page.locator('section[lang="es"]')).toHaveCount(1);
  await page.getByRole("button", { name: "English" }).click();
  await expect(page.getByText("Welcome. Let's get you checked in.")).toBeVisible();

  const tile = page.getByRole("region", { name: "Agent actions per 5 minutes" });
  await expect(tile.getByText("No agent actions yet.")).toBeVisible();
  // The caption names the aggregate only; it never changes with the data source's mode.
  await expect(tile.getByText("agent_gate_5m · continuous aggregate", { exact: true })).toBeVisible();
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
      // The evidence tokens themselves, not just the bars the fixture happens to draw.
      const tokens = await page.evaluate(() => {
        const cs = getComputedStyle(document.documentElement);
        return ["--evidence-against", "--evidence-for"].map((name) => cs.getPropertyValue(name).trim());
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
