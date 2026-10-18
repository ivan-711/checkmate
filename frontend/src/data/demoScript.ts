import transcript from "@hero/frontdesk_transcript.json";
import type { Language } from "@/api/types";

/** The parts of data/scenarios/hero/frontdesk_transcript.json the kiosk reads: a data file read
 * at build time, so the presenter can send the exact line the replay expects. */
type ScriptTurn = { userText: string; steps: { model: { args?: { preferredLanguage?: string } } }[] };
const TURNS = (transcript as unknown as { turns: ScriptTurn[] }).turns;

/** The transcript's lines in one language, in order: the hero's first, then later patients. */
function lines(language: Language): string[] {
  return TURNS.filter((t) => t.steps.some((step) => step.model.args?.preferredLanguage === language)).map(
    (t) => t.userText,
  );
}

/** The hero's line in each language, and the new patient's (the second turn), which the gate lets
 * open a chart. The replay accepts only these exact texts. */
export const DEMO_SCRIPT = {
  en: lines("EN")[0] ?? "",
  es: lines("ES")[0] ?? "",
  newPatient: { en: lines("EN")[1] ?? "", es: lines("ES")[1] ?? "" },
} as const;
