import transcript from "@hero/frontdesk_transcript.json";
import type { Language } from "@/api/types";

/** The parts of data/scenarios/hero/frontdesk_transcript.json the kiosk reads: a data file read
 * at build time, so the presenter can send the exact line the replay expects. */
type ScriptTurn = { userText: string; steps: { model: { args?: { preferredLanguage?: string } } }[] };
const TURNS = (transcript as unknown as { turns: ScriptTurn[] }).turns;

/** The first turn in each language is the hero's; later turns cover other patients. */
function firstLine(language: Language): string {
  const turn = TURNS.find((t) => t.steps.some((step) => step.model.args?.preferredLanguage === language));
  return turn?.userText ?? "";
}

export const DEMO_SCRIPT = { en: firstLine("EN"), es: firstLine("ES") } as const;
