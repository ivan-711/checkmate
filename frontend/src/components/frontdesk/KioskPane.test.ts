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
  const transcript = html.slice(html.indexOf("<ol"), html.indexOf("</ol>"));
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
});
