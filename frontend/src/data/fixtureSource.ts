import type {
  MatchDecision,
  ReviewRequest,
  ReviewResponse,
  SessionResponse,
  TilesResponse,
} from "@/api/types";
import type { ScenarioFixture, TimelineEvent } from "./scenario";
import { DataError, type CaseData, type DataSource } from "./source";

interface SessionState {
  session: SessionResponse;
  /** Append-only, oldest first, like the API's decision history. */
  history: MatchDecision[];
  outcome: ReviewResponse | null;
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

  async getCase(): Promise<CaseData> {
    const { history, outcome } = this.current;
    const base = this.fixture.pair;
    const detail = { ...base, pair: { ...base.pair, decision: history[history.length - 1] }, history };
    return { detail, outcome };
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

  async getTiles(): Promise<TilesResponse> {
    return this.fixture.tiles;
  }

  async reset(): Promise<SessionResponse> {
    this.previous = this.current;
    this.current = this.freshSession(this.previous.session.id);
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
    const { history } = this.current;
    const last = history[history.length - 1];
    const approving = body.action === "APPROVE";
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
    return response;
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
    return { session, history: history?.length ? [...history] : [pair.decision], outcome: null };
  }
}
