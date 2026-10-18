import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { IntakeSession, IntakeTurn } from "@/api/types";
import { SESSION_CHANGE_KEY } from "@/components/ui/ResetButton";
import { DataSourceProvider } from "@/data/DataSourceProvider";
import { FixtureSource } from "@/data/fixtureSource";
import { scenario } from "@/data/scenario";
import { COPY } from "./copy";
import { INTAKE_KEY, SEND_TURN_KEY } from "./intake";
import { KioskPane } from "./KioskPane";

/** The kiosk with one check-in already in the cache, rendered for real. */
function renderKiosk(session: IntakeSession, queryClient = new QueryClient()): string {
  queryClient.setQueryData(INTAKE_KEY, session);
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

/** How many FrontDesk lines the transcript shows (the speaker label heads each one). */
function agentLines(html: string): number {
  // The transcript is the outermost list; a turn's step checklist nests inside it.
  const transcript = html.slice(html.indexOf("<ol"), html.lastIndexOf("</ol>"));
  return transcript.split(`>${COPY.en.speaker}<`).length - 1;
}

describe("KioskPane transcript", () => {
  it("closes a turn the gate handed off with one automatic line, not a second one that repeats it", async () => {
    const { session, turn } = await checkIn(scenario.frontdeskIntake.utteranceEn);
    const html = renderKiosk(session);
    expect(html).toContain(COPY.en.handoff);
    expect(html).not.toContain(turn.assistantText);
    expect(agentLines(html)).toBe(1);
  });

  it("shows the agent's own reply on a turn that handed nothing off", async () => {
    const { session, turn } = await checkIn("I have an appointment at three.");
    const html = renderKiosk(session);
    expect(html).toContain(turn.assistantText);
    expect(html).not.toContain(COPY.en.handoff);
    expect(agentLines(html)).toBe(1);
  });

  it("promises under the composer that nothing is linked until staff approve", async () => {
    const { session } = await checkIn("I have an appointment at three.");
    const html = renderKiosk(session);
    expect(html).toContain('data-testid="kiosk-promise"');
    expect(html).toContain(COPY.en.promise);
  });

  it("finishes a held check-in by naming what did not happen", async () => {
    const held = renderKiosk((await checkIn(scenario.frontdeskIntake.utteranceEn)).session);
    expect(held).toContain('data-testid="kiosk-finish-held"');
    expect(held).toContain(COPY.en.heldFinish);
    const notHeld = renderKiosk((await checkIn("I have an appointment at three.")).session);
    expect(notHeld).not.toContain(COPY.en.heldFinish);
  });

  it("sets the agent's own words in the gray agent tone and system text in the verified tone", async () => {
    const { session, turn } = await checkIn("I have an appointment at three.");
    const model = {
      ...turn,
      assistantText: "Thank you, I am checking that now.",
      assistantTextSource: "MODEL" as const,
    };
    const agentHtml = renderKiosk({ ...session, turns: [model] });
    expect(agentHtml).toMatch(/data-voice="agent"[^>]*>Thank you, I am checking that now\.</);
    expect(agentHtml).toMatch(/data-voice="agent"[^>]*class="[^"]*text-ink-2/);
    // The template is written by the system, not the model: it reads as a fact.
    expect(renderKiosk(session)).toMatch(new RegExp(`data-voice="system"[^>]*>${turn.assistantText}<`));
  });

  it("tags the gate's fact and the gate card as a rule result, in plain words, in near-black", async () => {
    const held = renderKiosk((await checkIn(scenario.frontdeskIntake.utteranceEn)).session);
    expect(held).toMatch(/data-testid="gate-fact"[^>]*data-voice="verified"/);
    const card = held.slice(held.indexOf('data-testid="gate-card"'));
    expect(card.slice(0, card.indexOf("</h4>"))).toContain(`>${COPY.en.ruleResult}<`);
    const fact = held.slice(held.indexOf('data-testid="gate-fact"'));
    const factHtml = fact.slice(0, fact.indexOf("</li>"));
    expect(factHtml).toContain(`>${COPY.en.ruleResult}<`);
    expect(factHtml).toContain(COPY.en.reason.CANDIDATE_IN_REVIEW_OR_HIGHER);
    expect(factHtml).not.toContain(">CANDIDATE_IN_REVIEW_OR_HIGHER<");
  });

  it("lists the turn's steps and ends them on the gate fact, keeping the chips and the gate card", async () => {
    const html = renderKiosk((await checkIn(scenario.frontdeskIntake.utteranceEn)).session);
    const steps = html.slice(html.indexOf('data-testid="turn-steps"'));
    expect(steps.indexOf("Read your check-in")).toBeLessThan(steps.indexOf('data-testid="gate-fact"'));
    expect(steps.indexOf("Asked to create a new chart")).toBeLessThan(
      steps.indexOf('data-testid="gate-fact"'),
    );
    expect(html.match(/data-testid="tool-call-chip"/g)).toHaveLength(2);
    expect(html).toContain('data-testid="gate-card"');
  });
});

/** A client whose cache holds a mutation under `mutationKey` that never settles: the kiosk sees
 * it the way it sees a turn or a reset in flight, through useIsMutating. */
function inFlight(mutationKey: readonly unknown[]): QueryClient {
  const queryClient = new QueryClient();
  const mutation = queryClient
    .getMutationCache()
    .build(queryClient, { mutationKey: [...mutationKey], mutationFn: () => new Promise<never>(() => {}) });
  void mutation.execute(undefined);
  return queryClient;
}

/** Whether the button that reads `label` is rendered disabled (the attribute, not a class). */
function isDisabled(html: string, label: string): boolean {
  const end = html.indexOf(`>${label}</button>`);
  expect(end, `a "${label}" button`).toBeGreaterThan(-1);
  return html.slice(html.lastIndexOf("<button", end), end + 1).includes(' disabled=""');
}

describe("KioskPane while work is in flight", () => {
  it("locks Use this while the first turn is being read, so the line cannot go twice into one check-in", async () => {
    const fresh = await new FixtureSource(scenario).startIntake("EN");
    expect(isDisabled(renderKiosk(fresh), COPY.en.suggestUse)).toBe(false);
    expect(isDisabled(renderKiosk(fresh, inFlight(SEND_TURN_KEY)), COPY.en.suggestUse)).toBe(true);
  });

  it("locks Start over while the demo resets", async () => {
    const { session } = await checkIn(scenario.frontdeskIntake.utteranceEn);
    expect(isDisabled(renderKiosk(session), COPY.en.startOver)).toBe(false);
    expect(isDisabled(renderKiosk(session, inFlight(SESSION_CHANGE_KEY)), COPY.en.startOver)).toBe(true);
  });
});
