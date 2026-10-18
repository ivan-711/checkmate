import { describe, expect, it } from "vitest";
import type { IntakeSession, IntakeTurn } from "@/api/types";
import { needsNewCheckIn } from "./checkIn";

const session = (language: "EN" | "ES", turns: number) =>
  ({ language, turns: Array.from({ length: turns }, () => ({}) as IntakeTurn) }) as IntakeSession;

describe("needsNewCheckIn", () => {
  it("starts a new check-in when the toggle changed before the first turn", () => {
    expect(needsNewCheckIn(session("EN", 0), "ES")).toBe(true);
    expect(needsNewCheckIn(session("ES", 0), "EN")).toBe(true);
  });

  it("keeps a check-in already in the toggle's language", () => {
    expect(needsNewCheckIn(session("ES", 0), "ES")).toBe(false);
  });

  it("never restarts a conversation that has begun, or one still starting", () => {
    expect(needsNewCheckIn(session("EN", 1), "ES")).toBe(false);
    expect(needsNewCheckIn(undefined, "ES")).toBe(false);
  });
});
