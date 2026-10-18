import { expect, test } from "@playwright/test";

// Run by `npm run e2e:api` against the API-mode build and an API in REPLAY with the corpus hero.
// It presses Reset demo on that API; the config refuses to run unless CHECKMATE_API_ORIGIN names it.
// The hero hands two pairs to the registrar (the ER chart and the Clinic chart). Only the approval
// that joins the allergy to the order raises the flag, and only that pair shows the summary.
const RESET_MS = 90_000;
test.setTimeout(240_000);
test.use({ viewport: { width: 1280, height: 720 } });

const isReset = (url: string, method: string) =>
  method === "POST" && new URL(url).pathname === "/api/v1/sessions";
const isReview = (url: string) => /\/candidate-pairs\/[^/]+\/reviews$/.test(new URL(url).pathname);

test("approving both held pairs: the approval that raises the flag shows it, and Open case shows the card", async ({
  page,
}) => {
  await page.goto("/frontdesk");
  await expect(page.getByTestId("agent-mode-badge")).toBeVisible();
  const reset = page.waitForResponse((r) => isReset(r.url(), r.request().method()), { timeout: RESET_MS });
  await page.getByTestId("reset-button").click();
  await reset;
  await page.getByRole("button", { name: "Use this" }).click();
  await page.getByTestId("kiosk-send").click();
  const held = page.getByTestId("registrar-held");
  await expect(held).toContainText("Held check-ins (2)", { timeout: 30_000 });
  await expect(held.getByTestId("registrar-flag-summary")).toHaveCount(0);

  const raisedBy: string[] = [];
  for (let i = 0; i < 2; i++) {
    await held.getByTestId("approve-button").first().click();
    const [res] = await Promise.all([
      page.waitForResponse((r) => isReview(r.url()), { timeout: 30_000 }),
      held.getByTestId("review-submit-button").click(),
    ]);
    const body = (await res.json()) as { decision: { pairId: string; status: string }; alerts?: unknown[] };
    expect(body.decision.status).toBe("LINKED");
    if (body.alerts?.length) raisedBy.push(body.decision.pairId);
    await expect(held.getByText(/Approved by /)).toHaveCount(i + 1);
  }
  expect(raisedBy, "exactly one of the two approvals raises the flag").toHaveLength(1);

  const summary = held.getByTestId("registrar-flag-summary");
  await expect(summary).toHaveCount(1);
  const headline = summary.getByTestId("registrar-flag-headline");
  // Read from the API's alert: an allergy with its reaction, an active order, each with its source.
  await expect(headline).toHaveText(/^\S.* allergy \(.+\) from .+ · active \S.* order from .+$/);
  await expect(headline).not.toContainText("Documented allergy");
  await expect(summary.getByTestId("registrar-flag-count")).toHaveText("1 safety flag on the linked chart");
  const openCase = summary.getByRole("link", { name: "Open case" });
  await expect(openCase).toBeFocused();
  await expect(summary).toBeInViewport();
  await expect(page.getByRole("status")).toContainText("Link approved. Flagged for clinician review:");
  await expect(summary.locator("[aria-live], [role=alert], [role=status]")).toHaveCount(0);
  // Nothing in the summary widens the page (the chip's tooltip once ran 23 px past the edge).
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth),
  ).toBeLessThanOrEqual(0);
  const text = ((await headline.textContent()) ?? "").trim();

  await openCase.click();
  await expect(page).toHaveURL(new RegExp(`/queue/${raisedBy[0]}$`));
  const flag = page.getByTestId("flag-card");
  await expect(flag).toBeVisible({ timeout: 30_000 });
  await expect(flag.getByTestId("flag-card-headline")).toHaveText(text);
  await expect(page.getByTestId("flag-card-rule-id")).toHaveText("BL-AMOX-01");
  await expect(flag.getByText("Details", { exact: true })).toBeVisible();
});
