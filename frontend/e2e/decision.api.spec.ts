import { expect, test, type APIRequestContext } from "@playwright/test";
import { requireApiOrigin } from "./apiOrigin";

// BUILD-SPEC decision 1 on the real API: one Confirm records the ER/Clinic link and attaches the
// kiosk's held check-in as a second approval. The rule raises its flag once, the kiosk reaches its
// done state, and the event log shows one LINK_APPROVED per link. Presses Reset demo on the API.
const API = requireApiOrigin(process.env);

async function apiClock(request: APIRequestContext): Promise<string> {
  const res = await request.get(`${API}/api/v1/health`);
  return new Date(res.headers()["date"]).toISOString().replace("Z", "+00:00");
}

async function eventCounts(request: APIRequestContext, since: string): Promise<Record<string, number>> {
  const counts: Record<string, number> = {};
  let cursor: string | null = null;
  do {
    const query = `since=${encodeURIComponent(since)}&limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`;
    const body = (await (await request.get(`${API}/api/v1/events?${query}`)).json()) as {
      items: { eventType: string }[];
      nextCursor: string | null;
    };
    for (const row of body.items) counts[row.eventType] = (counts[row.eventType] ?? 0) + 1;
    cursor = body.nextCursor;
  } while (cursor);
  return counts;
}

test("one Confirm links the records and attaches the held check-in: one flag, kiosk done", async ({
  page,
  request,
}) => {
  test.setTimeout(150_000);
  await page.goto("/");
  const reset = page.waitForResponse(
    (r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/v1/sessions",
    { timeout: 60_000 },
  );
  await page.getByTestId("reset-button").click();
  await reset;
  await expect(page.getByTestId("source-card")).toHaveCount(2);

  // The kiosk check-in: the demo line, sent once; the gate holds it for a registrar.
  // Send stays disabled until the composer has text; "Use this" fills it with the demo line.
  await expect(page.getByRole("button", { name: "Use this" }).first()).toBeEnabled({ timeout: 30_000 });
  await page.getByRole("button", { name: "Use this" }).first().click();
  await expect(page.getByTestId("kiosk-send")).toBeEnabled();
  await page.getByTestId("kiosk-send").click();
  await expect(page.locator('[data-pane="held"]')).toBeVisible({ timeout: 30_000 });

  // Approve sits beside the held check-in, in view without scrolling the window.
  await page.getByTestId("resolve-button").click();
  await expect(page.getByTestId("pair-band")).toHaveText(/REVIEW/);
  await expect(page.getByTestId("approve-button")).toBeInViewport();
  expect(await page.evaluate(() => window.scrollY)).toBe(0);

  const since = await apiClock(request);
  await page.getByTestId("approve-button").click();
  const attach = page.getByTestId("attach-checkin");
  await expect(attach).toBeChecked();
  await expect(page.getByText("Also attach the kiosk check-in")).toBeVisible();
  await page.getByTestId("review-note-input").fill("decision 1: link and attach the check-in");
  await expect(page.getByTestId("review-submit-button")).toBeInViewport();
  await page.getByTestId("review-submit-button").click();

  await expect(page.getByTestId("golden-record")).toBeVisible();
  await expect(page.getByTestId("flag-card")).toHaveCount(1);
  // The kiosk's done state (L2): "You’re checked in, <name>."
  await expect(page.getByTestId("kiosk")).toHaveAttribute("data-k", "done", { timeout: 15_000 });
  await expect(page.getByTestId("kiosk")).toContainText("You’re checked in");
  await expect(page.getByTestId("attach-checkin-button")).toHaveCount(0);

  await expect
    .poll(async () => {
      const counts = await eventCounts(request, since);
      return { approved: counts.LINK_APPROVED ?? 0, alerts: counts.ALERT_RAISED ?? 0 };
    })
    .toEqual({ approved: 2, alerts: 1 });
});
