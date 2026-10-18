import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

const scenario = JSON.parse(
  readFileSync(path.join(__dirname, "../../contracts/fixtures/scenario.json"), "utf8"),
);
const pairId = "00000000-0000-4000-8000-000000000099";
const nonHero = {
  ...scenario.pair,
  pair: {
    ...scenario.pair.pair,
    id: pairId,
    decision: {
      ...scenario.pair.pair.decision,
      pairId,
      p: 0.61,
      status: "PROPOSED",
      band: "REVIEW",
    },
  },
};

test("opens a non-hero pair from the real work-queue flow", async ({ page }) => {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "POST" && url.pathname === "/api/v1/match-runs") {
      return route.fulfill({
        status: 201,
        json: {
          runId: "00000000-0000-4000-8000-000000000096",
          records: 1161,
          entities: 555,
          allPairs: 673380,
          candidatePairs: 1163,
          reductionRatio: 0.9983,
          bandCounts: { AUTO_LINK: 31, REVIEW: 742, KEEP_SEPARATE: 390 },
          pairsSkippedOversized: 0,
          scorerVersion: "test",
          thresholdSetId: "test",
          elapsedMs: 84,
        },
      });
    }
    if (request.method() === "GET" && url.pathname === "/api/v1/candidate-pairs") {
      return route.fulfill({ json: { items: [nonHero.pair], nextCursor: "next" } });
    }
    if (request.method() === "GET" && url.pathname === `/api/v1/candidate-pairs/${pairId}`) {
      return route.fulfill({ json: nonHero });
    }
    return route.fulfill({ status: 404, json: { error: { code: "NOT_FOUND", message: "not mocked" } } });
  });

  await page.goto("/queue");
  await expect(page.getByText("673,380 all possible pairs")).toBeVisible();
  const nonHeroRow = page.getByTestId("work-queue-row");
  await expect(nonHeroRow).toContainText("61.0%");
  await nonHeroRow.click();
  await expect(page).toHaveURL(new RegExp(`/queue/${pairId}$`));
  await expect(page.getByTestId("candidate-pair")).toBeVisible();
  await expect(page.getByRole("article", { name: "ER FHIR record" })).toBeVisible();
  await expect(page.getByTestId("approve-button")).toBeVisible();
  await expect(page.getByTestId("reject-button")).toBeVisible();
});
