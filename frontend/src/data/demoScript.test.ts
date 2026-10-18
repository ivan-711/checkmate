import { describe, expect, it } from "vitest";
import transcript from "@hero/frontdesk_transcript.json";
import { ApiSource } from "./apiSource";
import { DEMO_SCRIPT } from "./demoScript";

describe("demo script lines", () => {
  it("are the hero transcript's own lines, so the replay recognises them", () => {
    const lines = transcript.turns.map((turn) => turn.userText);
    expect(lines).toContain(DEMO_SCRIPT.es);
    expect(lines).toContain(DEMO_SCRIPT.en);
    expect(DEMO_SCRIPT.es).toMatch(/^Me llamo /);
    expect(DEMO_SCRIPT.en).toMatch(/^My name is /);
  });

  it("are what the API kiosk suggests, never the fixture's placeholder names", () => {
    const suggested = new ApiSource().suggestedCheckIn;
    expect(suggested).toEqual({ ...DEMO_SCRIPT, demoScript: true });
    expect(`${suggested.en} ${suggested.es}`).not.toMatch(/PLACEHOLDER/i);
  });
});
