import type { CandidatePairDetail } from "@/api/types";

/** The stage's state on the Desk (CONCEPT §8, L1 contract). One pane of the decision column is
 * mounted per state; the Organism reads the same value. */
export type StageState = "idle" | "held" | "review" | "confirm" | "linked" | "rejected";
export type KioskState = "idle" | "working" | "held" | "done";
export interface DeskState {
  stage: StageState;
  kiosk: KioskState;
}

/** A record field the evidence can cite. Hovering or focusing an evidence row names one; both
 * records wash that field (hover-to-cite, CONCEPT §5 touch 6). */
export type CiteField = "given" | "family" | "dob" | "addr" | "phone" | "sex";

export interface CiteContext {
  cite: CiteField | null;
  setCite: (field: CiteField | null) => void;
}

export type ReviewIntent = "APPROVE" | "REJECT";

export interface StageInputs {
  /** The pair under review, once Resolve (or a queue link) has it; null before. */
  detail: CandidatePairDetail | null;
  resolved: boolean;
  /** Hand-off pairs the gate holds for the kiosk's check-in. */
  heldPairs: number;
  /** The confirm sheet that is open, if any. */
  intent: ReviewIntent | null;
}

/** The decision follows the pair's recorded status; a held check-in only matters before anything
 * is compared. Pure, so the Organism and the column can never disagree. */
export function deriveStageState({ detail, heldPairs, intent }: StageInputs): StageState {
  if (detail) {
    const { status } = detail.pair.decision;
    if (status === "LINKED") return "linked";
    if (status === "REJECTED") return "rejected";
    return intent ? "confirm" : "review";
  }
  return heldPairs > 0 ? "held" : "idle";
}
