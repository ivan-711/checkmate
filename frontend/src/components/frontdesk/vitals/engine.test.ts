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
  type VitalLensInstance,
  wrapLens,
} from "./engine";
import { isVitalsOn, vitalsEnabled } from "./VitalsSlot";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

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

  it("takes the newest element when the library reports confidence per sample", () => {
    // The bundle's own widget reads heart_rate.confidence as a number or an array and shows the last
    // element; coercing the array to 0 made every real reading "unsteady".
    expect(readHeartRate({ vitals: { heart_rate: { value: 70, confidence: [0.2, 0.5, 0.9] } } })).toEqual({
      bpm: 70,
      confidence: 0.9,
    });
    expect(readHeartRate({ vitals: { heart_rate: { value: 70, confidence: [] } } })).toEqual({
      bpm: 70,
      confidence: 0,
    });
    expect(readHeartRate({ vitals: { heart_rate: { value: 70, confidence: ["high"] } } })).toEqual({
      bpm: 70,
      confidence: 0,
    });
  });

  it("does not start the stream when stopped while the library is still attaching it", async () => {
    let attached!: () => void;
    const lens = {
      addEventListener: vi.fn(),
      setVideoStream: vi.fn(
        () =>
          new Promise<void>((resolve) => {
            attached = resolve;
          }),
      ),
      startVideoStream: vi.fn(),
      stopVideoStream: vi.fn(),
      close: vi.fn().mockResolvedValue(undefined),
    } satisfies VitalLensInstance;
    const engine = wrapLens(lens);
    const starting = engine.start({} as MediaStream, {} as HTMLVideoElement, () => undefined);
    await engine.stop();
    attached();
    await starting;
    expect(lens.startVideoStream).not.toHaveBeenCalled();
    expect(lens.close).toHaveBeenCalledTimes(1);
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
  it("is off unless the flag value is exactly on", () => {
    expect(isVitalsOn(undefined)).toBe(false);
    expect(isVitalsOn("")).toBe(false);
    expect(isVitalsOn("true")).toBe(false);
    expect(isVitalsOn("on")).toBe(true);
  });

  it("reads the flag from NEXT_PUBLIC_VITALS", () => {
    vi.stubEnv("NEXT_PUBLIC_VITALS", "on");
    expect(vitalsEnabled()).toBe(true);
    vi.stubEnv("NEXT_PUBLIC_VITALS", "");
    expect(vitalsEnabled()).toBe(false);
  });

  it("has the same keys in English and Spanish", () => {
    expect(Object.keys(VITALS_COPY.es).sort()).toEqual(Object.keys(VITALS_COPY.en).sort());
  });

  it("labels the panel a constructed wellness demo in both languages", () => {
    expect(VITALS_COPY.en.label).toBe("Constructed demo, wellness only");
    expect(VITALS_COPY.es.label).toBe("Demostración construida, solo bienestar");
  });

  it("carries the exact footer the kiosk must show", () => {
    expect(VITALS_COPY.en.footer).toBe(
      "Wellness estimate only, not a medical measurement. Not saved, not sent to staff, not used for check-in.",
    );
    expect(VITALS_COPY.es.footer).toBe(
      "Solo una estimación de bienestar, no una medición médica. No se guarda, no se envía al personal y no se usa para el registro.",
    );
  });

  // eval/acceptance/g16.spec.ts NEVER_SAY plus the on-screen words DESIGN.md bans.
  const BANNED = [
    "prevented",
    "would have died",
    "the ai caught",
    "contraindicated for this patient",
    "fatal",
    "thinking",
    "diagnos", // diagnosis, diagnose, diagnosed, diagnostic, diagnóstico
    "calibrat", // calibrated, calibration, calibrado
  ];

  it("never puts a banned word on screen in either language", () => {
    for (const language of ["en", "es"] as const) {
      for (const value of Object.values(VITALS_COPY[language])) {
        const text = (typeof value === "function" ? value(72) : value).toLowerCase();
        for (const banned of BANNED) expect(text, `${language}: "${text}"`).not.toContain(banned);
      }
    }
  });
});
