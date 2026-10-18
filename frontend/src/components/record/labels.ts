import type { SourceCard } from "@/api/types";

// The demo sources in plain words (CONCEPT.md §3). Any other source keeps the API's own
// label, so a new source is visible rather than misnamed.
const SOURCE_NAMES: Record<string, string> = {
  ER_FHIR: "Emergency room",
  CLINIC_CSV: "Clinic",
  // The kiosk check-in, once a registrar attaches it to the linked record.
  FRONTDESK_INTAKE: "Kiosk check-in",
};

const FORMATS: Record<string, string> = {
  FHIR_PATIENT: "FHIR R4",
  CSV_ROW: "CSV export",
};

export function sourceName(sourceSystem: string, fallback: string): string {
  return SOURCE_NAMES[sourceSystem] ?? fallback;
}

/** The source's name from the session's cards when one carries that system; the code otherwise. */
export function sourceNameFrom(sourceSystem: string, cards: SourceCard[]): string {
  const card = cards.find((c) => c.record.sourceSystem === sourceSystem);
  return sourceName(sourceSystem, card?.displayLabel ?? sourceSystem);
}

// A kiosk intake record is keyed by a UUID; its first 8 characters tell check-ins apart on a tab.
const INTAKE_ID_CHARS = 8;

/** The record id a crosswalk tab shows: an intake's short id, any other source's id as stored. */
export function recordIdLabel(sourceSystem: string, id: string): string {
  if (sourceSystem !== "FRONTDESK_INTAKE") return id;
  return id.replace(/^intake:/, "").slice(0, INTAKE_ID_CHARS);
}

export function sourceFormat(kind: string): string {
  return FORMATS[kind] ?? kind;
}

/** Coded sex values read as words; anything else is shown as the source wrote it. */
export function sexLabel(value: string): string {
  const code = value.toUpperCase();
  if (code === "F" || code === "FEMALE") return "Female";
  if (code === "M" || code === "MALE") return "Male";
  return value;
}

/** A North American E.164 number grouped for reading; any other number as stored. */
export function phoneLabel(value: string): string {
  const match = /^\+1(\d{3})(\d{3})(\d{4})$/.exec(value);
  return match ? `+1 ${match[1]} ${match[2]} ${match[3]}` : value;
}

/** "1 allergy · 4 active orders": what the record holds, counted from its clinical rows; null when
 * it holds neither, so the record says nothing it cannot count. */
export function holdsLine({ allergies, orders }: { allergies: number; orders: number }): string | null {
  const parts: string[] = [];
  if (allergies > 0) parts.push(`${allergies} ${allergies === 1 ? "allergy" : "allergies"}`);
  if (orders > 0) parts.push(`${orders} active ${orders === 1 ? "order" : "orders"}`);
  return parts.length ? parts.join(" · ") : null;
}
