import type { IntakeSession, Language } from "@/api/types";

/** A check-in takes its language when it starts, and the replay plays the recording for that
 * language only. So a toggle change before the first turn starts a new check-in in the new
 * language; once the patient has written, the conversation is kept. */
export function needsNewCheckIn(session: IntakeSession | undefined, language: Language): boolean {
  return !!session && (session.turns ?? []).length === 0 && session.language !== language;
}
