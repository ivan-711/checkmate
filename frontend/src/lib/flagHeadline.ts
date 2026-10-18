import type { SafetyAlert } from "@/api/types";

// The alert carries no structured drug or reaction field, so the headline reads the sentences the
// rule writes into its card text (backend/rule/bl_amox_01.py, rule v1). A part the text does not
// carry falls back to plain words; no drug, reaction or patient value is ever typed here.
const ALLERGY = /documents an allergy coded (.+?) \(RxNorm /;
const REACTION = /; reaction: (.+?)\)\./;
const ORDER = /has an active order for (.+?), RxNorm \d+\./;
const NOT_RECORDED = /not recorded$/;
const NUMBER = /^\d/;

const capitalize = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** "Amoxicillin" reads as "amoxicillin" mid-sentence; "penicillin V" and "AMOXICILLIN" stay. */
function midSentence(text: string): string {
  const [first] = text.split(" ");
  return /^[A-Z][a-z]+$/.test(first) ? text.charAt(0).toLowerCase() + text.slice(1) : text;
}

/** The rule writes "<name>, <severity>", a severity alone, or "not recorded". */
function reactionName(reaction: string): string | null {
  const comma = reaction.lastIndexOf(", ");
  const name = comma === -1 ? reaction : reaction.slice(0, comma);
  return NOT_RECORDED.test(name) ? null : midSentence(name);
}

/** "amoxicillin 250 MG / clavulanate 125 MG Oral Tablet" names "amoxicillin/clavulanate": each
 * ingredient is the words before its strength, after any leading quantity ("1 ML ..."). */
function drugName(display: string): string {
  const names = display.split(" / ").map((part) => {
    const words = part.split(" ");
    const start = NUMBER.test(words[0]) ? 2 : 0;
    const end = words.findIndex((word, i) => i >= start && NUMBER.test(word));
    return words.slice(start, end === -1 ? undefined : end).join(" ");
  });
  return midSentence(names.every(Boolean) ? names.join("/") : display);
}

/** The flag's two facts, e.g. "Penicillin V allergy (anaphylaxis)" and "active amoxicillin order". */
export function flagFacts(alert: Pick<SafetyAlert, "cardText">): { allergy: string; order: string } {
  const allergy = ALLERGY.exec(alert.cardText)?.[1];
  const reaction = REACTION.exec(alert.cardText)?.[1];
  const order = ORDER.exec(alert.cardText)?.[1];
  const reactionText = reaction ? reactionName(reaction) : null;
  return {
    allergy: `${allergy ? `${capitalize(allergy)} allergy` : "Documented allergy"}${
      reactionText ? ` (${reactionText})` : ""
    }`,
    order: `active ${order ? `${drugName(order)} ` : ""}order`,
  };
}

/** One line for a raised flag, e.g. "Penicillin V allergy (anaphylaxis) · active amoxicillin order". */
export function flagHeadline(alert: Pick<SafetyAlert, "cardText">): string {
  const { allergy, order } = flagFacts(alert);
  return `${allergy} · ${order}`;
}

/** "1 allergy surfaced", "2 allergies surfaced": one per alert the approval raised. */
export function surfacedLine(count: number): string {
  return `${count} ${count === 1 ? "allergy" : "allergies"} surfaced`;
}
