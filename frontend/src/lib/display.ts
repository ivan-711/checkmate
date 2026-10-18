import type { Contribution, NormalizedRecord, SourceCard } from "@/api/types";
import type { CiteField } from "./desk";

// Feature codes come from the scorer; the screen shows plain words. One closed list: the scorer's
// ids (backend/core) plus the contract fixture's older ids. Unknown codes fall through unchanged
// so a new feature is visible rather than silently dropped.
// Each name feature reads as "<Given|Family> name" plus this suffix. The scorer compares the
// accented spelling (jw) and the folded one: accents stripped, punctuation to spaces (jw_folded).
const NAME_FEATURES = {
  jw: " spelling",
  jw_folded: ", accents ignored",
  dl: ", typos allowed",
  dmeta: " sound",
  nickname: ", nickname match",
  initial: " initial",
  token_overlap: " parts",
} as const;

// The features backend/core/features.py computes for each name; only given names have
// nickname and initial checks.
export type NameFeature = keyof typeof NAME_FEATURES;
export const GIVEN_FEATURES = Object.keys(NAME_FEATURES) as NameFeature[];
export const FAMILY_FEATURES = GIVEN_FEATURES.filter((f) => f !== "nickname" && f !== "initial");

function nameLabels(
  prefix: "given" | "family",
  name: string,
  features: readonly (keyof typeof NAME_FEATURES)[],
): Record<string, string> {
  return Object.fromEntries(features.map((f) => [`${prefix}_${f}`, `${name}${NAME_FEATURES[f]}`]));
}

export const FEATURE_LABELS: Record<string, string> = {
  ...nameLabels("given", "Given name", GIVEN_FEATURES),
  ...nameLabels("family", "Family name", FAMILY_FEATURES),
  dob_exact: "Date of birth",
  dob_day_month_swap: "Day and month swapped",
  dob_one_digit_edit: "Date of birth, one digit off",
  dob_one_component_off: "Date of birth, one part off",
  dob_year_match: "Birth year",
  sex_match: "Sex",
  phone_match: "Phone",
  address_jaccard: "Address",
  zip_match: "ZIP code",
  missing_given_name: "Given name missing",
  missing_family_name: "Family name missing",
  missing_dob: "Date of birth missing",
  missing_sex: "Sex missing",
  missing_phone: "Phone missing",
  missing_address: "Address missing",
  missing_zip: "ZIP code missing",
  // The contract fixture's ids (REPLAY mode). They never appear in the same list as the
  // scorer's, so "Family name sound" can name both family_metaphone and family_dmeta.
  given_name_jw: "Given name",
  family_name_jw: "Family name",
  family_metaphone: "Family name sound",
};

// The record field each evidence feature cites (CONCEPT.md §5, hover-to-cite). Sex and phone
// have no cite: the Organism draws threads for the four fields the story is about.
const DOB_FEATURES = [
  "dob_exact",
  "dob_day_month_swap",
  "dob_one_digit_edit",
  "dob_one_component_off",
  "dob_year_match",
] as const;

const FEATURE_FIELD: Record<string, CiteField> = {
  ...Object.fromEntries(GIVEN_FEATURES.map((f) => [`given_${f}`, "given"])),
  ...Object.fromEntries(FAMILY_FEATURES.map((f) => [`family_${f}`, "family"])),
  ...Object.fromEntries(DOB_FEATURES.map((f) => [f, "dob"])),
  address_jaccard: "addr",
  zip_match: "addr",
  given_name_jw: "given",
  family_name_jw: "family",
  family_metaphone: "family",
};

/** The field an evidence row lights up in both records; null when the feature has none. */
export function citeFieldFor(feature: string): CiteField | null {
  return FEATURE_FIELD[feature] ?? null;
}

/** The card fields (NormalizedRecord keys) each cite washes. */
export const CITE_CARD_FIELDS = {
  given: ["givenName"],
  family: ["familyName"],
  dob: ["birthDate"],
  addr: ["addressLine", "zip5"],
} as const satisfies Record<CiteField, readonly (keyof NormalizedRecord)[]>;

// Display labels for the event feed (the Activity strip). The code stays in data-event-type for
// the acceptance script; the words are what a judge reads.
const EVENT_LABELS: Record<string, string> = {
  RECORD_INGESTED: "Records loaded",
  MATCH_RUN_COMPLETED: "Match run completed",
  PAIR_SCORED: "Pairs scored",
  LINK_APPROVED: "Link approved",
  LINK_REJECTED: "Link rejected",
  LINK_REVOKED: "Link revoked",
  ENTITY_MERGED: "Records joined",
  ENTITY_SPLIT: "Records split",
  ALERT_RAISED: "Flag raised",
  ALERT_RETRACTED: "Flag withdrawn",
  WHATIF_APPLIED: "What-if applied",
  DEMO_RESET: "Demo reset",
  DEMO_RESTORED: "Demo restored",
  EXPLANATION_GENERATED: "Explanation written",
  EXTERNAL_CALL: "External call",
  EVAL_RUN_STARTED: "Evaluation started",
  EVAL_RUN_FINISHED: "Evaluation finished",
  INTAKE_STARTED: "Check-in started",
  AGENT_TOOL_CALLED: "Agent tool call",
  INTAKE_HANDOFF_CREATED: "Held for registrar",
  AGENT_TURN_DEGRADED: "Agent turn degraded",
};

/** "LINK_APPROVED" reads as "Link approved"; an unlisted code reads as words, never as a code. */
export function eventLabel(eventType: string): string {
  const known = EVENT_LABELS[eventType];
  if (known) return known;
  const words = eventType.toLowerCase().replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Weight as dots (CONCEPT §5 touch 8): six dots, one per 0.5 log-odds, partial fill allowed, by
 * magnitude. 1.47 is 2.94 dots. It reads at a glance and claims no more precision than it has. */
export const EVIDENCE_DOTS = 6;
const LOGIT_PER_DOT = 0.5;

export function evidenceDots(logit: number): number[] {
  const dots = Math.abs(logit) / LOGIT_PER_DOT;
  return Array.from(
    { length: EVIDENCE_DOTS },
    (_, i) => Math.round(Math.max(0, Math.min(1, dots - i)) * 100) / 100,
  );
}

const SAME = 1;
const CLOSE = 0.85;
// Every comparison the scorer makes, said as what it found (backend/core/features.py).
const NAME_NOTES: Record<NameFeature, [same: string, close: string, different: string]> = {
  jw: ["Same letters", "Close spelling", "Different spelling"],
  jw_folded: ["Same, accents ignored", "Close, accents ignored", "Different, accents ignored"],
  dl: ["Same, typos allowed", "Close, typos allowed", "Different, typos allowed"],
  dmeta: ["Same sound", "Similar sound", "Different sound"],
  nickname: ["Nickname match", "Nickname match", "No nickname match"],
  initial: ["Same initial", "Same initial", "Different initial"],
  token_overlap: ["Same parts", "Some parts shared", "Different parts"],
};
const FIELD_NOTES: Record<string, [same: string, close: string, different: string]> = {
  dob_exact: ["Exact", "Exact", "Differs"],
  dob_day_month_swap: ["Day and month swapped", "Day and month swapped", "Not swapped"],
  dob_one_digit_edit: ["One digit off", "One digit off", "More than one digit off"],
  dob_one_component_off: ["One part off", "One part off", "More than one part off"],
  dob_year_match: ["Same year", "Same year", "Different year"],
  sex_match: ["Same", "Same", "Differs"],
  phone_match: ["Same phone", "Same phone", "Different phone"],
  address_jaccard: ["Same street and ZIP", "Mostly the same", "Different address"],
  zip_match: ["Same ZIP", "Same ZIP", "Different ZIP"],
  given_name_jw: NAME_NOTES.jw,
  family_name_jw: NAME_NOTES.jw,
  family_metaphone: NAME_NOTES.dmeta,
};
const NAME_FEATURE = /^(given|family)_(.+)$/;

/** What a row compared, in plain words: the feature's own comparison and how close the two values
 * came. A missing value says so; it is never called a difference. */
export function evidenceNote(feature: string, value: number | null | undefined): string {
  if (value == null) return "Not given on one side";
  const name = NAME_FEATURE.exec(feature);
  const notes = FIELD_NOTES[feature] ?? (name ? NAME_NOTES[name[2] as NameFeature] : undefined);
  if (!notes) return value >= SAME ? "Same" : value > 0 ? "Partly the same" : "Differs";
  return value >= SAME
    ? notes[0]
    : value >= CLOSE || (value > 0 && notes[1] === notes[0])
      ? notes[1]
      : notes[2];
}

export interface RankedContribution extends Contribution {
  label: string;
  missing: boolean;
}

/** Sorted by absolute weight; a missing feature is "no evidence", never negative. The kiosk
 * passes its own language's labels. */
export function rankContributions(
  contributions: Contribution[],
  labels: Record<string, string> = FEATURE_LABELS,
): RankedContribution[] {
  return contributions
    .map((c) => ({ ...c, label: labels[c.feature] ?? c.feature, missing: c.value == null }))
    .sort((a, b) => Number(a.missing) - Number(b.missing) || Math.abs(b.logit) - Math.abs(a.logit));
}

export const CARD_FIELDS = [
  ["givenName", "Given name"],
  ["familyName", "Family name"],
  ["birthDate", "Date of birth"],
  ["sex", "Sex"],
  ["addressLine", "Address"],
  ["zip5", "ZIP code"],
  ["phoneE164", "Phone"],
] as const satisfies readonly (readonly [keyof NormalizedRecord, string])[];

export type CardField = (typeof CARD_FIELDS)[number][0];

export function differingFields(a: NormalizedRecord, b: NormalizedRecord): Set<CardField> {
  const differs = new Set<CardField>();
  for (const [field] of CARD_FIELDS) {
    const left = a[field];
    const right = b[field];
    if (left != null && right != null && left !== right) differs.add(field);
  }
  return differs;
}

const CT_TIME = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/Chicago",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

export function formatCt(iso: string): string {
  return `${CT_TIME.format(new Date(iso))} CT`;
}

/** "registrar:Registrar A" reads as "Registrar A"; other actors keep their full label. */
export function actorName(actor: string): string {
  return actor.startsWith("registrar:") ? actor.slice("registrar:".length) : actor;
}

export function sourceLabel(sourceSystem: string, cards: SourceCard[]): string {
  return cards.find((c) => c.record.sourceSystem === sourceSystem)?.displayLabel ?? sourceSystem;
}

/** A golden value as text. Clinical values (allergies, active orders) arrive as coded objects;
 * they read by their display name and status, so no value ever renders as "[object Object]". */
export function goldenValueText(value: unknown): string | null {
  if (value == null) return null;
  if (Array.isArray(value)) return value.map(goldenValueText).filter(Boolean).join(", ");
  if (typeof value !== "object") return String(value);
  const record = value as Record<string, unknown>;
  const name = record.display ?? record.code;
  if (name != null) return record.status ? `${String(name)} (${String(record.status)})` : String(name);
  return Object.entries(record)
    .filter(([, v]) => v != null)
    .map(([k, v]) => `${k}: ${goldenValueText(v)}`)
    .join(", ");
}

/** One timeline lane, oldest first, cut to its latest `rows` events so the flag card below stays
 * on screen. Constructed-scenario events are the demo's story, so they are never cut. */
export function compactLane<T extends { occurredAt: string; isConstructed?: boolean | null }>(
  lane: T[],
  rows: number,
): { shown: T[]; hidden: number } {
  const sorted = [...lane].sort((a, b) => a.occurredAt.localeCompare(b.occurredAt));
  const cutoff = sorted.length - rows;
  const shown = sorted.filter((e, i) => i >= cutoff || e.isConstructed);
  return { shown, hidden: sorted.length - shown.length };
}

/** The rule's footer without a leading "Rule <id> <version>." when the card already shows the
 * rule in its header; any other footer is returned unchanged. */
export function footerWithoutRule(footer: string, ruleId: string, ruleVersion: string): string {
  const prefix = `Rule ${ruleId} ${ruleVersion}.`;
  return footer.startsWith(prefix) ? footer.slice(prefix.length).trimStart() : footer;
}
