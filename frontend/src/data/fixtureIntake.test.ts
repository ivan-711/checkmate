import { describe, expect, it } from "vitest";
import { scenario } from "./scenario";
import { FixtureSource } from "./fixtureSource";
import { foldText } from "./fixtureIntake";
import { DataError } from "./source";

const NOW = new Date("2026-10-17T20:30:00Z");
const { utteranceEn, utteranceEs } = scenario.frontdeskIntake;

function gateTile(tiles: Awaited<ReturnType<FixtureSource["getTiles"]>>) {
  return tiles.tiles.find((t) => t.id === "AGENT_GATE")!;
}

describe("FixtureSource FrontDesk intake", () => {
  it("opens a REPLAY check-in with no registration", async () => {
    const session = await new FixtureSource(scenario, () => NOW).startIntake("EN");
    expect(session.agentMode).toBe("REPLAY");
    expect(session.registration.state).toBe("NONE");
    expect(session.turns).toEqual([]);
  });

  it("the suggested check-in is searched, denied a new chart at REVIEW and handed to a registrar", async () => {
    const s = new FixtureSource(scenario, () => NOW);
    const { id } = await s.startIntake("ES");
    const turn = await s.sendTurn(id, utteranceEs, "k1");
    const [search, propose] = turn.toolCalls!;
    expect(search.toolName).toBe("search_patients");
    expect(search.gate.outcome).toBe("ALLOW");
    expect(propose.toolName).toBe("propose_new_chart");
    expect(propose.gate).toMatchObject({
      outcome: "DENY",
      reasonCode: "CANDIDATE_IN_REVIEW_OR_HIGHER",
      handoffRequired: true,
      policyVersion: "frontdesk-gate/1",
    });
    // Well-formed calls carry their validated arguments; only an invalid call has null args.
    expect(propose.args).toMatchObject({ birthDate: scenario.pair.recordA.normalized.birthDate });
    expect(propose.candidates![0]).toMatchObject({
      band: scenario.pair.pair.decision.band,
      pairId: scenario.pair.pair.id,
    });
    expect(turn.registration).toEqual({
      state: "PENDING_REGISTRAR",
      handoffPairIds: [scenario.pair.pair.id],
    });
    expect(turn.assistantText).toMatch(/^Gracias/);
  });

  it("matches the suggestion with case, accents and spacing folded", async () => {
    expect(foldText("  Nací  EL 3 ")).toBe("naci el 3");
    const s = new FixtureSource(scenario, () => NOW);
    const { id } = await s.startIntake("EN");
    const turn = await s.sendTurn(id, utteranceEn.toUpperCase(), "k1");
    expect(turn.toolCalls).toHaveLength(2);
  });

  it("other text degrades to the template and calls no tool", async () => {
    const s = new FixtureSource(scenario, () => NOW);
    const { id } = await s.startIntake("EN");
    const turn = await s.sendTurn(id, "Hello, I have an appointment.", "k1");
    expect(turn).toMatchObject({
      degraded: "REPLAY_INPUT_MISMATCH",
      assistantTextSource: "TEMPLATE",
      toolCalls: [],
    });
    expect(turn.registration.state).toBe("NONE");
  });

  it("a retried key replays its turn; the same key with other text is refused", async () => {
    const s = new FixtureSource(scenario, () => NOW);
    const { id } = await s.startIntake("EN");
    const first = await s.sendTurn(id, utteranceEn, "k1");
    expect(await s.sendTurn(id, utteranceEn, "k1")).toBe(first);
    await expect(s.sendTurn(id, "something else", "k1")).rejects.toMatchObject({
      code: "IDEMPOTENCY_MISMATCH",
    });
    expect(gateTile(await s.getTiles()).total).toBe(2); // the retry is not counted again
  });

  it("an unknown check-in is NOT_FOUND", async () => {
    await expect(
      new FixtureSource(scenario, () => NOW).sendTurn("nope", utteranceEn, "k1"),
    ).rejects.toBeInstanceOf(DataError);
  });

  it("the AGENT_GATE tile counts every gate outcome and keeps them across a reset", async () => {
    const s = new FixtureSource(scenario, () => NOW);
    const { id } = await s.startIntake("EN");
    await s.sendTurn(id, utteranceEn, "k1");
    await s.reset();
    const tile = gateTile(await s.getTiles());
    const count = (series: string) =>
      tile.buckets.filter((b) => b.series === series).reduce((n, b) => n + b.count, 0);
    expect(tile.total).toBe(2);
    expect(count("ALLOW")).toBe(1);
    expect(count("DENY")).toBe(1);
    const events = (await s.getEvents()).map((e) => e.eventType);
    expect(events).toEqual(
      expect.arrayContaining(["INTAKE_STARTED", "AGENT_TOOL_CALLED", "INTAKE_HANDOFF_CREATED"]),
    );
  });
});
