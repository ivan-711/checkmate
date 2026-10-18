import { describe, expect, it } from "vitest";
import type { IntakeSession, IntakeTurn } from "@/api/types";
import { newChartFacts } from "./kioskNewChart";

const allowed = {
  toolName: "propose_new_chart",
  args: {
    givenName: "Teodoro",
    familyName: "Quintanilla Abasolo",
    birthDate: "1951-11-09",
    phone: "555-012-7734",
    evidence: {
      givenName: "Teodoro",
      familyName: "Quintanilla Abasolo",
      birthDate: "November 9, 1951",
      phone: "555-012-7734",
    },
  },
  gate: { outcome: "ALLOW" },
} as unknown as NonNullable<IntakeTurn["toolCalls"]>[number];

const session = (state: IntakeSession["registration"]["state"], calls = [allowed]) =>
  ({
    registration: { state, handoffPairIds: [] },
    turns: [{ toolCalls: calls } as unknown as IntakeTurn],
  }) as unknown as IntakeSession;

describe("newChartFacts", () => {
  it("reads the new chart's name, date of birth and phone as the patient typed them", () => {
    expect(newChartFacts(session("NEW_CHART"))).toEqual({
      name: "Teodoro Quintanilla Abasolo",
      birthDate: "November 9, 1951",
      phone: "555-012-7734",
    });
  });

  it("is nothing while a check-in is held, linked or not started", () => {
    expect(newChartFacts(session("PENDING_REGISTRAR"))).toBeNull();
    expect(newChartFacts(session("LINKED"))).toBeNull();
    expect(newChartFacts(undefined)).toBeNull();
  });

  it("falls back to the validated arguments where no quote was kept", () => {
    const bare = { ...allowed, args: { givenName: "Ana", familyName: "Ruiz", birthDate: "1990-01-02" } };
    expect(newChartFacts(session("NEW_CHART", [bare]))).toEqual({
      name: "Ana Ruiz",
      birthDate: "1990-01-02",
      phone: null,
    });
  });
});
