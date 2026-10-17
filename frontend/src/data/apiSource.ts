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
import { DataError, EVENT_FEED_ROWS, type CaseData, type DataSource } from "./source";

const SCENARIO_ID = "hero";
const LIST_LIMIT_MAX = 200; // the frozen contract's bound; a larger value is a 422
// recordId narrows the queue to pairs that include the session's first record; a handful of
// pages is already far more than one record can be paired with. Past that, ask for a reset.
const HERO_PAGES_MAX = 10;
const NO_SESSION_MESSAGE = "No demo session yet. Press Reset demo to load the demo patient.";

type PairSummary = { id: string; recordAId: string; recordBId: string };

function fail(error: unknown): never {
  const envelope = error as Partial<ErrorEnvelope> | undefined;
  const body = envelope?.error;
  throw new DataError(body?.code ?? "UPSTREAM_UNAVAILABLE", body?.message ?? "The API did not answer.");
}

/** Calls FastAPI through the same-origin /api/v1 rewrite in next.config.ts.
 *
 * Postgres is the source of truth: the session comes from POST /sessions or, after a reload,
 * GET /sessions/current, and the pair, entity, timeline and alerts are read back from the API,
 * so a reload shows the same screen. The hero is always the pair built from the session's two
 * source records; no other pair is ever shown in its place. */
export class ApiSource implements DataSource {
  readonly mode = "LOCAL" as const;
  readonly canRestore = false; // the contract has no restore route
  private readonly client: ReturnType<typeof createClient<paths>>;
  // The last session this tab saw: used only while GET /sessions/current is a 501 stub.
  private session: SessionResponse | null = null;
  private pendingSession: Promise<SessionResponse | null> | null = null;

  /** `baseUrl` stays "" in the browser (same origin); tests pass an absolute origin. */
  constructor(baseUrl = "") {
    this.client = createClient<paths>({ baseUrl });
  }

  /** The API's current session, re-read on every call so a reset made in another tab is
   * followed; callers asking at the same time share one request. null before any reset (404). */
  getSession(): Promise<SessionResponse | null> {
    this.pendingSession ??= this.readCurrentSession().finally(() => {
      this.pendingSession = null;
    });
    return this.pendingSession;
  }

  private async readCurrentSession(): Promise<SessionResponse | null> {
    const res = await this.client.GET("/api/v1/sessions/current");
    if (res.response.status === 404) return null;
    if (res.response.status === 501) return this.session; // route not implemented: this tab's memory
    if (!res.data) fail(res.error);
    this.session = res.data;
    return res.data;
  }

  async getCase(): Promise<CaseData> {
    const session = await this.getSession();
    if (!session) throw new DataError("NO_SESSION", NO_SESSION_MESSAGE);
    const { sources } = session;
    const hero = await this.heroPair(sources.map((s) => s.record.id));
    // Until Resolve identity queues the session's pair, the screen shows the cards alone.
    if (!hero) return { sources, detail: null, outcome: null, resolved: false, alertsKnown: true };
    const detail = await this.client.GET("/api/v1/candidate-pairs/{pair_id}", {
      params: { path: { pair_id: hero.id } },
    });
    if (!detail.data) fail(detail.error);
    const { outcome, alertsKnown } = await this.outcomeFor(detail.data);
    return { sources, detail: detail.data, outcome, resolved: true, alertsKnown };
  }

  async resolve(): Promise<void> {
    const res = await this.client.POST("/api/v1/match-runs");
    if (!res.data) fail(res.error);
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

  /** One page of the feed, newest first; the event log is never walked in full. */
  async getEvents(): Promise<EventLogRow[]> {
    const res = await this.client.GET("/api/v1/events", { params: { query: { limit: EVENT_FEED_ROWS } } });
    if (!res.data) fail(res.error);
    return res.data.items;
  }

  async getTiles() {
    const res = await this.client.GET("/api/v1/metrics/tiles");
    if (!res.data) fail(res.error);
    return res.data;
  }

  async reset() {
    const res = await this.client.POST("/api/v1/sessions", { body: { scenarioId: SCENARIO_ID } });
    if (!res.data) fail(res.error);
    this.session = res.data;
    return res.data;
  }

  async restore(): Promise<void> {
    throw new DataError("NOT_IMPLEMENTED", "Undo is not available from the API yet.");
  }

  /** The match-run pair whose records are exactly the session's first and second source, found
   * through the recordId filter and its cursor; null when it is not queued (never another pair).
   * Running out of pages is reported as a reset prompt rather than "not queued". */
  private async heroPair(recordIds: string[]): Promise<PairSummary | null> {
    const [first, second] = recordIds;
    if (!first || !second) return null;
    let cursor: string | null | undefined;
    for (let page = 0; page < HERO_PAGES_MAX; page++) {
      const res = await this.client.GET("/api/v1/candidate-pairs", {
        params: {
          query: {
            recordId: first,
            origin: "MATCH_RUN",
            limit: LIST_LIMIT_MAX,
            ...(cursor ? { cursor } : {}),
          },
        },
      });
      if (!res.data) fail(res.error);
      const hero = res.data.items.find(
        (p) =>
          (p.recordAId === first && p.recordBId === second) ||
          (p.recordAId === second && p.recordBId === first),
      );
      if (hero) return hero;
      cursor = res.data.nextCursor;
      if (!cursor) return null;
    }
    throw new DataError("NO_SESSION", NO_SESSION_MESSAGE);
  }

  /** The entity and alerts of a LINKED pair, read from the API so a reload shows the same state.
   * A failed or unavailable alerts read is reported as unknown, never as "no flag". */
  private async outcomeFor(
    detail: CandidatePairDetail,
  ): Promise<{ outcome: ReviewResponse | null; alertsKnown: boolean }> {
    const { decision } = detail.pair;
    const entityId = detail.mergePreview.entityIdIfApproved;
    if (decision.status !== "LINKED" || !entityId) return { outcome: null, alertsKnown: true };
    const res = await this.client.GET("/api/v1/entities/{entity_id}", {
      params: { path: { entity_id: entityId } },
    });
    if (!res.data) return { outcome: null, alertsKnown: false }; // 501 until the read side lands, 404 if the entity moved
    const alerts = await this.getAlerts(res.data.id).catch(() => null);
    return { outcome: { decision, entity: res.data, alerts: alerts ?? [] }, alertsKnown: alerts !== null };
  }
}
