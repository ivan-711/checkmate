import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { CandidatePairDetail, IntakeSession, IntakeTurn } from "@/api/types";
import { DataSourceProvider } from "@/data/DataSourceProvider";
import { FixtureSource } from "@/data/fixtureSource";
import { scenario } from "@/data/scenario";
import { COPY } from "./copy";
import { handoffPairKey, INTAKE_KEY } from "./intake";
import { KioskPane } from "./KioskPane";

/** The kiosk with one check-in already in the cache, rendered for real. A decided hand-off pair
 * goes in the cache too, as the registrar pane's approval leaves it. */
function renderKiosk(session: IntakeSession, decided?: CandidatePairDetail): string {
  const queryClient = new QueryClient();
  queryClient.setQueryData(INTAKE_KEY, session);
  if (decided) queryClient.setQueryData(handoffPairKey(decided.pair.id), decided);
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(DataSourceProvider, null, createElement(KioskPane)),
    ),
  );
}

async function checkIn(text: string): Promise<{ session: IntakeSession; turn: IntakeTurn }> {
  const s = new FixtureSource(scenario);
  const session = await s.startIntake("EN");
  const turn = await s.sendTurn(session.id, text, "k1");
  return { session: { ...session, turns: [turn], registration: turn.registration }, turn };
}

function decidedPair(status: "LINKED" | "REJECTED"): CandidatePairDetail {
  const { pair } = scenario;
  return { ...pair, pair: { ...pair.pair, decision: { ...pair.pair.decision, status } } };
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

/** Text a patient can see: every text node outside a closed disclosure, tags stripped. */
function visibleText(html: string): string {
  return html
    .replace(/<details[\s\S]*?<\/details>/g, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ");
}

const state = (html: string) => html.match(/data-testid="kiosk"[^>]*data-k="([a-z]+)"/)?.[1];

describe("KioskPane states", () => {
  it("opens idle: the welcome, the demo line with Use this, a tall composer, the promise and a visible disabled Send", () => {
    const html = renderKiosk(fresh);
    expect(state(html)).toBe("idle");
    expect(html).toContain(COPY.en.title);
    expect(html).toContain(COPY.en.sub);
    expect(html).toContain(`>${COPY.en.demoLabel}<`);
    expect(html).toContain(scenario.frontdeskIntake.utteranceEn);
    expect(html).toMatch(/<button[^>]*>Use this<\/button>/);
    expect(html).toMatch(/data-testid="kiosk-composer"[^>]*placeholder="Your name and date of birth"/);
    expect(html).toMatch(/data-testid="kiosk-send"[^>]*disabled/);
    const promise = html.slice(html.indexOf('data-testid="kiosk-promise"'));
    expect(promise.slice(0, promise.indexOf("</p>"))).toContain("FrontDesk gets it ready.");
    expect(html).toContain(COPY.en.foot);
    expect(html).not.toContain("Start over");
  });

  it("holds: a past-tense checklist ends on the gate step, then the gate card, then a reply box", async () => {
    const { session, turn } = await checkIn(scenario.frontdeskIntake.utteranceEn);
    const html = renderKiosk(session);
    expect(state(html)).toBe("held");
    expect(html).toContain(`>${COPY.en.ready}<`);
    const steps = html.slice(html.indexOf('data-testid="turn-steps"'), html.indexOf("</ol>"));
    const order = ["Read your check-in", "Found a chart that may be yours", "Asked to open a new chart"].map(
      (s) => steps.indexOf(s),
    );
    expect(order).toEqual([...order].sort((a, b) => a - b));
    expect(order[0]).toBeGreaterThan(-1);
    // The gate step is the checklist's last row and carries the gate's codes as data, not text.
    const last = steps.slice(steps.lastIndexOf("<li"));
    expect(last).toMatch(/data-testid="gate-fact"/);
    expect(last).toMatch(/data-outcome="HELD"/);
    expect(last).toMatch(/data-reason="CANDIDATE_IN_REVIEW_OR_HIGHER"/);
    expect(last).toContain("Checked with the identity gate: held");
    // Each tool step keeps its tool id in a data attribute.
    expect(html.match(/data-testid="tool-call-chip"/g)).toHaveLength(2);
    expect(html).toMatch(/data-tool="search_patients"[^>]*data-outcome="ALLOW"/);
    expect(html).toMatch(/data-tool="propose_new_chart"[^>]*data-outcome="DENY"/);
    // The gate card follows the checklist.
    const card = html.indexOf('data-testid="gate-card"');
    expect(card).toBeGreaterThan(html.indexOf('data-testid="gate-fact"'));
    expect(html).toContain(COPY.en.gateLabel);
    expect(html).toContain(COPY.en.gateTitle);
    expect(html).toContain(turn.toolCalls![1].candidates![0].p.toFixed(2));
    expect(html).toContain(COPY.en.gateHeld);
    expect(html).toMatch(/data-testid="gate-card"[^>]*data-policy="frontdesk-gate\/1"/);
    expect(html).toMatch(/data-testid="gate-card"[^>]*data-tool="propose_new_chart"/);
    // The composer shrinks to a reply box; the demo line is gone; Start over is offered.
    expect(html).toMatch(/data-testid="kiosk-composer"[^>]*placeholder="Type a reply"/);
    expect(html).not.toContain("Use this");
    expect(html).toContain(">Start over<");
    // No agent line repeats the hand-off: the gate card's held line says it once.
    expect(html).not.toContain(turn.assistantText);
  });

  it("shows the patient no machine names: tool ids, policy ids, reason codes, system codes or modes", async () => {
    const { session } = await checkIn(scenario.frontdeskIntake.utteranceEn);
    const text = visibleText(renderKiosk(session));
    for (const raw of ["propose_new_chart", "search_patients", "frontdesk-gate", "CANDIDATE_IN_REVIEW_OR_HIGHER", "ER_FHIR", "CLINIC_CSV", "REPLAY"])
      expect(text, raw).not.toContain(raw);
  });

  it("keeps the masked candidate and its evidence rows under Details, in plain words", async () => {
    const { session, turn } = await checkIn(scenario.frontdeskIntake.utteranceEn);
    const html = renderKiosk(session);
    const details = html.slice(html.indexOf("<details"), html.indexOf("</details>"));
    expect(details).toContain(COPY.en.gateCandidate);
    const candidate = turn.toolCalls![1].candidates![0];
    expect(details).toContain(`Chart ••••${candidate.recordId.slice(-2)} · Clinic`);
    expect(details).toContain("Date of birth");
    expect(details).toContain(COPY.en.gateHidden);
    expect(details).not.toContain("CLINIC_CSV");
  });

  it("is done once a registrar linked the check-in: greets by the name the agent heard, no composer", async () => {
    const { session, turn } = await checkIn(scenario.frontdeskIntake.utteranceEn);
    const name = (turn.toolCalls![0].args as { givenName: string }).givenName;
    const html = renderKiosk(session, decidedPair("LINKED"));
    expect(state(html)).toBe("done");
    expect(html).toContain(COPY.en.doneTitle(name));
    expect(html).toContain(COPY.en.doneSub);
    for (const step of COPY.en.doneSteps) expect(html).toContain(step);
    expect(html).not.toContain('data-testid="kiosk-composer"');
    expect(html).not.toContain('data-testid="gate-card"');
    expect(html).toContain(">Start over<");
  });

  it("says a registrar is creating a new chart once every held pair was rejected", async () => {
    const { session } = await checkIn(scenario.frontdeskIntake.utteranceEn);
    const html = renderKiosk(session, decidedPair("REJECTED"));
    expect(state(html)).toBe("rejected");
    expect(html).toContain(COPY.en.rejected);
    expect(html).not.toContain(COPY.en.doneSub);
  });

  it("shows the agent's own reply on a turn that handed nothing off, labelled as an automatic message or AI agent", async () => {
    const { session, turn } = await checkIn("I have an appointment at three.");
    const html = renderKiosk(session);
    expect(state(html)).toBe("replied");
    expect(html).toContain(turn.assistantText);
    expect(html).toMatch(new RegExp(`data-voice="system"[^>]*>${turn.assistantText}<`));
    expect(html).toContain(COPY.en.automatic);
    expect(html).not.toContain('data-testid="turn-steps"');
    const model = { ...turn, assistantText: "Thank you, I am checking that now.", assistantTextSource: "MODEL" as const };
    const agentHtml = renderKiosk({ ...session, turns: [model] });
    expect(agentHtml).toMatch(/data-voice="agent"[^>]*>Thank you, I am checking that now\.</);
    expect(agentHtml).toContain(COPY.en.aiAgent);
  });

  it("marks the kiosk with its language, so the crossfade swaps a labelled region", () => {
    expect(renderKiosk(fresh)).toMatch(/data-testid="kiosk"[^>]*lang="en"/);
  });
});
