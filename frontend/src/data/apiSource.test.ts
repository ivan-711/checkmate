import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { scenario } from "./scenario";
import { ApiSource } from "./apiSource";
import { EVENT_FEED_ROWS } from "./source";

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

  it("Resolve returns the match-run receipt, which the work queue's funnel reads", async () => {
    const run = { runId: "run-77", allPairs: 6, candidatePairs: 2 };
    stubFetch({ "POST /api/v1/match-runs": () => ({ status: 201, body: run }) });
    expect(await new ApiSource(ORIGIN).resolve()).toEqual(run);
  });

  it("lists a keyset page with its band and status filters", async () => {
    const calls = stubFetch({
      "GET /api/v1/candidate-pairs": () => ({ body: { items: [twin], nextCursor: "next-page" } }),
    });
    const page = await new ApiSource(ORIGIN).getCandidatePairs({
      band: "REVIEW",
      status: "PROPOSED",
      cursor: "cursor-1",
      limit: 12,
    });
    expect(page.nextCursor).toBe("next-page");
    expect(calls[0].query.toString()).toBe("band=REVIEW&status=PROPOSED&cursor=cursor-1&limit=12");
  });

  it("opens a selected non-hero pair without reading the hero session", async () => {
    const selected = { ...hero, pair: twin, recordA: hero.recordB, recordB: hero.recordA };
    const calls = stubFetch({
      [`GET /api/v1/candidate-pairs/${twin.id}`]: () => ({ body: selected }),
    });
    const result = await new ApiSource(ORIGIN).getCase(twin.id);
    expect(result.detail?.pair.id).toBe(twin.id);
    expect(result.sources).toEqual([selected.recordA, selected.recordB]);
    expect(calls.map((c) => c.path)).toEqual([`/api/v1/candidate-pairs/${twin.id}`]);
  });

  it("binds the hero by the session's first record and the other record, following nextCursor", async () => {
    const [first, second] = scenario.session.sources.map((c) => c.record.id);
    const other = { ...twin, recordAId: first, recordBId: "r-someone-else" };
    const calls = stubFetch({
      "POST /api/v1/sessions": () => ({ status: 201, body: scenario.session }),
      "GET /api/v1/sessions/current": () => ({ body: scenario.session }),
      "GET /api/v1/candidate-pairs": (c) =>
        c.query.get("cursor")
          ? { body: { items: [{ ...hero.pair, recordAId: second, recordBId: first }], nextCursor: null } }
          : { body: { items: [other], nextCursor: "page-2" } },
      [`GET /api/v1/candidate-pairs/${hero.pair.id}`]: () => ({ body: hero }),
    });
    const s = new ApiSource(ORIGIN);
    await s.reset();
    const { detail, resolved } = await s.getCase();
    expect(detail!.pair.id).toBe(hero.pair.id);
    expect(resolved).toBe(true);
    const lists = calls.filter((c) => c.path === "/api/v1/candidate-pairs");
    expect(lists.map((c) => c.query.get("recordId"))).toEqual([first, first]);
    expect(calls.find((c) => c.path === "/api/v1/sessions")?.body).toEqual({ scenarioId: "hero" });
    expect(calls.some((c) => c.path.endsWith(other.id))).toBe(false);
  });

  it("never shows a different pair as the hero when the session's pair is not queued", async () => {
    const [first] = scenario.session.sources.map((c) => c.record.id);
    const calls = stubFetch({
      "POST /api/v1/sessions": () => ({ status: 201, body: scenario.session }),
      "GET /api/v1/sessions/current": () => ({ body: scenario.session }),
      "GET /api/v1/candidate-pairs": () => ({
        body: { items: [{ ...twin, recordAId: first }, twin], nextCursor: null },
      }),
    });
    const s = new ApiSource(ORIGIN);
    await s.reset();
    const { detail, resolved, sources } = await s.getCase();
    expect(detail).toBeNull();
    expect(resolved).toBe(false);
    expect(sources).toEqual(scenario.session.sources);
    expect(calls.some((c) => c.path.startsWith("/api/v1/candidate-pairs/"))).toBe(false);
  });

  it("takes the cards only from the session's sources, in the session's order", async () => {
    const swapped = { ...hero, recordA: hero.recordB, recordB: hero.recordA };
    stubFetch({
      "POST /api/v1/sessions": () => ({ status: 201, body: scenario.session }),
      "GET /api/v1/sessions/current": () => ({ body: scenario.session }),
      "GET /api/v1/candidate-pairs": () => ({ body: { items: [hero.pair], nextCursor: null } }),
      [`GET /api/v1/candidate-pairs/${hero.pair.id}`]: () => ({ body: swapped }),
    });
    const s = new ApiSource(ORIGIN);
    await s.reset();
    expect((await s.getCase()).sources).toEqual(scenario.session.sources);
  });

  it("on page load rebinds the hero from GET /sessions/current", async () => {
    const calls = stubFetch({
      "GET /api/v1/sessions/current": () => ({ body: scenario.session }),
      "GET /api/v1/candidate-pairs": () => ({ body: { items: [hero.pair], nextCursor: null } }),
      [`GET /api/v1/candidate-pairs/${hero.pair.id}`]: () => ({ body: hero }),
    });
    const s = new ApiSource(ORIGIN);
    expect((await s.getSession())?.id).toBe(scenario.session.id);
    expect((await s.getCase()).detail!.pair.id).toBe(hero.pair.id);
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("follows a reset made elsewhere: the session is re-read, never kept from an earlier load", async () => {
    const other = {
      ...scenario.session,
      id: "00000000-0000-4000-8000-000000000199",
      sources: scenario.session.sources.map((c) => ({
        ...c,
        record: { ...c.record, id: `${c.record.id}-new` },
      })),
    };
    let current = scenario.session;
    const calls = stubFetch({
      "GET /api/v1/sessions/current": () => ({ body: current }),
      "GET /api/v1/candidate-pairs": () => ({ body: { items: [], nextCursor: null } }),
    });
    const s = new ApiSource(ORIGIN);
    expect((await s.getCase()).sources).toEqual(scenario.session.sources);
    current = other;
    expect((await s.getCase()).sources).toEqual(other.sources);
    const lists = calls.filter((c) => c.path === "/api/v1/candidate-pairs");
    expect(lists.at(-1)?.query.get("recordId")).toBe(other.sources[0].record.id);
  });

  it("shares one GET /sessions/current between callers that ask at the same time", async () => {
    const calls = stubFetch({ "GET /api/v1/sessions/current": () => ({ body: scenario.session }) });
    const s = new ApiSource(ORIGIN);
    await Promise.all([s.getSession(), s.getSession()]);
    expect(calls.filter((c) => c.path === "/api/v1/sessions/current")).toHaveLength(1);
  });

  it("asks only for match-run pairs, so a FrontDesk handoff pair is never bound as the hero", async () => {
    const calls = stubFetch({
      "GET /api/v1/sessions/current": () => ({ body: scenario.session }),
      "GET /api/v1/candidate-pairs": () => ({ body: { items: [], nextCursor: null } }),
    });
    await new ApiSource(ORIGIN).getCase();
    expect(calls.find((c) => c.path === "/api/v1/candidate-pairs")?.query.get("origin")).toBe("MATCH_RUN");
  });

  it("asks for a reset when the pages run out without finding the session's pair", async () => {
    const [first] = scenario.session.sources.map((c) => c.record.id);
    stubFetch({
      "GET /api/v1/sessions/current": () => ({ body: scenario.session }),
      "GET /api/v1/candidate-pairs": () => ({
        body: { items: [{ ...twin, recordAId: first }], nextCursor: "more" },
      }),
    });
    await expect(new ApiSource(ORIGIN).getCase()).rejects.toMatchObject({ code: "NO_SESSION" });
  });

  it.each([404, 501])("asks for a reset when GET /sessions/current answers %i", async (status) => {
    stubFetch({
      "GET /api/v1/sessions/current": () => ({
        status,
        body: { error: { code: "NOT_FOUND", message: "none" } },
      }),
    });
    const s = new ApiSource(ORIGIN);
    expect(await s.getSession()).toBeNull();
    await expect(s.getCase()).rejects.toMatchObject({ code: "NO_SESSION" });
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
      "GET /api/v1/sessions/current": () => ({ body: scenario.session }),
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
    const { outcome, alertsKnown } = await new ApiSource(ORIGIN).getCase();
    expect(outcome?.entity?.id).toBe(scenario.entityIfApproved.id);
    expect(outcome?.alerts).toHaveLength(1);
    expect(alertsKnown).toBe(true);
  });

  it.each([501, 500])("says nothing about the rule when the alerts read answers %i", async (status) => {
    const linked = { ...hero, pair: { ...hero.pair, decision: { ...hero.pair.decision, status: "LINKED" } } };
    const entityId = hero.mergePreview.entityIdIfApproved!;
    stubFetch({
      "GET /api/v1/sessions/current": () => ({ body: scenario.session }),
      "GET /api/v1/candidate-pairs": () => ({ body: { items: [hero.pair], nextCursor: null } }),
      [`GET /api/v1/candidate-pairs/${hero.pair.id}`]: () => ({ body: linked }),
      [`GET /api/v1/entities/${entityId}`]: () => ({ body: scenario.entityIfApproved }),
      "GET /api/v1/alerts": () => ({ status, body: { error: { code: "INTERNAL", message: "down" } } }),
    });
    const { outcome, alertsKnown } = await new ApiSource(ORIGIN).getCase();
    expect(outcome?.entity?.id).toBe(scenario.entityIfApproved.id);
    expect(alertsKnown).toBe(false);
  });

  it("reads one page of the event feed, never the whole log, and the timeline through the entity route", async () => {
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
      "GET /api/v1/events": () => ({
        body: { items: [row("LINK_APPROVED"), row("DEMO_RESET")], nextCursor: "c1" },
      }),
      [`GET /api/v1/entities/${scenario.entityIfApproved.id}/timeline`]: () => ({
        body: { items: scenario.timelineIfApproved, nextCursor: null },
      }),
    });
    const s = new ApiSource(ORIGIN);
    const events = await s.getEvents();
    expect(events.map((e) => e.eventType)).toEqual(["LINK_APPROVED", "DEMO_RESET"]);
    const eventCalls = calls.filter((c) => c.path === "/api/v1/events");
    expect(eventCalls.map((c) => [c.query.get("limit"), c.query.get("cursor")])).toEqual([
      [String(EVENT_FEED_ROWS), null],
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
      "GET /api/v1/sessions/current": () => ({ body: scenario.session }),
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
