import type { IntakeSession, IntakeTurn, Language, ToolCallRecord } from "@/api/types";
import type { ScenarioFixture } from "./scenario";
import { DataError } from "./source";

const POLICY_VERSION = "frontdesk-gate/1";
// ADR-016 §8: the bilingual template a degraded turn answers with.
const TEMPLATE_TEXT =
  "Un momento, una persona de registro le va a ayudar / One moment, a registrar will help you";
// The recorded agent line after the hand-off (ADR-016 §7), in the language the patient wrote.
const RECORDED_REPLY: Record<Language, string> = {
  EN: "Thank you. A registrar will confirm your chart in a moment.",
  ES: "Gracias. Una persona de registro va a confirmar su expediente en un momento.",
};

/** The replay adapter's comparison: case, accents and spacing do not count (ADR-016 §7). */
export function foldText(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().replace(/\s+/g, " ").trim();
}

interface KeyedTurn {
  text: string;
  turn: IntakeTurn;
}

/** Plays the recorded FrontDesk turn in the browser. The suggested check-in gets the recorded
 * answer: search allowed, new chart denied because the fixture pair is REVIEW, handed to a
 * registrar. Any other text degrades to the template, as the server's replay adapter does. */
export class FixtureIntake {
  private readonly sessions = new Map<string, IntakeSession>();
  private readonly keys = new Map<string, KeyedTurn>();
  /** Gate outcomes so far; the AGENT_GATE tile adds them (the tile keeps history across resets). */
  readonly gateCounts = { ALLOW: 0, DENY: 0 };

  constructor(
    private readonly fixture: ScenarioFixture,
    private readonly now: () => Date,
  ) {}

  start(language: Language): IntakeSession {
    const session: IntakeSession = {
      id: crypto.randomUUID(),
      createdAt: this.now().toISOString(),
      language,
      agentMode: "REPLAY",
      registration: { state: "NONE", handoffPairIds: [] },
      promptVersion: "fixture",
      toolSchemaVersion: "fd-tools/1",
      turns: [],
      closed: false,
    };
    this.sessions.set(session.id, session);
    return session;
  }

  send(sessionId: string, text: string, idempotencyKey: string): IntakeTurn {
    const session = this.sessions.get(sessionId);
    if (!session) throw new DataError("NOT_FOUND", "Check-in not found.");
    const keyId = `${sessionId}:${idempotencyKey}`; // keys are scoped to one check-in
    const seen = this.keys.get(keyId);
    if (seen) {
      if (seen.text !== text) {
        throw new DataError(
          "IDEMPOTENCY_MISMATCH",
          "This request key was already used for a different message.",
        );
      }
      return seen.turn;
    }
    const { utteranceEn, utteranceEs } = this.fixture.frontdeskIntake;
    const language = [["EN", utteranceEn] as const, ["ES", utteranceEs] as const].find(
      ([, u]) => foldText(u) === foldText(text),
    )?.[0];
    const turns = session.turns ?? [];
    const turnIndex = turns.length;
    const turn =
      language && turnIndex === 0
        ? this.recordedTurn(text, language)
        : this.degradedTurn(session, text, turnIndex);
    for (const call of turn.toolCalls ?? []) this.gateCounts[call.gate.outcome] += 1;
    this.sessions.set(sessionId, { ...session, turns: [...turns, turn], registration: turn.registration });
    this.keys.set(keyId, { text, turn });
    return turn;
  }

  private recordedTurn(userText: string, language: Language): IntakeTurn {
    const { pair, recordA, recordB, contributions } = this.fixture.pair;
    const existing = recordB.record;
    // What the agent heard: the arriving patient's demographics, as the ER record holds them.
    const { givenName, familyName, birthDate } = recordA.normalized;
    const args = { givenName, familyName, birthDate };
    const candidate = {
      recordId: existing.id,
      sourceSystem: existing.sourceSystem,
      p: pair.decision.p,
      band: pair.decision.band,
      pairId: pair.id,
      negativeRulesFired: pair.decision.negativeRulesFired ?? [],
      topContributions: contributions,
    };
    const call = (stepIndex: number, toolName: string, gate: ToolCallRecord["gate"]): ToolCallRecord => ({
      id: crypto.randomUUID(),
      stepIndex,
      toolName,
      args,
      gate,
      effect: { status: "NONE" },
      candidates: [candidate],
      latencyMs: 0,
    });
    return {
      turnIndex: 0,
      userText,
      assistantText: RECORDED_REPLY[language],
      assistantTextSource: "MODEL",
      agentMode: "REPLAY",
      degraded: null,
      // The server would create an intake record and a FRONTDESK_HANDOFF pair for it. The fixture
      // has one pair, so the hand-off points at it and the registrar decides the same pair as Case.
      registration: { state: "PENDING_REGISTRAR", handoffPairIds: [pair.id] },
      toolCalls: [
        call(0, "search_patients", {
          outcome: "ALLOW",
          handoffRequired: false,
          policyVersion: POLICY_VERSION,
        }),
        call(1, "propose_new_chart", {
          outcome: "DENY",
          reasonCode: "CANDIDATE_IN_REVIEW_OR_HIGHER",
          handoffRequired: true,
          policyVersion: POLICY_VERSION,
          evidenceIds: [
            { kind: "CANDIDATE_RECORD", id: existing.id },
            { kind: "MATCH_DECISION", id: pair.decision.id },
          ],
        }),
      ],
    };
  }

  private degradedTurn(session: IntakeSession, userText: string, turnIndex: number): IntakeTurn {
    return {
      turnIndex,
      userText,
      assistantText: TEMPLATE_TEXT,
      assistantTextSource: "TEMPLATE",
      agentMode: "REPLAY",
      degraded: "REPLAY_INPUT_MISMATCH",
      registration: session.registration,
      toolCalls: [],
    };
  }
}
