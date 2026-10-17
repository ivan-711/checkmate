import createClient from "openapi-fetch";
import type { paths } from "@/api/schema";
import type { ErrorEnvelope, ReviewRequest, ReviewResponse, TimelineEvent } from "@/api/types";
import { DataError, type CaseData, type DataSource } from "./source";

const SCENARIO_ID = "hero";

function fail(error: unknown): never {
  const envelope = error as Partial<ErrorEnvelope> | undefined;
  const body = envelope?.error;
  throw new DataError(body?.code ?? "UPSTREAM_UNAVAILABLE", body?.message ?? "The API did not answer.");
}

/** Calls FastAPI through the same-origin /api/v1 rewrite in next.config.ts. */
export class ApiSource implements DataSource {
  readonly mode = "LOCAL" as const;
  readonly canRestore = false; // the contract has no restore route
  private readonly client = createClient<paths>({ baseUrl: "" });
  // The alerts and timeline routes are stubs (501) until W3b lands, so the outcome of a
  // review made in this tab is kept until the page reloads; after a reload only the
  // decision line shows. Wiring those routes is part of the switch to the real API.
  private lastOutcome: ReviewResponse | null = null;

  async getCase(): Promise<CaseData> {
    const list = await this.client.GET("/api/v1/candidate-pairs", {
      params: { query: { origin: "MATCH_RUN", limit: 1 } },
    });
    if (!list.data) fail(list.error);
    const first = list.data.items[0];
    if (!first) throw new DataError("NOT_FOUND", "No candidate pair is queued.");
    const detail = await this.client.GET("/api/v1/candidate-pairs/{pair_id}", {
      params: { path: { pair_id: first.id } },
    });
    if (!detail.data) fail(detail.error);
    const current = detail.data.pair.decision.id;
    const outcome = this.lastOutcome?.decision.id === current ? this.lastOutcome : null;
    return { detail: detail.data, outcome };
  }

  async review(pairId: string, body: ReviewRequest, idempotencyKey: string): Promise<ReviewResponse> {
    const res = await this.client.POST("/api/v1/candidate-pairs/{pair_id}/reviews", {
      params: { path: { pair_id: pairId }, header: { "Idempotency-Key": idempotencyKey } },
      body,
    });
    if (!res.data) fail(res.error);
    this.lastOutcome = res.data;
    return res.data;
  }

  async getTimeline(): Promise<TimelineEvent[] | null> {
    return null; // the timeline route is a stub until W3b lands
  }

  async getTiles() {
    const res = await this.client.GET("/api/v1/metrics/tiles");
    if (!res.data) fail(res.error);
    return res.data;
  }

  async reset() {
    const res = await this.client.POST("/api/v1/sessions", { body: { scenarioId: SCENARIO_ID } });
    if (!res.data) fail(res.error);
    this.lastOutcome = null;
    return res.data;
  }

  async restore(): Promise<void> {
    throw new DataError("NOT_IMPLEMENTED", "Undo is not available from the API yet.");
  }
}
