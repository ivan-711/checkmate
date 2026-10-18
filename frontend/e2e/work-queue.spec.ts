import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

// Runs against the fixture adapter (REPLAY), with no API behind it and nothing mocked: the queue
// must read the same source as Case, so any /api/v1 request here is a failure.
const scenario = JSON.parse(
  readFileSync(path.join(__dirname, "../../contracts/fixtures/scenario.json"), "utf8"),
);
const pairId: string = scenario.pair.pair.id;

function apiRequests(page: Page): string[] {
  const seen: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/v1/"))
      seen.push(`${request.method()} ${request.url()}`);
  });
  return seen;
}

const tab = (page: Page, name: string) =>
  page.getByRole("navigation", { name: "Main" }).getByRole("link", { name });

test("REPLAY: the queue reads the fixture and Case keeps its golden record across tabs", async ({ page }) => {
  const api = apiRequests(page);
  await page.goto("/");
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link")).toHaveText([
    "FrontDesk",
    "Case",
    "Work queue",
  ]);
  await page.getByTestId("resolve-button").click();
  await page.getByTestId("approve-button").click();
  await page.getByTestId("review-note-input").fill("work queue round trip");
  await page.getByTestId("review-submit-button").click();
  await expect(page.getByRole("heading", { name: "Golden record" })).toBeVisible();

  await tab(page, "Work queue").click();
  await expect(page).toHaveURL(/\/queue$/);
  await expect(page.getByTestId("app-mode-badge")).toHaveText(/REPLAY/);
  await expect(page.getByTestId("work-queue-no-funnel")).toHaveText(/REPLAY has no match-run funnel/);
  const columns = page.getByTestId("work-queue-columns");
  await expect(columns).toContainText("Probability estimate");
  await expect(columns).toContainText("fitted on our synthetic development distribution");
  const row = page.getByTestId("work-queue-row");
  await expect(row).toHaveCount(1);
  await expect(row).toContainText(scenario.pair.pair.decision.p.toFixed(2));
  await expect(row).toContainText("Linked");
  await expect(row).not.toContainText("%");

  await tab(page, "Case").click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Golden record" })).toBeVisible();
  await expect(page.getByRole("article", { name: "ER FHIR record" })).toHaveCount(0);
  expect(api).toEqual([]);
});

test("REPLAY: a queue row opens Case for that pair", async ({ page }) => {
  const api = apiRequests(page);
  await page.goto("/");
  await expect(page.getByTestId("candidate-pair")).toHaveCount(0);
  await tab(page, "Work queue").click();
  await expect(
    page.getByText("No candidate pairs yet. Resolve identity on Case scores the loaded records."),
  ).toBeVisible();

  await tab(page, "Case").click();
  await page.getByTestId("resolve-button").click();
  await expect(page.getByTestId("candidate-pair")).toBeVisible();
  await tab(page, "Work queue").click();
  await page.getByTestId("work-queue-row").click();
  await expect(page).toHaveURL(new RegExp(`/queue/${pairId}$`));
  await expect(page.getByTestId("candidate-pair")).toBeVisible();
  await expect(page.getByRole("article", { name: "ER FHIR record" })).toBeVisible();
  await expect(page.getByTestId("approve-button")).toBeVisible();
  await expect(page.getByTestId("reject-button")).toBeVisible();
  expect(api).toEqual([]);
});
