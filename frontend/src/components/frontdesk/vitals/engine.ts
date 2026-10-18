// The on-device pulse estimate: vitallens (MIT, Rouast Labs) in its local POS method.
//
// Why POS and how the bundle is loaded (checked against vitallens 0.4.5's shipped bundle):
// - Only the "vitallens*" methods build the REST client that posts video to the vendor's API;
//   "pos" never constructs it, so no frame leaves the browser.
// - Its WebAssembly core is inlined as a data: URL, so starting it makes no request.
// - The face-detection model is fetched relative to the bundle's own URL, and the library falls
//   back to a public CDN when that fetch fails. We therefore serve the bundle and the model from
//   this origin (scripts/vendor-vitallens.mjs) and import the bundle natively, bypassing webpack,
//   and we refuse to start unless the model is reachable here.
// - processVideoFile() downloads ffmpeg from a CDN, so it is never called: a recorded clip goes
//   through the same live-stream path as the webcam (see VitalsPanel).

export const VENDOR_BASE = "/vendor/vitallens/";
const BUNDLE = "vitallens.browser.js";
/** The model file vitallens 0.4.5 asks for; a version bump that renames it fails engine.test.ts. */
export const MODEL_JSON = "models/model-1adab985916724ff.json";

/**
 * Lowest heart-rate confidence (the library reports 0 to 1) that the kiosk shows as a number.
 * The library ships no recommended cut-off; this is a spike value to tune on the venue camera.
 */
export const MIN_CONFIDENCE = 0.7;

export interface PulseReading {
  bpm: number;
  confidence: number;
}

export interface PulseEngine {
  /** Starts estimating from a live stream; `onReading` gets each update (null: no heart rate yet). */
  start(
    stream: MediaStream,
    video: HTMLVideoElement,
    onReading: (r: PulseReading | null) => void,
  ): Promise<void>;
  /** Stops processing and frees the library. Safe to call more than once. */
  stop(): Promise<void>;
}

// The slice of the library's API this module uses. Its published types point at a missing
// file in 0.4.5, so the shape is declared here instead.
export interface VitalLensInstance {
  addEventListener(event: "vitals", callback: (data: unknown) => void): void;
  setVideoStream(stream?: MediaStream, video?: HTMLVideoElement): Promise<void>;
  startVideoStream(): void;
  stopVideoStream(): void;
  close(): Promise<void>;
}
interface VitalLensModule {
  VitalLens: new (options: { method: "pos" }) => VitalLensInstance;
}

/** The heart rate in one library result, or null when it has none. */
export function readHeartRate(result: unknown): PulseReading | null {
  const hr = (result as { vitals?: { heart_rate?: { value?: unknown; confidence?: unknown } } } | null)
    ?.vitals?.heart_rate;
  if (typeof hr?.value !== "number" || !Number.isFinite(hr.value)) return null;
  return { bpm: hr.value, confidence: newestConfidence(hr.confidence) };
}

/**
 * The library reports `confidence` either as one number or as one number per sample in the
 * window. Its own widget takes the last element, the newest sample, so the kiosk does the same;
 * anything else counts as no confidence at all.
 */
function newestConfidence(value: unknown): number {
  const newest = Array.isArray(value) ? value[value.length - 1] : value;
  return typeof newest === "number" && Number.isFinite(newest) ? newest : 0;
}

/** Whether a reading is steady enough to show the patient a number. */
export function isSteady(reading: PulseReading | null): reading is PulseReading {
  return reading !== null && reading.confidence >= MIN_CONFIDENCE;
}

async function assertModelServedHere() {
  const res = await fetch(VENDOR_BASE + MODEL_JSON, { method: "HEAD", cache: "no-store" });
  const type = res.headers.get("content-type") ?? "";
  // A missing file would send the library to the CDN; stop here instead.
  if (!res.ok || type.includes("text/html")) {
    throw new Error("The pulse model is not served by this app; run npm run vendor:vitallens.");
  }
}

export async function createPulseEngine(): Promise<PulseEngine> {
  await assertModelServedHere();
  const url = VENDOR_BASE + BUNDLE;
  const { VitalLens } = (await import(/* webpackIgnore: true */ url)) as VitalLensModule;
  return wrapLens(new VitalLens({ method: "pos" }));
}

/** Wraps one library instance so that `stop()` wins over a `start()` still attaching the stream. */
export function wrapLens(lens: VitalLensInstance): PulseEngine {
  let stopped = false;
  return {
    async start(stream, video, onReading) {
      lens.addEventListener("vitals", (data) => {
        if (!stopped) onReading(readHeartRate(data));
      });
      await lens.setVideoStream(stream, video);
      // Stopped (timeout, Stop, unmount) while the stream was attaching: close() has already run,
      // so starting now would leave the library processing a stream nobody releases.
      if (stopped) return;
      lens.startVideoStream();
    },
    async stop() {
      if (stopped) return;
      stopped = true;
      lens.stopVideoStream();
      await lens.close();
    },
  };
}
