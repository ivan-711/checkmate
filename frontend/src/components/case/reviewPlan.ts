import type { CandidatePairDetail, ReviewRequest, ReviewResponse } from "@/api/types";

/** Decision 1 (BUILD-SPEC): one Confirm may record two approvals. The pair under review goes
 * first; then, when the kiosk's check-in is held by a hand-off pair and the "Also attach" row is
 * on, that pair. Each step is its own review with its own Idempotency-Key, so a person still
 * approves every link explicitly and the event log shows one LINK_APPROVED per link. */
export interface ReviewStep {
  pairId: string;
  body: ReviewRequest;
  key: string;
}

export interface ReviewKeys {
  primary: string;
  attach: string;
}

export interface AttachChoice {
  pairId: string;
  on: boolean;
}

/** The hand-off pair the attach row offers: the strongest one still waiting on a person, and
 * never the pair already under review (in the fixture both are the same pair). */
export function attachablePair(
  handoffs: CandidatePairDetail[],
  reviewingPairId: string,
): CandidatePairDetail | null {
  const waiting = handoffs.filter(
    (d) => d.pair.id !== reviewingPairId && d.pair.decision.status === "PROPOSED",
  );
  if (waiting.length === 0) return null;
  return waiting.reduce((best, d) => (d.pair.decision.p > best.pair.decision.p ? d : best));
}

export function planReviews({
  pairId,
  body,
  attach,
  keys,
}: {
  pairId: string;
  body: ReviewRequest;
  attach: AttachChoice | null;
  keys: ReviewKeys;
}): ReviewStep[] {
  const steps: ReviewStep[] = [{ pairId, body, key: keys.primary }];
  if (body.action === "APPROVE" && attach?.on) {
    // The registrar's label carries over; the note belongs to the first decision only.
    steps.push({ pairId: attach.pairId, body: { action: "APPROVE", actor: body.actor, note: null }, key: keys.attach });
  }
  return steps;
}

export interface ReviewRun {
  primary: ReviewResponse;
  attach: ReviewResponse | null;
  /** The second approval failed after the first was recorded: the link stands, the check-in waits. */
  attachError: Error | null;
}

export type ReviewFn = (pairId: string, body: ReviewRequest, key: string) => Promise<ReviewResponse>;

/** Posts the steps in order. The first failing is the caller's error; a failing second step is
 * reported alongside the first's response, never thrown, so a recorded link is never shown as lost. */
export async function runReviews(review: ReviewFn, steps: ReviewStep[]): Promise<ReviewRun> {
  const [first, second] = steps;
  const primary = await review(first.pairId, first.body, first.key);
  if (!second) return { primary, attach: null, attachError: null };
  try {
    return { primary, attach: await review(second.pairId, second.body, second.key), attachError: null };
  } catch (error) {
    return { primary, attach: null, attachError: error instanceof Error ? error : new Error(String(error)) };
  }
}
