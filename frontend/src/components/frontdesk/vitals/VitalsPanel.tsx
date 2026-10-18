"use client";

// Optional pulse estimate while the kiosk looks up the patient's record. Everything happens in
// this component: the reading is never sent to the API, stored or shown to staff, and the camera
// is released when the 20 seconds end, on timeout, on Stop and on unmount.
import { useEffect, useRef, useState } from "react";
import { useAnnounce } from "@/components/ui/LiveRegion";
import type { KioskLanguage } from "../copy";
import { VITALS_COPY } from "./copy";
import { createPulseEngine, isSteady, type PulseEngine, type PulseReading } from "./engine";

/** Length of one reading; the POS window needs a few seconds before its first estimate. */
export const MEASURE_SECONDS = 20;
/** Bounds camera ownership across both library start-up and measurement. */
export const VITALS_TIMEOUT_MS = 45_000;
const TICK_MS = 1000;
const CAMERA: MediaStreamConstraints = {
  video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
  audio: false,
};

type Phase =
  | "consent"
  | "declined"
  | "pick-file"
  | "starting"
  | "measuring"
  | "result"
  | "stopped"
  | "timed-out"
  | "unsteady"
  | "unavailable";

/** One camera or clip run: what has to be released when it ends. */
interface Run {
  stream: MediaStream | null;
  engine: PulseEngine | null;
  timer: ReturnType<typeof setInterval> | null;
  watchdog: ReturnType<typeof setTimeout> | null;
  clipUrl: string | null;
  reading: PulseReading | null;
}

/** A local clip is a development-only camera substitute and cannot ship in production builds. */
function fromFileRequested() {
  return (
    process.env.NODE_ENV !== "production" &&
    new URLSearchParams(window.location.search).get("vitalsSource") === "file"
  );
}

export default function VitalsPanel({ language }: { language: KioskLanguage }) {
  const t = VITALS_COPY[language];
  const [phase, setPhase] = useState<Phase>("consent");
  const [remaining, setRemaining] = useState(MEASURE_SECONDS);
  const [bpm, setBpm] = useState<number | null>(null);
  const [fromFile] = useState(fromFileRequested);
  const preview = useRef<HTMLVideoElement>(null);
  const clip = useRef<HTMLVideoElement>(null);
  const run = useRef<Run | null>(null);
  const announce = useAnnounce();

  function release(r: Run) {
    if (run.current === r) run.current = null;
    if (r.timer) clearInterval(r.timer);
    r.timer = null;
    if (r.watchdog) clearTimeout(r.watchdog);
    r.watchdog = null;
    void r.engine?.stop().catch(() => undefined);
    r.engine = null;
    r.stream?.getTracks().forEach((track) => track.stop());
    r.stream = null;
    if (preview.current) preview.current.srcObject = null;
    if (r.clipUrl) {
      clip.current?.pause();
      clip.current?.removeAttribute("src");
      URL.revokeObjectURL(r.clipUrl);
      r.clipUrl = null;
    }
  }

  // Unmount (leaving the page, Reset) always turns the camera off.
  useEffect(
    () => () => {
      if (run.current) release(run.current);
    },
    [],
  );

  function finish(r: Run) {
    const reading = r.reading;
    release(r);
    if (isSteady(reading)) {
      setBpm(Math.round(reading.bpm));
      setPhase("result");
    } else {
      setPhase("unsteady");
    }
  }

  async function measure(openStream: (r: Run) => Promise<MediaStream>) {
    const r: Run = {
      stream: null,
      engine: null,
      timer: null,
      watchdog: null,
      clipUrl: null,
      reading: null,
    };
    run.current = r;
    r.watchdog = setTimeout(() => {
      if (run.current !== r) return;
      release(r);
      setPhase("timed-out");
    }, VITALS_TIMEOUT_MS);
    setPhase("starting");
    try {
      r.stream = await openStream(r);
      if (run.current !== r) return release(r); // stopped or unmounted while the camera opened
      const video = preview.current!;
      video.srcObject = r.stream;
      r.engine = await createPulseEngine();
      if (run.current !== r) return release(r);
      await r.engine.start(r.stream, video, (reading) => {
        r.reading = reading;
      });
      if (run.current !== r) return release(r);
      const endsAt = Date.now() + MEASURE_SECONDS * 1000;
      setRemaining(MEASURE_SECONDS);
      setPhase("measuring");
      r.timer = setInterval(() => {
        const left = Math.ceil((endsAt - Date.now()) / 1000);
        if (left <= 0) finish(r);
        else setRemaining(left);
      }, TICK_MS);
    } catch (error) {
      console.warn("vitals: on-device pulse estimate unavailable", error);
      const current = run.current === r;
      release(r);
      if (current) setPhase("unavailable");
    }
  }

  const openCamera = () => navigator.mediaDevices.getUserMedia(CAMERA);

  async function openClip(file: File, r: Run) {
    const video = clip.current!;
    r.clipUrl = URL.createObjectURL(file);
    video.src = r.clipUrl;
    await video.play();
    return (video as HTMLVideoElement & { captureStream(): MediaStream }).captureStream();
  }

  function stop() {
    if (run.current) release(run.current);
    setPhase("stopped");
  }

  const live = phase === "starting" || phase === "measuring";
  const status =
    phase === "declined"
      ? t.declined
      : phase === "stopped"
        ? t.stopped
        : phase === "timed-out"
          ? t.timedOut
          : phase === "starting"
            ? t.starting
            : phase === "unsteady"
              ? t.unsteady
              : phase === "unavailable"
                ? t.unavailable
                : null;
  // Spoken through the page's one polite live region, as every other kiosk message is.
  const spoken = phase === "measuring" ? t.hold : phase === "result" && bpm !== null ? t.result(bpm) : status;
  useEffect(() => {
    if (spoken) announce(spoken);
  }, [spoken, announce]);

  return (
    <section
      data-testid="vitals-panel"
      aria-labelledby="vitals-heading"
      className="flex flex-col gap-3 rounded-lg border border-border-subtle bg-surface p-4"
    >
      <h3 id="vitals-heading" className="text-[16px] font-semibold uppercase tracking-wider text-ink-3">
        {t.heading}
      </h3>
      <p data-testid="vitals-label" className="text-[16px] font-semibold text-ink-2">
        {t.label}
      </p>

      {phase === "consent" && (
        <>
          <p className="max-w-[68ch]">{t.consent}</p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              data-testid="vitals-accept"
              onClick={() => (fromFile ? setPhase("pick-file") : void measure(openCamera))}
              className="h-11 rounded-md border border-border-strong bg-surface px-4 font-semibold text-ink-1 hover:bg-sunken"
            >
              {t.accept}
            </button>
            <button
              type="button"
              data-testid="vitals-decline"
              onClick={() => setPhase("declined")}
              className="h-11 px-2 font-semibold text-accent underline underline-offset-2"
            >
              {t.decline}
            </button>
          </div>
        </>
      )}

      {phase === "pick-file" && (
        <label className="flex flex-col gap-1 text-[16px]">
          <span>{t.pickFile}</span>
          <input
            type="file"
            accept="video/*"
            data-testid="vitals-file"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void measure((r) => openClip(file, r));
            }}
          />
        </label>
      )}

      {/* Always mounted so a stream can be attached before the measuring state renders. */}
      <div hidden={!live} className="flex flex-wrap items-center gap-4">
        <video
          ref={preview}
          aria-label={t.preview}
          autoPlay
          muted
          playsInline
          className={`h-30 w-40 rounded-md bg-sunken object-cover ${fromFile ? "" : "-scale-x-100"}`}
        />
        <div className="flex flex-col gap-1">
          {phase === "measuring" && (
            <>
              <p className="font-semibold">{t.hold}</p>
              <p data-testid="vitals-countdown" className="text-[16px] text-ink-3 tabular-nums">
                {t.remaining(remaining)}
              </p>
            </>
          )}
          {/* Stop exists only while there is a run to stop; after a timeout or a result there is
              nothing left for it to do. */}
          {live && (
            <button
              type="button"
              data-testid="vitals-stop"
              onClick={stop}
              className="self-start text-[16px] font-semibold text-accent underline underline-offset-2"
            >
              {t.stop}
            </button>
          )}
        </div>
      </div>
      {fromFile && <video ref={clip} hidden muted playsInline loop />}

      {status && (
        <p data-testid="vitals-status" className="text-[16px]">
          {status}
        </p>
      )}
      {phase === "result" && bpm !== null && (
        <p data-testid="vitals-result" className="text-[32px] leading-[36px] font-semibold tabular-nums">
          {t.result(bpm)}
        </p>
      )}

      <p data-testid="vitals-footer" className="text-[16px] font-medium text-ink-3">
        {t.footer}
      </p>
    </section>
  );
}
