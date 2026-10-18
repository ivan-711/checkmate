import { describe, expect, it, vi } from "vitest";
import type { CandidatePairDetail, ReviewRequest, ReviewResponse } from "@/api/types";
import { scenario } from "@/data/scenario";
import { attachablePair, planReviews, reviewable, runReviews } from "./reviewPlan";

const hero = scenario.pair;
const kiosk = "kiosk-record";

function handoff(
  id: string,
  p: number,
  status: "PROPOSED" | "LINKED" | "REJECTED" = "PROPOSED",
): CandidatePairDetail {
  return {
    ...hero,
    pair: {
      ...hero.pair,
      id,
      origin: "FRONTDESK_HANDOFF",
      recordAId: kiosk,
      recordBId: hero.pair.recordAId,
      decision: { ...hero.pair.decision, p, status },
    },
  };
}

describe("attachablePair", () => {
  it("is the highest-scoring hand-off pair still waiting on a person", () => {
    const pairs = [handoff("low", 0.66), handoff("high", 0.98)];
    expect(attachablePair(pairs, hero.pair.id)?.pair.id).toBe("high");
  });

  it("is nothing when no hand-off pair is waiting, or when the only one is the pair under review", () => {
    expect(attachablePair([handoff("done", 0.98, "LINKED")], hero.pair.id)).toBeNull();
    expect(
      attachablePair(
        [{ ...handoff("same", 0.98), pair: { ...handoff("same", 0.98).pair, id: hero.pair.id } }],
        hero.pair.id,
      ),
    ).toBeNull();
    expect(attachablePair([], hero.pair.id)).toBeNull();
  });
});

describe("planReviews", () => {
  const actor = "registrar:Registrar A";

  it("an approve with the attach row on posts the pair under review first, then the check-in, each with its own key", () => {
    const plan = planReviews({
      pairId: hero.pair.id,
      body: { action: "APPROVE", actor, note: "checked phone" },
      attach: { pairId: "handoff-1", on: true },
      keys: { primary: "key-1", attach: "key-2" },
    });
    expect(plan.map((step) => [step.pairId, step.key, step.body.action])).toEqual([
      [hero.pair.id, "key-1", "APPROVE"],
      ["handoff-1", "key-2", "APPROVE"],
    ]);
    // The check-in's approval carries the registrar and no note of its own.
    expect(plan[1].body).toEqual({ action: "APPROVE", actor, note: null });
  });

  it("a reject never touches the check-in, and an approve with the row off posts one review", () => {
    const reject: ReviewRequest = {
      action: "REJECT",
      actor,
      reasonCode: "INSUFFICIENT_EVIDENCE",
      note: null,
    };
    expect(
      planReviews({
        pairId: hero.pair.id,
        body: reject,
        attach: { pairId: "handoff-1", on: true },
        keys: { primary: "k", attach: "k2" },
      }),
    ).toHaveLength(1);
    expect(
      planReviews({
        pairId: hero.pair.id,
        body: { action: "APPROVE", actor, note: null },
        attach: { pairId: "handoff-1", on: false },
        keys: { primary: "k", attach: "k2" },
      }),
    ).toHaveLength(1);
    expect(
      planReviews({
        pairId: hero.pair.id,
        body: { action: "APPROVE", actor, note: null },
        attach: null,
        keys: { primary: "k", attach: "k2" },
      }),
    ).toHaveLength(1);
  });
});

describe("runReviews", () => {
  const response = (pairId: string): ReviewResponse => ({
    decision: { ...hero.pair.decision, pairId, status: "LINKED" },
    entity: null,
    alerts: [],
  });

  it("posts the steps one after the other and returns both responses", async () => {
    const calls: string[] = [];
    const review = vi.fn(async (pairId: string, _body: ReviewRequest, key: string) => {
      calls.push(`${pairId}:${key}`);
      return response(pairId);
    });
    const result = await runReviews(review, [
      { pairId: "a", body: { action: "APPROVE", actor: "r", note: null }, key: "k1" },
      { pairId: "b", body: { action: "APPROVE", actor: "r", note: null }, key: "k2" },
    ]);
    expect(calls).toEqual(["a:k1", "b:k2"]);
    expect(result.primary.decision.pairId).toBe("a");
    expect(result.attach?.decision.pairId).toBe("b");
    expect(result.attachError).toBeNull();
  });

  it("a failed second approval keeps the first and reports the failure instead of throwing", async () => {
    const review = vi.fn(async (pairId: string) => {
      if (pairId === "b") throw new Error("boom");
      return response(pairId);
    });
    const result = await runReviews(review, [
      { pairId: "a", body: { action: "APPROVE", actor: "r", note: null }, key: "k1" },
      { pairId: "b", body: { action: "APPROVE", actor: "r", note: null }, key: "k2" },
    ]);
    expect(result.primary.decision.pairId).toBe("a");
    expect(result.attach).toBeNull();
    expect(result.attachError?.message).toBe("boom");
  });

  it("a failed first review throws, so nothing else is posted", async () => {
    const review = vi.fn(async () => {
      throw new Error("down");
    });
    await expect(
      runReviews(review, [
        { pairId: "a", body: { action: "APPROVE", actor: "r", note: null }, key: "k1" },
        { pairId: "b", body: { action: "APPROVE", actor: "r", note: null }, key: "k2" },
      ]),
    ).rejects.toThrow("down");
    expect(review).toHaveBeenCalledTimes(1);
  });
});

describe("reviewable", () => {
  const decision = scenario.pair.pair.decision;
  it("a proposed pair is open for review", () => {
    expect(reviewable({ ...decision, status: "PROPOSED" }, false)).toBe(true);
  });

  it("a rejection for not enough evidence reopens only after Resolve again", () => {
    const rejected = { ...decision, status: "REJECTED" as const, reasonCode: "INSUFFICIENT_EVIDENCE" as const };
    expect(reviewable(rejected, false)).toBe(false);
    expect(reviewable(rejected, true)).toBe(true);
  });

  it("a different-person rejection or a link never reopens", () => {
    expect(reviewable({ ...decision, status: "REJECTED", reasonCode: "DIFFERENT_PERSON" }, true)).toBe(false);
    expect(reviewable({ ...decision, status: "LINKED" }, true)).toBe(false);
    expect(reviewable(null, true)).toBe(false);
  });
});
