import type {
  CandidatePairDetail,
  CandidatePairPage,
  CandidatePairQuery,
  MatchRunResponse,
  EventLogRow,
  IntakeSession,
  IntakeTurn,
  Language,
  ReviewRequest,
  ReviewResponse,
  SafetyAlert,
  SessionResponse,
  SourceCard,
  TilesResponse,
  TimelineEvent,
} from "@/api/types";

/** Rows the event feed shows; the API is asked for exactly one page of this size. */
export const EVENT_FEED_ROWS = 12;

/** REPLAY when reading the fixture; LOCAL when calling the API on this laptop. */
export type Mode = "REPLAY" | "LOCAL";

export interface CaseData {
  /** The session's source cards; shown before Resolve has queued a pair. */
  sources: SourceCard[];
  /** null until Resolve identity has queued the hero pair. */
  detail: CandidatePairDetail | null;
  /** The response that produced the current decision, when this source knows it. */
  outcome: ReviewResponse | null;
  /** False after a reset until Resolve identity has queued the session's pair. */
  resolved: boolean;
  /** False when the alerts read failed or is not available, so the screen makes no rule claim. */
  alertsKnown: boolean;
}

/** The kiosk's suggested check-in in each language. demoScript is true when it is the hero
 * transcript's line (API), false when it is the contract fixture's utterance. */
export interface SuggestedCheckIn {
  en: string;
  es: string;
  demoScript: boolean;
}

/** One data layer, two adapters. The UI branches on `mode` only for the badge and for the
 * kiosk's Start over, which in LOCAL has to be the demo reset. */
export interface DataSource {
  readonly mode: Mode;
  /** Whether restore() works here; the Undo reset action is offered only when it does. */
  readonly canRestore: boolean;
  readonly suggestedCheckIn: SuggestedCheckIn;
  /** The session the screen is showing; null when this tab has not reset yet in LOCAL. */
  getSession(): Promise<SessionResponse | null>;
  /** The session's Case pair, or the pair `pairId` names when the work queue opened one. */
  getCase(pairId?: string): Promise<CaseData>;
  /** UX "Resolve identity": block, score, band (POST /match-runs in LOCAL). Returns the run's
   * receipt, which feeds the work-queue funnel; null where the source is already scored. */
  resolve(): Promise<MatchRunResponse | null>;
  /** One keyset page of stored candidate pairs, read-only, in the server's order. */
  getCandidatePairs(query: CandidatePairQuery): Promise<CandidatePairPage>;
  /** One pair with both records and its evidence; DataError NOT_FOUND when it is not stored. */
  getCandidatePair(pairId: string): Promise<CandidatePairDetail>;
  review(pairId: string, body: ReviewRequest, idempotencyKey: string): Promise<ReviewResponse>;
  /** null when this source has no timeline for the entity. */
  getTimeline(entityId: string): Promise<TimelineEvent[] | null>;
  /** null when this source has no alerts read for the entity. */
  getAlerts(entityId: string): Promise<SafetyAlert[] | null>;
  /** The newest EVENT_FEED_ROWS rows of the append-only event feed, newest first. */
  getEvents(): Promise<EventLogRow[]>;
  getTiles(): Promise<TilesResponse>;
  /** FrontDesk: opens a check-in. The server picks the agent mode and reports it as agentMode. */
  startIntake(language: Language, scenarioContextId: string): Promise<IntakeSession>;
  /** One typed message. The key is minted once per message and reused when it is retried. */
  sendTurn(sessionId: string, text: string, idempotencyKey: string): Promise<IntakeTurn>;
  reset(): Promise<SessionResponse>;
  restore(previousSessionId: string): Promise<void>;
}

export class DataError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "DataError";
  }
}
