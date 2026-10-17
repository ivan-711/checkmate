import createClient from "openapi-fetch";
import type { paths } from "@/api/schema";
import type {
  CandidatePairDetail,
  ErrorEnvelope,
  EventLogRow,
  ReviewRequest,
  ReviewResponse,
  SafetyAlert,
  SessionResponse,
  TimelineEvent,
} from "@/api/types";
import { DataError, type CaseData, type DataSource } from "./source";

const SCENARIO_ID = "hero";
const LIST_LIMIT_MAX = 200; // the frozen contract's bound; a larger value is a 422
const EVENT_PAGES_MAX = 50;

function fail(error: unknown): never {
  const envelope = error as Partial<ErrorEnvelope> | undefined;
  const body = envelope?.error;
  throw new DataError(body?.code ?? "UPSTREAM_UNAVAILABLE", body?.message ?? "The API did not answer.");
}

/** Calls FastAPI through the same-origin /api/v1 rewrite in next.config.ts.
 *
 * Postgres is the source of truth: after a review the pair, entity, timeline and alerts are
 * read back from the API, never kept in this tab, so a reload shows the same screen. The only
 * memory here is which records the current session loaded (to bind the hero pair) and the
 * last session id; both are re-derived from the API when absent. */
export class ApiSource implements DataSource {
  readonly mode = "LOCAL" as const;
  readonly canRestore = false; // the contract has no restore route
  private readonly client: ReturnType<typeof createClient<paths>>;
  private sessionRecordIds: Set<string> | null = null;
  private session: SessionResponse | null = null;
  private resolved = false;

  /** `baseUrl` stays "" in the browser (same origin); tests pass an absolute origin. */
  constructor(baseUrl = "") {
    this.client = createClient<paths>({ baseUrl });
  }

  async getSession(): Promise<SessionResponse | null> {
    return this.session;
  }

  async getCase(): Promise<CaseData> {
    const pairs = await this.listPairs();
    const hero = this.heroPair(pairs);
    if (!hero) {
      // After a reset the queue is empty until Resolve identity runs; the cards still show.
      if (!this.session) throw new DataError("NOT_FOUND", "No session in this tab yet. Press Reset demo.");
      return { sources: this.session.sources, detail: null, outcome: null, resolved: false };
    }
    const detail = await this.client.GET("/api/v1/candidate-pairs/{pair_id}", {
      params: { path: { pair_id: hero.id } },
    });
    if (!detail.data) fail(detail.error);
    const outcome = await this.outcomeFor(detail.data);
    const sources = this.session?.sources ?? [detail.data.recordA, detail.data.recordB];
    return { sources, detail: detail.data, outcome, resolved: true };
  }

  async resolve(): Promise<void> {
    const res = await this.client.POST("/api/v1/match-runs");
    if (!res.data) fail(res.error);
    this.resolved = true;
  }

  async review(pairId: string, body: ReviewRequest, idempotencyKey: string): Promise<ReviewResponse> {
    const res = await this.client.POST("/api/v1/candidate-pairs/{pair_id}/reviews", {
      params: { path: { pair_id: pairId }, header: { "Idempotency-Key": idempotencyKey } },
      body,
    });
    if (!res.data) fail(res.error);
    return res.data;
  }

  async getTimeline(entityId: string): Promise<TimelineEvent[] | null> {
    const res = await this.client.GET("/api/v1/entities/{entity_id}/timeline", {
      params: { path: { entity_id: entityId }, query: { limit: LIST_LIMIT_MAX } },
    });
    if (res.response.status === 501) return null;
    if (!res.data) fail(res.error);
    return res.data.items;
  }

  async getAlerts(entityId: string): Promise<SafetyAlert[] | null> {
    const res = await this.client.GET("/api/v1/alerts", {
      params: { query: { entityId, limit: LIST_LIMIT_MAX } },
    });
    if (res.response.status === 501) return null;
    if (!res.data) fail(res.error);
    return res.data.items;
  }

  /** The whole feed through nextCursor, newest first. */
  async getEvents(): Promise<EventLogRow[]> {
    const rows: EventLogRow[] = [];
    let cursor: string | null | undefined;
    for (let page = 0; page < EVENT_PAGES_MAX; page++) {
      const res = await this.client.GET("/api/v1/events", {
        params: { query: { limit: LIST_LIMIT_MAX, ...(cursor ? { cursor } : {}) } },
      });
      if (!res.data) fail(res.error);
      rows.push(...res.data.items);
      cursor = res.data.nextCursor;
      if (!cursor) break;
    }
    return rows;
  }

  async getTiles() {
    const res = await this.client.GET("/api/v1/metrics/tiles");
    if (!res.data) fail(res.error);
    return res.data;
  }

  async reset() {
    const res = await this.client.POST("/api/v1/sessions", { body: { scenarioId: SCENARIO_ID } });
    if (!res.data) fail(res.error);
    this.sessionRecordIds = new Set(res.data.sources.map((s) => s.record.id));
    this.session = res.data;
    this.resolved = false;
    return res.data;
  }

  async restore(): Promise<void> {
    throw new DataError("NOT_IMPLEMENTED", "Undo is not available from the API yet.");
  }

  private async listPairs() {
    const list = await this.client.GET("/api/v1/candidate-pairs", {
      params: { query: { origin: "MATCH_RUN", limit: LIST_LIMIT_MAX } },
    });
    if (!list.data) fail(list.error);
    return list.data.items;
  }

  /** The pair whose two records are the session's hero records, never just the first queued one. */
  private heroPair(pairs: Awaited<ReturnType<ApiSource["listPairs"]>>) {
    const ids = this.sessionRecordIds;
    if (ids) {
      const bound = pairs.find((p) => ids.has(p.recordAId) && ids.has(p.recordBId));
      if (bound) return bound;
    }
    // Before any reset in this tab the session is unknown; with one hero pair loaded the
    // queue holds exactly it. More than one pair without a session is reported, not guessed.
    if (pairs.length > 1 && !ids) {
      throw new DataError("NOT_FOUND", "Several pairs are queued; press Reset demo to bind the hero.");
    }
    return pairs[0] ?? null;
  }

  /** The entity and alerts of a LINKED pair, read from the API so a reload shows the same state. */
  private async outcomeFor(detail: CandidatePairDetail): Promise<ReviewResponse | null> {
    const { decision } = detail.pair;
    if (decision.status !== "LINKED") return null;
    const entityId = detail.mergePreview.entityIdIfApproved;
    if (!entityId) return null;
    const res = await this.client.GET("/api/v1/entities/{entity_id}", {
      params: { path: { entity_id: entityId } },
    });
    if (!res.data) return null; // 501 until the read side lands, 404 if the entity moved
    const alerts = (await this.getAlerts(res.data.id)) ?? [];
    return { decision, entity: res.data, alerts };
  }
}
