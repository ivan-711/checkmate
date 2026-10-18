import type {
  CandidatePairDetail,
  CandidatePairPage,
  CandidatePairQuery,
  EventLogRow,
  EventType,
  IntakeSession,
  IntakeTurn,
  Language,
  MatchDecision,
  ReviewRequest,
  ReviewResponse,
  SafetyAlert,
  SessionResponse,
  TilesResponse,
  TimelineEvent,
} from "@/api/types";
import { GATE_BUCKET_MS } from "@/lib/buckets";
import { FixtureIntake } from "./fixtureIntake";
import type { ScenarioFixture } from "./scenario";
import { DataError, EVENT_FEED_ROWS, type CaseData, type DataSource, type SuggestedCheckIn } from "./source";

interface SessionState {
  session: SessionResponse;
  /** Append-only, oldest first, like the API's decision history. */
  history: MatchDecision[];
  outcome: ReviewResponse | null;
  /** Append-only, oldest first: what the API's event_log would hold for this session. */
  events: EventLogRow[];
  resolved: boolean;
  /** A FrontDesk check-in handed the fixture pair to a registrar; the API stores that pair. */
  handedOff: boolean;
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
  readonly suggestedCheckIn: SuggestedCheckIn;
  private current: SessionState;
  private previous: SessionState | null = null;
  private readonly keys = new Map<string, KeyedReview>();
  private sessionCount = 0;
  private readonly intake: FixtureIntake;

  constructor(
    private readonly fixture: ScenarioFixture,
    private readonly now: () => Date = () => new Date(),
  ) {
    this.current = this.freshSession(null);
    this.intake = new FixtureIntake(fixture, now);
    const { utteranceEn, utteranceEs } = fixture.frontdeskIntake;
    this.suggestedCheckIn = { en: utteranceEn, es: utteranceEs, demoScript: false };
  }

  async getSession(): Promise<SessionResponse> {
    return this.current.session;
  }

  async getCase(pairId?: string): Promise<CaseData> {
    const { outcome, resolved } = this.current;
    const detail = pairId ? await this.getCandidatePair(pairId) : this.currentDetail();
    return { sources: this.current.session.sources, detail, outcome, resolved, alertsKnown: true };
  }

  /** The fixture is already scored; Resolve only re-queues the pair and logs the run. It has no
   * match-run receipt to return, so the work queue shows no funnel in REPLAY. */
  async resolve(): Promise<null> {
    this.current = { ...this.current, resolved: true };
    this.log("MATCH_RUN_COMPLETED", { pairId: this.fixture.pair.pair.id });
    return null;
  }

  /** The fixture's one pair, with this session's decision, once Resolve or a FrontDesk hand-off
   * has stored it (as the API would); filtered the way the API filters, on one page. */
  async getCandidatePairs(query: CandidatePairQuery): Promise<CandidatePairPage> {
    if (!this.current.resolved && !this.current.handedOff) return { items: [], nextCursor: null };
    const { pair: stored } = this.currentDetail();
    // Stored only by the kiosk's hand-off, it reads as the API stores that pair.
    const pair = this.current.resolved ? stored : { ...stored, origin: "FRONTDESK_HANDOFF" as const };
    const matches =
      (!query.band || pair.decision.band === query.band) &&
      (!query.status || pair.decision.status === query.status) &&
      (!query.origin || pair.origin === query.origin) &&
      (!query.recordId || [pair.recordAId, pair.recordBId].includes(query.recordId));
    return { items: matches ? [pair] : [], nextCursor: null };
  }

  async getCandidatePair(pairId: string): Promise<CandidatePairDetail> {
    if (pairId !== this.fixture.pair.pair.id) throw new DataError("NOT_FOUND", "Pair not found.");
    return this.currentDetail();
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

  /** The fixture tiles with HUMAN_REVIEW counting this session's registrar decisions and
   * AGENT_GATE counting every gate outcome so far (agent actions are not undone by a reset). */
  async getTiles(): Promise<TilesResponse> {
    const reviews = this.current.history.filter((d) => d.actorType === "REGISTRAR").length;
    // Each outcome in the 5-minute bucket it happened in, never in the fixture's 18:00 snapshot
    // bucket; like the API, only series with a count get a row.
    const gate = [...this.intake.gateCounts].flatMap(([bucket, counts]) =>
      (["ALLOW", "DENY"] as const)
        .filter((series) => counts[series] > 0)
        .map((series) => ({
          bucket,
          series,
          count: counts[series],
          meanLatencyMs: null,
          maxLatencyMs: null,
        })),
    );
    const tiles = this.fixture.tiles.tiles.map((tile) => {
      if (tile.id === "HUMAN_REVIEW") return { ...tile, total: tile.total + reviews };
      if (tile.id !== "AGENT_GATE") return tile;
      // Like the API, the tile holds the last windowMinutes only.
      const since = this.now().getTime() - tile.windowMinutes * 60_000;
      const recent = gate.filter((b) => Date.parse(b.bucket) + GATE_BUCKET_MS > since);
      const buckets = [...tile.buckets.filter((b) => b.count > 0), ...recent];
      return { ...tile, buckets, total: tile.total + recent.reduce((n, b) => n + b.count, 0) };
    });
    return { ...this.fixture.tiles, tiles };
  }

  async startIntake(language: Language): Promise<IntakeSession> {
    const session = this.intake.start(language);
    this.log("INTAKE_STARTED", { intakeSessionId: session.id });
    return session;
  }

  async sendTurn(sessionId: string, text: string, idempotencyKey: string): Promise<IntakeTurn> {
    const turn = this.intake.send(sessionId, text, idempotencyKey);
    for (const call of turn.toolCalls ?? []) {
      this.log("AGENT_TOOL_CALLED", {
        intakeSessionId: sessionId,
        toolName: call.toolName,
        gate: call.gate.outcome,
      });
    }
    if (
      turn.registration.state === "PENDING_REGISTRAR" &&
      turn.toolCalls?.some((c) => c.gate.handoffRequired)
    ) {
      // One row per hand-off pair (ADR-016 §6).
      for (const pairId of turn.registration.handoffPairIds ?? []) {
        this.log("INTAKE_HANDOFF_CREATED", { intakeSessionId: sessionId, pairId });
      }
      this.current = { ...this.current, handedOff: true };
    }
    if (turn.degraded)
      this.log("AGENT_TURN_DEGRADED", { intakeSessionId: sessionId, degraded: turn.degraded });
    return turn;
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

  private currentDetail(): CandidatePairDetail {
    const { history } = this.current;
    const base = this.fixture.pair;
    return { ...base, pair: { ...base.pair, decision: history[history.length - 1] }, history };
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
      handedOff: false,
    };
  }
}
