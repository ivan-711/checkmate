import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { IntakeSession, IntakeTurn } from "@/api/types";
import { DataSourceProvider } from "@/data/DataSourceProvider";
import { FixtureSource } from "@/data/fixtureSource";
import { scenario } from "@/data/scenario";
import { COPY } from "./copy";
import { INTAKE_KEY } from "./intake";
import { KioskPane } from "./KioskPane";

/** The kiosk with one check-in already in the cache, rendered for real. */
function renderKiosk(session: IntakeSession): string {
  const queryClient = new QueryClient();
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

  it("tags the gate's fact and the gate card as verified, in near-black", async () => {
    const held = renderKiosk((await checkIn(scenario.frontdeskIntake.utteranceEn)).session);
    expect(held).toMatch(/data-testid="gate-fact"[^>]*data-voice="verified"/);
    const card = held.slice(held.indexOf('data-testid="gate-card"'));
    expect(card.slice(0, card.indexOf("</h4>"))).toContain(`>${COPY.en.verified}<`);
    const fact = held.slice(held.indexOf('data-testid="gate-fact"'));
    expect(fact.slice(0, fact.indexOf("</li>"))).toContain(`>${COPY.en.verified}<`);
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
