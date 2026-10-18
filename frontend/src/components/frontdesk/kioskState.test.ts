import { describe, expect, it } from "vitest";
import type { IntakeSession, IntakeTurn } from "@/api/types";
import { FixtureSource } from "@/data/fixtureSource";
import { scenario } from "@/data/scenario";
import { kioskState, patientGivenName } from "./kioskState";

async function checkIn(text: string): Promise<IntakeSession> {
  const s = new FixtureSource(scenario);
  const session = await s.startIntake("EN");
  const turn = await s.sendTurn(session.id, text, "k1");
  return { ...session, turns: [turn], registration: turn.registration };
}

const fresh: IntakeSession = {
  id: "s",
  createdAt: "2026-10-18T00:00:00Z",
  language: "EN",
  agentMode: "REPLAY",
  registration: { state: "NONE", handoffPairIds: [] },
  promptVersion: "fixture",
  toolSchemaVersion: "fd-tools/1",
  turns: [],
  closed: false,
};

describe("kioskState", () => {
  it("is idle before the first message, and while the check-in itself is still loading", () => {
    expect(kioskState({ session: fresh, pending: false, failed: false, decided: null })).toBe("idle");
    expect(kioskState({ session: undefined, pending: false, failed: false, decided: null })).toBe("idle");
  });

  it("is working while a turn is in flight, whatever the transcript holds", async () => {
    expect(kioskState({ session: fresh, pending: true, failed: false, decided: null })).toBe("working");
    const held = await checkIn(scenario.frontdeskIntake.utteranceEn);
    expect(kioskState({ session: held, pending: true, failed: false, decided: null })).toBe("working");
  });

  it("is held once the gate denied a new chart and no registrar has decided", async () => {
    const held = await checkIn(scenario.frontdeskIntake.utteranceEn);
    expect(kioskState({ session: held, pending: false, failed: false, decided: null })).toBe("held");
  });

  it("is replied after a turn the gate did not hold, and after a failed send", async () => {
    const replied = await checkIn("I have an appointment at three.");
    expect(kioskState({ session: replied, pending: false, failed: false, decided: null })).toBe("replied");
    expect(kioskState({ session: fresh, pending: false, failed: true, decided: null })).toBe("replied");
  });

  it("is done once a registrar linked the check-in, and rejected once every pair was rejected", async () => {
    const held = await checkIn(scenario.frontdeskIntake.utteranceEn);
    expect(kioskState({ session: held, pending: false, failed: false, decided: "LINKED" })).toBe("done");
    expect(kioskState({ session: held, pending: false, failed: false, decided: "REJECTED" })).toBe(
      "rejected",
    );
  });
});

describe("patientGivenName", () => {
  it("reads the given name the agent passed to its tools, never a hard-coded one", async () => {
    const held = await checkIn(scenario.frontdeskIntake.utteranceEn);
    const heard = (held.turns![0].toolCalls![0].args as { givenName: string }).givenName;
    expect(heard).toBeTruthy();
    expect(patientGivenName(held)).toBe(heard);
  });

  it("is null when no tool carried a name", async () => {
    expect(patientGivenName(fresh)).toBeNull();
    expect(patientGivenName(await checkIn("I have an appointment at three."))).toBeNull();
    const blank = {
      ...fresh,
      turns: [{ toolCalls: [{ args: { givenName: "  " } }] } as unknown as IntakeTurn],
    };
    expect(patientGivenName(blank)).toBeNull();
  });
});
