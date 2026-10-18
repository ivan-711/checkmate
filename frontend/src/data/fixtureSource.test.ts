import { describe, expect, it } from "vitest";
import { scenario } from "./scenario";
import { FixtureSource } from "./fixtureSource";
import { DataError } from "./source";

const NOW = new Date("2026-10-17T19:32:08Z");
const pairId = scenario.pair.pair.id;
const approve = { action: "APPROVE", actor: "registrar:Registrar B" } as const;
const reject = {
  action: "REJECT",
  actor: "registrar:Registrar A",
  reasonCode: "DIFFERENT_PERSON",
} as const;

function source() {
  return new FixtureSource(scenario, () => NOW);
}

describe("FixtureSource", () => {
  it("reports REPLAY and starts with the proposed pair and no outcome", async () => {
    const s = source();
    const { detail, outcome } = await s.getCase();
    expect(s.mode).toBe("REPLAY");
    expect(detail!.pair.decision.status).toBe("PROPOSED");
    expect(detail!.recordA.displayLabel).toBe("ER FHIR");
    expect(outcome).toBeNull();
  });

  it("approve returns the linked entity and the alert", async () => {
    const res = await source().review(pairId, approve, "key-approve-1");
    expect(res.decision.status).toBe("LINKED");
    expect(res.decision.actor).toBe("registrar:Registrar B");
    expect(res.decision.actorType).toBe("REGISTRAR");
    expect(res.decision.decidedAt).toBe(NOW.toISOString());
    expect(res.entity?.id).toBe(scenario.entityIfApproved.id);
    expect(res.alerts?.map((a) => a.ruleId)).toEqual(["BL-AMOX-01"]);
  });

  it("reject leaves the records separate and the rule silent", async () => {
    const res = await source().review(pairId, reject, "key-reject-1");
    expect(res.decision.status).toBe("REJECTED");
    expect(res.decision.reasonCode).toBe("DIFFERENT_PERSON");
    expect(res.entity).toBeNull();
    expect(res.alerts).toEqual([]);
  });

  it("a second review supersedes the first: reject then approve", async () => {
    const s = source();
    await s.review(pairId, reject, "key-1");
    const res = await s.review(pairId, approve, "key-2");
    const { detail, outcome } = await s.getCase();
    expect(res.decision.version).toBe(3);
    expect(detail!.pair.decision.status).toBe("LINKED");
    expect(detail!.history?.map((d) => d.status)).toEqual(["PROPOSED", "REJECTED", "LINKED"]);
    expect(outcome?.entity?.id).toBe(scenario.entityIfApproved.id);
  });

  it("answers a repeat approve on a LINKED pair with the current decision and no new version", async () => {
    const s = source();
    const first = await s.review(pairId, approve, "key-a");
    const again = await s.review(pairId, { ...approve, actor: "registrar:Registrar C" }, "key-b");
    expect(again.decision).toEqual(first.decision);
    expect((await s.getCase()).detail!.history).toHaveLength(2);
  });

  it("refuses to reject a LINKED pair: DECISION_NOT_PENDING", async () => {
    const s = source();
    await s.review(pairId, approve, "key-a");
    await expect(s.review(pairId, reject, "key-b")).rejects.toMatchObject({ code: "DECISION_NOT_PENDING" });
    expect((await s.getCase()).detail!.pair.decision.status).toBe("LINKED");
  });

  it("a second reject supersedes the first with its own reason", async () => {
    const s = source();
    await s.review(pairId, reject, "key-a");
    const res = await s.review(pairId, { ...reject, reasonCode: "INSUFFICIENT_EVIDENCE" }, "key-b");
    expect(res.decision.version).toBe(3);
    expect(res.decision.reasonCode).toBe("INSUFFICIENT_EVIDENCE");
  });

  it("replays the same response for a retried idempotency key", async () => {
    const s = source();
    const first = await s.review(pairId, reject, "key-retry");
    const again = await s.review(pairId, reject, "key-retry");
    expect(again).toEqual(first);
    expect((await s.getCase()).detail!.history).toHaveLength(2);
  });

  it("rejects a reused key with a different body", async () => {
    const s = source();
    await s.review(pairId, reject, "key-reuse");
    await expect(s.review(pairId, approve, "key-reuse")).rejects.toMatchObject({
      code: "IDEMPOTENCY_MISMATCH",
    });
  });

  it("returns NOT_FOUND for an unknown pair", async () => {
    await expect(source().review("nope", approve, "key-x")).rejects.toBeInstanceOf(DataError);
  });

  it("gives the timeline only for the linked entity", async () => {
    const s = source();
    expect(await s.getTimeline(scenario.entityIfApproved.id)).toHaveLength(2);
    expect(await s.getTimeline("other")).toEqual([]);
  });

  it("reset returns to the fragmented state and restore brings the decision back", async () => {
    const s = source();
    expect(s.canRestore).toBe(true);
    await s.review(pairId, approve, "key-a");
    const session = await s.reset();
    expect((await s.getCase()).outcome).toBeNull();
    expect(session.previousSessionId).toBeTruthy();
    await s.restore(session.previousSessionId!);
    expect((await s.getCase()).detail!.pair.decision.status).toBe("LINKED");
  });

  it("refuses to restore a session it does not hold", async () => {
    await expect(source().restore("unknown")).rejects.toMatchObject({ code: "NOT_FOUND" });
  });
});

describe("FixtureSource G16 path", () => {
  it("waits for Resolve after a reset and logs one event per action, newest first", async () => {
    const s = source();
    expect((await s.getCase()).resolved).toBe(false);
    await s.reset();
    await s.resolve();
    expect((await s.getCase()).resolved).toBe(true);
    await s.review(pairId, { ...reject, reasonCode: "INSUFFICIENT_EVIDENCE" }, "k1");
    await s.resolve();
    const res = await s.review(pairId, approve, "k2");
    const types = (await s.getEvents()).map((e) => e.eventType);
    expect(types).toEqual([
      "ALERT_RAISED",
      "LINK_APPROVED",
      "MATCH_RUN_COMPLETED",
      "LINK_REJECTED",
      "MATCH_RUN_COMPLETED",
      "DEMO_RESET",
    ]);
    expect(await s.getAlerts(res.entity!.id)).toHaveLength(1);
    const tiles = await s.getTiles();
    expect(tiles.tiles.find((t) => t.id === "HUMAN_REVIEW")?.total).toBe(2);
    expect((await s.getSession()).heroProvisional).toBe(scenario.session.heroProvisional);
  });

  it("a reset clears the resolved state and the review count", async () => {
    const s = source();
    await s.resolve();
    await s.review(pairId, approve, "k1");
    await s.reset();
    expect((await s.getCase()).resolved).toBe(false);
    expect((await s.getTiles()).tiles.find((t) => t.id === "HUMAN_REVIEW")?.total).toBe(0);
  });
});
