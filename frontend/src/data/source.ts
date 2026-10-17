import type {
  CandidatePairDetail,
  EventLogRow,
  ReviewRequest,
  SafetyAlert,
  SourceCard,
  ReviewResponse,
  SessionResponse,
  TilesResponse,
  TimelineEvent,
} from "@/api/types";

/** REPLAY when reading the fixture; LOCAL when calling the API on this laptop. */
export type Mode = "REPLAY" | "LOCAL";

export interface CaseData {
  /** The session's source cards; shown before Resolve has queued a pair. */
  sources: SourceCard[];
  /** null until Resolve identity has queued the hero pair. */
  detail: CandidatePairDetail | null;
  /** The response that produced the current decision, when this source knows it. */
  outcome: ReviewResponse | null;
  /** False after a reset until Resolve identity has run; the pair panel waits for it. */
  resolved: boolean;
}

/** One data layer, two adapters. The UI branches on `mode` only for the badge. */
export interface DataSource {
  readonly mode: Mode;
  /** Whether restore() works here; the Undo reset action is offered only when it does. */
  readonly canRestore: boolean;
  /** The session the screen is showing; null when this tab has not reset yet in LOCAL. */
  getSession(): Promise<SessionResponse | null>;
  getCase(): Promise<CaseData>;
  /** UX "Resolve identity": block, score, band (POST /match-runs in LOCAL). */
  resolve(): Promise<void>;
  review(pairId: string, body: ReviewRequest, idempotencyKey: string): Promise<ReviewResponse>;
  /** null when this source has no timeline for the entity. */
  getTimeline(entityId: string): Promise<TimelineEvent[] | null>;
  /** null when this source has no alerts read for the entity. */
  getAlerts(entityId: string): Promise<SafetyAlert[] | null>;
  /** The append-only event feed, newest first. */
  getEvents(): Promise<EventLogRow[]>;
  getTiles(): Promise<TilesResponse>;
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
