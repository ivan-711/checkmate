import type {
  CandidatePairDetail,
  ReviewRequest,
  ReviewResponse,
  SessionResponse,
  TilesResponse,
} from "@/api/types";
import type { TimelineEvent } from "./scenario";

/** REPLAY when reading the fixture; LOCAL when calling the API on this laptop. */
export type Mode = "REPLAY" | "LOCAL";

export interface CaseData {
  detail: CandidatePairDetail;
  /** The response that produced the current decision, when this source knows it. */
  outcome: ReviewResponse | null;
}

/** One data layer, two adapters. The UI branches on `mode` only for the badge. */
export interface DataSource {
  readonly mode: Mode;
  getCase(): Promise<CaseData>;
  review(pairId: string, body: ReviewRequest, idempotencyKey: string): Promise<ReviewResponse>;
  /** null when this source has no timeline for the entity. */
  getTimeline(entityId: string): Promise<TimelineEvent[] | null>;
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
