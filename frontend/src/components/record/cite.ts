import type { Contribution, NormalizedRecord } from "@/api/types";
import type { CiteField } from "@/lib/desk";
import { citeFieldFor, rankContributions } from "@/lib/display";

/** The rows the evidence rail shows (EvidenceRail's TOP_CONTRIBUTIONS); a thread is drawn for
 * each field those rows cite, and for no other. */
export const RAIL_ROWS = 5;

/** The thread's node: the records agree on this field, or nearly. */
export type Mark = "=" | "≈";

/** The fields the shown evidence cites, strongest first, each once. A feature with no evidence
 * (a missing value) cites nothing. */
export function citedFields(contributions: Contribution[], max = RAIL_ROWS): CiteField[] {
  const fields: CiteField[] = [];
  for (const row of rankContributions(contributions).slice(0, max)) {
    if (row.missing) continue;
    const field = citeFieldFor(row.feature);
    if (field && !fields.includes(field)) fields.push(field);
  }
  return fields;
}

/** The text a record shows for a cited field; the address carries its ZIP. */
export function fieldText(field: CiteField, record: NormalizedRecord): string | null {
  switch (field) {
    case "given":
      return record.givenName ?? null;
    case "family":
      return record.familyName ?? null;
    case "dob":
      return record.birthDate ?? null;
    case "addr": {
      const parts = [record.addressLine, record.zip5].filter((part): part is string => !!part);
      return parts.length ? parts.join(", ") : null;
    }
  }
}

// Case and accents never count as a difference (the scorer folds them too); punctuation and
// spacing do, which is what the hyphen story is about.
function fold(text: string): string {
  return text.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().trim();
}

/** "=" when both records show the same value, "≈" when they differ; null when either side has
 * nothing, because there is no thread to draw to a missing value. */
export function fieldMark(field: CiteField, a: NormalizedRecord, b: NormalizedRecord): Mark | null {
  const left = fieldText(field, a);
  const right = fieldText(field, b);
  if (left == null || right == null) return null;
  return fold(left) === fold(right) ? "=" : "≈";
}

/** One run of characters that one spelling has and the other lacks: `side` names the spelling
 * that has it, `start`..`end` where. The other spelling shows a gap at `start`. */
export interface NameDiff {
  side: "a" | "b";
  start: number;
  end: number;
}

/** The hyphen story (touch 6): when the two spellings differ by exactly one inserted run (a hyphen,
 * a space), say where. Anything else (a substitution, two runs, equal names) is null: no mark. */
export function nameDiff(a: string, b: string): NameDiff | null {
  if (!a || !b || a === b) return null;
  const [long, short, side] = a.length > b.length ? ([a, b, "a"] as const) : ([b, a, "b"] as const);
  let start = 0;
  while (start < short.length && long[start] === short[start]) start++;
  let shortEnd = short.length;
  let longEnd = long.length;
  while (shortEnd > start && long[longEnd - 1] === short[shortEnd - 1]) {
    shortEnd--;
    longEnd--;
  }
  // Characters left over on the short side mean the names differ in more than one insertion.
  if (shortEnd !== start) return null;
  return { side, start, end: longEnd };
}
