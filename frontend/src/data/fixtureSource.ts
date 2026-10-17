import type {
  EventLogRow,
  EventType,
  MatchDecision,
  ReviewRequest,
  ReviewResponse,
  SafetyAlert,
  SessionResponse,
  TilesResponse,
  TimelineEvent,
} from "@/api/types";
import type { ScenarioFixture } from "./scenario";
import { DataError, EVENT_FEED_ROWS, type CaseData, type DataSource } from "./source";

interface SessionState {
  session: SessionResponse;
  /** Append-only, oldest first, like the API's decision history. */
  history: MatchDecision[];
  outcome: ReviewResponse | null;
  /** Append-only, oldest first: what the API's event_log would hold for this session. */
  events: EventLogRow[];
  resolved: boolean;
}

interface KeyedReview {
  body: string;
  response: ReviewResponse;
}

/** Plays the scenario fixture in the browser with the same rules the API documents:
 * decisions append a new version, a retried Idempotency-Key replays its response, and
 * reset keeps the previous session so Undo can return to it. */
export class FixtureSource implements DataSource {
  readonly mode = "REPLAY" as const;
  readonly canRestore = true;
  private current: SessionState;
  private previous: SessionState | null = null;
  private readonly keys = new Map<string, KeyedReview>();
  private sessionCount = 0;

  constructor(
    private readonly fixture: ScenarioFixture,
    private readonly now: () => Date = () => new Date(),
  ) {
    this.current = this.freshSession(null);
  }

  async getSession(): Promise<SessionResponse> {
    return this.current.session;
  }

  async getCase(): Promise<CaseData> {
    const { history, outcome, resolved } = this.current;
    const base = this.fixture.pair;
    const detail = { ...base, pair: { ...base.pair, decision: history[history.length - 1] }, history };
    return { sources: this.current.session.sources, detail, outcome, resolved, alertsKnown: true };
  }

  /** The fixture is already scored; Resolve only re-queues the pair and logs the run. */
  async resolve(): Promise<void> {
    this.current = { ...this.current, resolved: true };
    this.log("MATCH_RUN_COMPLETED", { pairId: this.fixture.pair.pair.id });
  }

  async review(pairId: string, body: ReviewRequest, idempotencyKey: string): Promise<ReviewResponse> {
    if (pairId !== this.fixture.pair.pair.id) throw new DataError("NOT_FOUND", "Pair not found.");
    const serialized = JSON.stringify(body);
    const seen = this.keys.get(idempotencyKey);
    if (seen) {
      if (seen.body !== serialized) {
        throw new DataError(
          "IDEMPOTENCY_MISMATCH",
          "This request key was already used for a different decision.",
        );
      }
      return seen.response;
    }
    const response = this.decide(body);
    this.keys.set(idempotencyKey, { body: serialized, response });
    return response;
  }

  async getTimeline(entityId: string): Promise<TimelineEvent[]> {
    return this.fixture.timelineIfApproved.filter((event) => event.entityId === entityId);
  }

  async getAlerts(entityId: string): Promise<SafetyAlert[]> {
    const alerts = this.current.outcome?.alerts ?? [];
    return alerts.filter((a) => a.entityId === entityId);
  }

  async getEvents(): Promise<EventLogRow[]> {
    const all = [...(this.previous?.events ?? []), ...this.current.events];
    return all.slice().reverse().slice(0, EVENT_FEED_ROWS); // one page, newest first, like GET /events
  }

  /** The fixture tiles with HUMAN_REVIEW counting this session's registrar decisions. */
  async getTiles(): Promise<TilesResponse> {
    const reviews = this.current.history.filter((d) => d.actorType === "REGISTRAR").length;
    const tiles = this.fixture.tiles.tiles.map((tile) =>
      tile.id === "HUMAN_REVIEW" ? { ...tile, total: tile.total + reviews } : tile,
    );
    return { ...this.fixture.tiles, tiles };
  }

  async reset(): Promise<SessionResponse> {
    this.previous = this.current;
    this.current = this.freshSession(this.previous.session.id);
    this.log("DEMO_RESET", { sessionId: this.current.session.id });
    return this.current.session;
  }

  async restore(previousSessionId: string): Promise<void> {
    if (this.previous?.session.id !== previousSessionId) {
      throw new DataError("NOT_FOUND", "That session is no longer available.");
    }
    this.current = this.previous;
    this.previous = null;
  }

  private decide(body: ReviewRequest): ReviewResponse {
    const { history, outcome } = this.current;
    const last = history[history.length - 1];
    const approving = body.action === "APPROVE";
    // The review contract: PROPOSED or REJECTED may move (a second review supersedes the
    // first, so the demo can reject and then approve); LINKED only takes a repeat approve.
    if (last.status === "LINKED") {
      if (approving && outcome) return outcome;
      throw new DataError("DECISION_NOT_PENDING", "This pair is already linked.");
    }
    const decision: MatchDecision = {
      ...last,
      id: crypto.randomUUID(),
      version: last.version + 1,
      status: approving ? "LINKED" : "REJECTED",
      actor: body.actor,
      actorType: "REGISTRAR",
      reasonCode: approving ? null : body.reasonCode,
      note: body.note ?? null,
      decidedAt: this.now().toISOString(),
    };
    const alertFires = approving && this.fixture.pair.mergePreview.alertWouldFire;
    const response: ReviewResponse = {
      decision,
      entity: approving ? this.fixture.entityIfApproved : null,
      alerts: alertFires ? [this.fixture.alertIfApproved] : [],
    };
    this.current = { ...this.current, history: [...history, decision], outcome: response };
    this.log(
      approving ? "LINK_APPROVED" : "LINK_REJECTED",
      { pairId: this.fixture.pair.pair.id },
      {
        decisionId: decision.id,
        actor: body.actor,
        actorType: "REGISTRAR",
      },
    );
    for (const alert of response.alerts ?? []) {
      this.log("ALERT_RAISED", { alertId: alert.id, ruleId: alert.ruleId }, { entityId: alert.entityId });
    }
    return response;
  }

  private log(
    eventType: EventType,
    payload: Record<string, unknown>,
    extra: Partial<EventLogRow> = {},
  ): void {
    const row: EventLogRow = {
      ts: this.now().toISOString(),
      eventId: crypto.randomUUID(),
      eventType,
      entryPoint: "API",
      actor: "system:fixture",
      actorType: "SYSTEM",
      mode: "REPLAY",
      payload,
      ...extra,
    };
    this.current = { ...this.current, events: [...this.current.events, row] };
  }

  private freshSession(previousSessionId: string | null): SessionState {
    this.sessionCount += 1;
    const session: SessionResponse = {
      ...this.fixture.session,
      id: this.sessionCount === 1 ? this.fixture.session.id : crypto.randomUUID(),
      createdAt: this.now().toISOString(),
      previousSessionId,
    };
    const { pair, history } = this.fixture.pair;
    return {
      session,
      history: history?.length ? [...history] : [pair.decision],
      outcome: null,
      events: [],
      resolved: false,
    };
  }
}
