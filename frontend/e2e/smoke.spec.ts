import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

// Runs against the fixture adapter (the default data source).
const scenario = JSON.parse(
  readFileSync(path.join(__dirname, "../../contracts/fixtures/scenario.json"), "utf8"),
);

const reviewPanel = (page: Page) => page.getByRole("region", { name: "Review" });

test("case path: reject keeps the rule silent, then approve links and flags", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Synthetic data. Not for clinical use.")).toBeVisible();
  await expect(page.getByText("REPLAY", { exact: true })).toBeVisible();

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
  await reviewPanel(page).getByLabel("Reason").selectOption({ label: "Different person" });
  await page.getByRole("button", { name: "Reject link" }).click();
  await expect(
    page.getByText(/Rejected by Registrar B at \d\d:\d\d:\d\d CT\. Reason: Different person\./),
  ).toBeVisible();
  await expect(page.getByText("No safety check ran: no link was approved.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Flagged for clinician review" })).toHaveCount(0);

  await page.getByRole("button", { name: "Approve link" }).click();
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
  await expect(page.getByText(/Approved by Registrar B at \d\d:\d\d:\d\d CT\./)).toBeVisible();
  // Scoped to main: Next.js keeps its own empty route announcer outside it.
  await expect(page.locator('main [role="alert"]')).toHaveCount(0);
});

test("reject without a reason asks for one and records nothing", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Reject link" }).click();
  await expect(page.getByText("Select a reason to reject the link.")).toBeVisible();
  await expect(reviewPanel(page).getByLabel("Reason")).toBeFocused();
  await expect(page.getByText(/Rejected by/)).toHaveCount(0);
});

test("reset returns to the separate records and Undo reset brings the link back", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Approve link" }).click();
  await expect(page.getByRole("heading", { name: "Golden record" })).toBeVisible();

  await page.getByRole("button", { name: "Reset demo" }).click();
  await expect(page.getByRole("article", { name: "ER FHIR record" })).toBeVisible();
  await page.getByRole("button", { name: "Undo reset" }).click();
  await expect(page.getByRole("heading", { name: "Golden record" })).toBeVisible();
});

test("keyboard path reaches Approve link and moves focus to the golden record", async ({ page }) => {
  await page.goto("/");
  const approve = page.getByRole("button", { name: "Approve link" });
  for (let i = 0; i < 40 && !(await approve.evaluate((el) => el === document.activeElement)); i++) {
    await page.keyboard.press("Tab");
  }
  await expect(approve).toBeFocused();
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
  await expect(tile.getByText(/agent_gate_5m · continuous aggregate · recorded log/)).toBeVisible();
});

test("nothing on either screen renders in red", async ({ page }) => {
  for (const route of ["/", "/frontdesk"]) {
    await page.goto(route);
    await page.getByRole("button", { name: "Reset demo" }).waitFor();
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
  }
});
