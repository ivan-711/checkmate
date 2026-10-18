import { existsSync } from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VITALS_COPY } from "./copy";
import {
  createPulseEngine,
  isSteady,
  MIN_CONFIDENCE,
  MODEL_JSON,
  readHeartRate,
  VENDOR_BASE,
} from "./engine";
import { vitalsEnabled } from "./VitalsSlot";

afterEach(() => vi.unstubAllGlobals());

describe("pulse engine", () => {
  it("reads the heart rate out of a library result", () => {
    expect(readHeartRate({ vitals: { heart_rate: { value: 68.4, confidence: 0.8, unit: "bpm" } } })).toEqual({
      bpm: 68.4,
      confidence: 0.8,
    });
    expect(readHeartRate({ vitals: {}, message: "no face" })).toBeNull();
    expect(readHeartRate({ vitals: { heart_rate: { value: Number.NaN } } })).toBeNull();
    expect(readHeartRate(null)).toBeNull();
    expect(readHeartRate({ vitals: { heart_rate: { value: 70 } } })).toEqual({ bpm: 70, confidence: 0 });
  });

  it("calls a reading steady only at or above the confidence floor", () => {
    expect(isSteady({ bpm: 70, confidence: MIN_CONFIDENCE })).toBe(true);
    expect(isSteady({ bpm: 70, confidence: MIN_CONFIDENCE - 0.01 })).toBe(false);
    expect(isSteady(null)).toBe(false);
  });

  it("names the model file the pinned vitallens ships", () => {
    const dist = path.join(__dirname, "../../../../node_modules/vitallens/dist");
    expect(existsSync(path.join(dist, MODEL_JSON))).toBe(true);
  });

  it("refuses to load the library when the model is not served by this app", async () => {
    // A Next 404 page: the library would fall back to the CDN, so the engine must stop here.
    const fetchSpy = vi
      .fn()
      .mockResolvedValue(
        new Response("<html></html>", { status: 404, headers: { "content-type": "text/html" } }),
      );
    vi.stubGlobal("fetch", fetchSpy);
    await expect(createPulseEngine()).rejects.toThrow(/not served/);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0][0]).toBe(VENDOR_BASE + MODEL_JSON);
  });
});

describe("vitals flag and copy", () => {
  it("is off unless NEXT_PUBLIC_VITALS is exactly on", () => {
    expect(vitalsEnabled(undefined)).toBe(false);
    expect(vitalsEnabled("")).toBe(false);
    expect(vitalsEnabled("true")).toBe(false);
    expect(vitalsEnabled("on")).toBe(true);
  });

  it("has the same keys in English and Spanish", () => {
    expect(Object.keys(VITALS_COPY.es).sort()).toEqual(Object.keys(VITALS_COPY.en).sort());
  });
});
