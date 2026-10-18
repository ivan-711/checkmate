import type { DecisionStatus, ReasonCode, RegistrationState } from "@/api/types";

/* The Desk contract (CONCEPT.md §8, "contract first"). L1 owns this file; L2, L3 and L4 build
 * against it and meet only here. Nothing in it renders. */

/** The registrar's stage: which still is on screen. Derived, never set by hand (deriveDeskState). */
export type DeskState = "idle" | "held" | "review" | "confirm" | "linked" | "rejected";

/** The patient's kiosk. Set by the kiosk (L2) through DeskContext.setKiosk. */
export type KioskState = "idle" | "working" | "held" | "done";

/** The field an evidence row cites; hovering or focusing the row lights it in both records. */
export type CiteField = "given" | "family" | "dob" | "addr";

/** Shared between the evidence rail (L4, writes) and the Organism (L3, reads). */
export interface CiteContext {
  cite: CiteField | null;
  setCite(cite: CiteField | null): void;
}

/** Which confirm sheet is open on the decision column; null when none. */
export type Sheet = "approve" | "reject" | null;

export interface DeskInput {
  /** The hero pair's decision once Resolve has queued it; null before. */
  decision: DecisionStatus | null;
  /** True once a LINKED decision's entity has loaded, so the record can be drawn. */
  linked: boolean;
  sheet: Sheet;
  kiosk: KioskState;
}

/** One function decides the stage state, so the title, stepper, panes and Organism never disagree. */
export function deriveDeskState({ decision, linked, sheet, kiosk }: DeskInput): DeskState {
  if (decision === "LINKED" && linked) return "linked";
  if (decision === "REJECTED") return "rejected";
  if (decision === "PROPOSED" || decision === "LINKED") return sheet ? "confirm" : "review";
  return kiosk === "held" ? "held" : "idle";
}

/** The story stepper in the header (BUILD-SPEC decision 3, from concept 5). */
export const STORY_STEPS = [
  { id: "checkin", label: "Check-in" },
  { id: "gate", label: "Rules gate" },
  { id: "compare", label: "Compare" },
  { id: "link", label: "Link" },
  { id: "flag", label: "Clinician flag" },
] as const;

export type StoryStep = (typeof STORY_STEPS)[number]["id"];

export type StepStatus = "done" | "current" | "upcoming";

/** The step the story is on. The gate step is current only while the kiosk is held and the
 * registrar has not started comparing; a desk with no kiosk activity (G16) starts at Check-in. */
export function currentStep(desk: DeskState, kiosk: KioskState, flagRaised: boolean): StoryStep {
  switch (desk) {
    case "linked":
      return flagRaised ? "flag" : "link";
    case "review":
    case "confirm":
    case "rejected":
      return "compare";
    case "held":
      return "gate";
    case "idle":
      return kiosk === "held" ? "gate" : "checkin";
  }
}

export function stepStatus(step: StoryStep, current: StoryStep): StepStatus {
  const order = STORY_STEPS.map((s) => s.id);
  const diff = order.indexOf(step) - order.indexOf(current);
  return diff < 0 ? "done" : diff === 0 ? "current" : "upcoming";
}

export interface StageHead {
  eyebrow: string;
  title: string;
  subtitle: string;
}

export interface StageHeadContext {
  /** The patient's given name from the records; null when no record has one. */
  name: string | null;
  /** Who linked the pair ("Registrar A"); null until a link exists. */
  registrar: string | null;
  flagRaised: boolean;
  /** The reject reason, once rejected. */
  reason: ReasonCode | null;
}

/** The stage header per state: an eyebrow, a plain-language title and one consequence line
 * (the keynote pattern). Every name comes from the data; nothing here names the hero. */
export function stageHead(desk: DeskState, ctx: StageHeadContext): StageHead {
  const who = ctx.name ?? "the same name";
  switch (desk) {
    case "idle":
      return {
        eyebrow: "Records on file",
        title: "Two records, one name",
        subtitle: `Two sources each hold a record for ${who}. They are not linked.`,
      };
    case "held":
      return {
        eyebrow: "Needs registrar",
        title: ctx.name ? `${ctx.name} is at the kiosk` : "A patient is at the kiosk",
        subtitle: "FrontDesk asked to open a new chart. The gate denied it: these records may be theirs.",
      };
    case "review":
      return {
        eyebrow: "Needs registrar",
        title: "Is this the same person?",
        subtitle: "Approving joins these two records into one. Nothing links until you do.",
      };
    case "confirm":
      return {
        eyebrow: "Needs registrar",
        title: "Is this the same person?",
        subtitle: "Confirm to record your decision. It is saved under your name.",
      };
    case "linked":
      return {
        eyebrow: ctx.registrar ? `Linked by ${ctx.registrar}` : "Linked",
        title: ctx.name ? `One record for ${ctx.name}` : "One record",
        subtitle: ctx.flagRaised
          ? "Both histories are together now. One item is flagged for a clinician."
          : "Both histories are together now. The rule found nothing to flag.",
      };
    case "rejected":
      return {
        eyebrow: "Records on file",
        title: "Two records, one name",
        subtitle:
          ctx.reason === "DIFFERENT_PERSON"
            ? "Rejected as a different person. Nothing was linked, and this pair will not be suggested again."
            : "Rejected for now. Nothing was linked, and nothing was suppressed: they can be compared again.",
      };
  }
}

/** The kiosk's default state from the check-in on record (the Registration state the contract
 * returns). The kiosk (L2) sets "working" itself while a turn runs; this is the fallback. */
export function kioskStateFrom(state: RegistrationState | undefined, turnRunning: boolean): KioskState {
  switch (state) {
    case "PENDING_REGISTRAR":
      return "held";
    case "NEW_CHART":
    case "LINKED":
    case "RELEASED":
      return "done";
    default:
      return turnRunning ? "working" : "idle";
  }
}

export interface EventGroup {
  eventType: string;
  count: number;
  /** The newest event's time and id in the group. */
  ts: string;
  eventId: string;
}

/** Consecutive events of one type collapse into one row with a count ("Pairs scored ×12"). */
export function groupEvents(
  rows: readonly { eventId: string; eventType: string; ts: string }[],
): EventGroup[] {
  const groups: EventGroup[] = [];
  for (const row of rows) {
    const last = groups[groups.length - 1];
    if (last && last.eventType === row.eventType) last.count += 1;
    else groups.push({ eventType: row.eventType, count: 1, ts: row.ts, eventId: row.eventId });
  }
  return groups;
}

const SECONDS_PER_MINUTE = 60;
const JUST_NOW_SECONDS = 3;

/** "held 0:41": minutes and zero-padded seconds. */
export function formatHeld(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / SECONDS_PER_MINUTE)}:${String(s % SECONDS_PER_MINUTE).padStart(2, "0")}`;
}

/** A live relative time that never rounds up what has not happened yet. */
export function agoText(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < JUST_NOW_SECONDS) return "just now";
  if (s < SECONDS_PER_MINUTE) return `${s} s ago`;
  return `${Math.floor(s / SECONDS_PER_MINUTE)} min ago`;
}
