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

describe("FixtureSource work queue", () => {
  it("lists nothing before Resolve, then the fixture pair with this session's decision", async () => {
    const s = source();
    expect(await s.getCandidatePairs({})).toEqual({ items: [], nextCursor: null });
    expect(await s.resolve()).toBeNull(); // no match-run receipt: REPLAY has no funnel
    await s.review(pairId, approve, "key-queue-1");
    const page = await s.getCandidatePairs({});
    expect(page.items.map((p) => [p.id, p.decision.status])).toEqual([[pairId, "LINKED"]]);
    expect(page.nextCursor).toBeNull();
  });

  it("lists the pair a FrontDesk check-in handed off, before any Resolve, with its decision", async () => {
    const s = source();
    const { id } = await s.startIntake("EN");
    await s.sendTurn(id, scenario.frontdeskIntake.utteranceEn, "k1");
    expect((await s.getCandidatePairs({})).items.map((p) => [p.id, p.origin])).toEqual([
      [pairId, "FRONTDESK_HANDOFF"],
    ]);
    expect((await s.getCandidatePairs({ origin: "FRONTDESK_HANDOFF" })).items).toHaveLength(1);
    await s.review(pairId, approve, "key-queue-3");
    const page = await s.getCandidatePairs({});
    expect(page.items.map((p) => p.decision.status)).toEqual(["LINKED"]);
    await s.reset();
    expect((await s.getCandidatePairs({})).items).toEqual([]);
  });

  it("keeps the pair's first origin in the list and the detail, through a later Resolve", async () => {
    const s = source();
    const origins = async () => [
      (await s.getCandidatePairs({})).items[0]?.origin,
      (await s.getCandidatePair(pairId)).pair.origin,
      (await s.getCase()).detail!.pair.origin,
    ];
    const { id } = await s.startIntake("EN");
    await s.sendTurn(id, scenario.frontdeskIntake.utteranceEn, "k1");
    expect(await origins()).toEqual(["FRONTDESK_HANDOFF", "FRONTDESK_HANDOFF", "FRONTDESK_HANDOFF"]);
    await s.resolve(); // a match run upserts the stored pair and keeps its origin (_UPSERT_PAIR)
    expect(await origins()).toEqual(["FRONTDESK_HANDOFF", "FRONTDESK_HANDOFF", "FRONTDESK_HANDOFF"]);
    expect((await s.getCandidatePairs({ origin: "FRONTDESK_HANDOFF" })).items).toHaveLength(1);
  });

  it("a pair Resolve stored first stays a match-run pair after a FrontDesk hand-off", async () => {
    const s = source();
    await s.resolve();
    const { id } = await s.startIntake("EN");
    await s.sendTurn(id, scenario.frontdeskIntake.utteranceEn, "k1");
    expect((await s.getCandidatePairs({})).items[0].origin).toBe("MATCH_RUN");
    expect((await s.getCandidatePair(pairId)).pair.origin).toBe("MATCH_RUN");
    await s.reset();
    expect((await s.getCandidatePairs({})).items).toEqual([]);
  });

  it("filters by band and status the way the API does", async () => {
    const s = source();
    await s.resolve();
    const { band } = scenario.pair.pair.decision;
    expect((await s.getCandidatePairs({ band, status: "PROPOSED" })).items).toHaveLength(1);
    expect((await s.getCandidatePairs({ status: "LINKED" })).items).toHaveLength(0);
  });

  it("opens the fixture pair by id with the shared session state, and nothing else", async () => {
    const s = source();
    await s.review(pairId, reject, "key-queue-2");
    expect((await s.getCase(pairId)).detail!.pair.decision.status).toBe("REJECTED");
    expect((await s.getCase()).detail!.pair.decision.status).toBe("REJECTED");
    await expect(s.getCandidatePair("00000000-0000-4000-8000-000000000099")).rejects.toMatchObject({
      code: "NOT_FOUND",
    });
  });
});
