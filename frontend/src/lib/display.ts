import type { Contribution, NormalizedRecord, SourceCard } from "@/api/types";

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
const GIVEN_FEATURES = Object.keys(NAME_FEATURES) as (keyof typeof NAME_FEATURES)[];
const FAMILY_FEATURES = GIVEN_FEATURES.filter((f) => f !== "nickname" && f !== "initial");

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

export interface RankedContribution extends Contribution {
  label: string;
  missing: boolean;
}

/** Sorted by absolute weight; a missing feature is "no evidence", never negative. */
export function rankContributions(contributions: Contribution[]): RankedContribution[] {
  return contributions
    .map((c) => ({ ...c, label: FEATURE_LABELS[c.feature] ?? c.feature, missing: c.value == null }))
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
