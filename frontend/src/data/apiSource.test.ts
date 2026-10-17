import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { scenario } from "./scenario";
import { ApiSource } from "./apiSource";
import { DataError } from "./source";

interface Call {
  method: string;
  path: string;
  query: URLSearchParams;
  headers: Headers;
  body: unknown;
}

type Handler = (call: Call) => { status?: number; body: unknown };

/** A fetch stub keyed on "METHOD /path"; records every call so the tests can assert on them. */
function stubFetch(handlers: Record<string, Handler>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    // openapi-fetch hands over a Request; read method, headers and body from it.
    const request = input instanceof Request ? input : new Request(input, init);
    const url = new URL(request.url);
    const text = await request.text();
    const call: Call = {
      method: request.method,
      path: url.pathname,
      query: url.searchParams,
      headers: request.headers,
      body: text ? JSON.parse(text) : null,
    };
    calls.push(call);
    const handler = handlers[`${call.method} ${call.path}`];
    if (!handler)
      return new Response(
        JSON.stringify({ error: { code: "NOT_FOUND", message: `no stub for ${call.method} ${call.path}` } }),
        { status: 404, headers: { "content-type": "application/json" } },
      );
    const { status = 200, body } = handler(call);
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  });
  return calls;
}

const ORIGIN = "http://ui";
const hero = scenario.pair;
const heroIds = { recordAId: hero.pair.recordAId, recordBId: hero.pair.recordBId };
const twin = {
  ...hero.pair,
  id: "00000000-0000-4000-8000-000000000030",
  recordAId: "r-twin-a",
  recordBId: "r-twin-b",
  p: 0.55,
};

describe("ApiSource", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("reports LOCAL mode and offers no Undo", () => {
    const s = new ApiSource(ORIGIN);
    expect(s.mode).toBe("LOCAL");
    expect(s.canRestore).toBe(false);
  });

  it("Resolve identity posts a match run", async () => {
    const calls = stubFetch({
      "POST /api/v1/match-runs": () => ({ status: 201, body: { queuedPairIds: [hero.pair.id] } }),
    });
    await new ApiSource(ORIGIN).resolve();
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual(["POST /api/v1/match-runs"]);
  });

  it("binds the hero pair from the session's records, not the first queued pair", async () => {
    const calls = stubFetch({
      "POST /api/v1/sessions": () => ({ status: 201, body: scenario.session }),
      "GET /api/v1/candidate-pairs": () => ({
        body: { items: [twin, { ...hero.pair, ...heroIds }], nextCursor: null },
      }),
      [`GET /api/v1/candidate-pairs/${hero.pair.id}`]: () => ({ body: hero }),
    });
    const s = new ApiSource(ORIGIN);
    await s.reset();
    const { detail, outcome, resolved } = await s.getCase();
    expect(detail!.pair.id).toBe(hero.pair.id);
    expect(outcome).toBeNull();
    expect(resolved).toBe(true);
    expect(calls.find((c) => c.path === "/api/v1/sessions")?.body).toEqual({ scenarioId: "hero" });
    expect(calls.some((c) => c.path.endsWith(twin.id))).toBe(false);
  });

  it("refuses to guess between several queued pairs before a reset", async () => {
    stubFetch({
      "GET /api/v1/candidate-pairs": () => ({ body: { items: [twin, hero.pair], nextCursor: null } }),
    });
    await expect(new ApiSource(ORIGIN).getCase()).rejects.toBeInstanceOf(DataError);
  });

  it("sends the review with the caller's Idempotency-Key and the action discriminator", async () => {
    const response = { decision: { ...hero.pair.decision, status: "REJECTED" }, entity: null, alerts: [] };
    const calls = stubFetch({
      [`POST /api/v1/candidate-pairs/${hero.pair.id}/reviews`]: () => ({ status: 201, body: response }),
    });
    const body = {
      action: "REJECT",
      actor: "registrar:Registrar A",
      reasonCode: "INSUFFICIENT_EVIDENCE",
    } as const;
    const res = await new ApiSource(ORIGIN).review(hero.pair.id, body, "key-123");
    expect(res.decision.status).toBe("REJECTED");
    expect(calls[0].headers.get("Idempotency-Key")).toBe("key-123");
    expect(calls[0].body).toEqual(body);
  });

  it("maps the API error envelope to a DataError", async () => {
    stubFetch({
      [`POST /api/v1/candidate-pairs/${hero.pair.id}/reviews`]: () => ({
        status: 409,
        body: { error: { code: "DECISION_NOT_PENDING", message: "already decided" } },
      }),
    });
    await expect(
      new ApiSource(ORIGIN).review(hero.pair.id, { action: "APPROVE", actor: "registrar:A" }, "k"),
    ).rejects.toMatchObject({ code: "DECISION_NOT_PENDING" });
  });

  it("re-reads a LINKED pair's entity and alerts from the API instead of remembering them", async () => {
    const linked = { ...hero, pair: { ...hero.pair, decision: { ...hero.pair.decision, status: "LINKED" } } };
    const entityId = hero.mergePreview.entityIdIfApproved!;
    stubFetch({
      "GET /api/v1/candidate-pairs": () => ({ body: { items: [hero.pair], nextCursor: null } }),
      [`GET /api/v1/candidate-pairs/${hero.pair.id}`]: () => ({ body: linked }),
      [`GET /api/v1/entities/${entityId}`]: () => ({ body: scenario.entityIfApproved }),
      "GET /api/v1/alerts": (c) => ({
        body: {
          items: c.query.get("entityId") === scenario.entityIfApproved.id ? [scenario.alertIfApproved] : [],
          nextCursor: null,
        },
      }),
    });
    const { outcome } = await new ApiSource(ORIGIN).getCase();
    expect(outcome?.entity?.id).toBe(scenario.entityIfApproved.id);
    expect(outcome?.alerts).toHaveLength(1);
  });

  it("reads the whole event feed through nextCursor and the timeline through the entity route", async () => {
    const row = (eventType: string) => ({
      ts: "2026-10-17T20:00:00Z",
      eventId: crypto.randomUUID(),
      eventType,
      entryPoint: "API",
      actor: "system:test",
      actorType: "SYSTEM",
      mode: "LOCAL",
      payload: {},
    });
    const calls = stubFetch({
      "GET /api/v1/events": (c) =>
        c.query.get("cursor")
          ? { body: { items: [row("DEMO_RESET")], nextCursor: null } }
          : { body: { items: [row("LINK_APPROVED")], nextCursor: "c1" } },
      [`GET /api/v1/entities/${scenario.entityIfApproved.id}/timeline`]: () => ({
        body: { items: scenario.timelineIfApproved, nextCursor: null },
      }),
    });
    const s = new ApiSource(ORIGIN);
    const events = await s.getEvents();
    expect(events.map((e) => e.eventType)).toEqual(["LINK_APPROVED", "DEMO_RESET"]);
    expect(calls.filter((c) => c.path === "/api/v1/events").map((c) => c.query.get("limit"))).toEqual([
      "200",
      "200",
    ]);
    expect(await s.getTimeline(scenario.entityIfApproved.id)).toHaveLength(
      scenario.timelineIfApproved.length,
    );
  });

  it("treats a 501 timeline or alerts stub as not available, not as an error", async () => {
    stubFetch({
      [`GET /api/v1/entities/${scenario.entityIfApproved.id}/timeline`]: () => ({
        status: 501,
        body: { error: { code: "INTERNAL", message: "not implemented" } },
      }),
      "GET /api/v1/alerts": () => ({
        status: 501,
        body: { error: { code: "INTERNAL", message: "not implemented" } },
      }),
    });
    const s = new ApiSource(ORIGIN);
    expect(await s.getTimeline(scenario.entityIfApproved.id)).toBeNull();
    expect(await s.getAlerts(scenario.entityIfApproved.id)).toBeNull();
  });
});

describe("ApiSource after a reset", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows the session's source cards while the queue is empty, and resolved is false", async () => {
    stubFetch({
      "POST /api/v1/sessions": () => ({ status: 201, body: scenario.session }),
      "GET /api/v1/candidate-pairs": () => ({ body: { items: [], nextCursor: null } }),
    });
    const s = new ApiSource(ORIGIN);
    await s.reset();
    const { sources, detail, resolved } = await s.getCase();
    expect(sources.map((c) => c.record.sourceSystem)).toEqual(["ER_FHIR", "CLINIC_CSV"]);
    expect(detail).toBeNull();
    expect(resolved).toBe(false);
  });
});
