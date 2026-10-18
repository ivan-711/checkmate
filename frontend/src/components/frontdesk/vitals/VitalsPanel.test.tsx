// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VITALS_COPY } from "./copy";
import { createPulseEngine, type PulseEngine, type PulseReading } from "./engine";
import VitalsPanel, { MEASURE_SECONDS } from "./VitalsPanel";

vi.mock("./engine", async (original) => ({
  ...(await original<typeof import("./engine")>()),
  createPulseEngine: vi.fn(),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const en = VITALS_COPY.en;

let container: HTMLDivElement;
let root: Root;
let track: { stop: ReturnType<typeof vi.fn> };
let getUserMedia: ReturnType<typeof vi.fn>;
let engine: { start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> };
let fetchSpy: ReturnType<typeof vi.fn>;

/** The engine reports this reading as soon as it starts. */
function engineReports(reading: PulseReading | null) {
  engine.start.mockImplementation(
    async (_stream: MediaStream, _video: HTMLVideoElement, onReading: (r: PulseReading | null) => void) =>
      onReading(reading),
  );
}

const byTestId = (id: string) => container.querySelector(`[data-testid="${id}"]`);
const flush = () => act(async () => {});

async function render(language: "en" | "es" = "en") {
  await act(async () => root.render(<VitalsPanel language={language} />));
}

async function click(id: string) {
  await act(async () => (byTestId(id) as HTMLButtonElement).click());
  await flush();
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
  track = { stop: vi.fn() };
  const stream = { getTracks: () => [track] } as unknown as MediaStream;
  getUserMedia = vi.fn().mockResolvedValue(stream);
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia }, configurable: true });
  engine = { start: vi.fn(), stop: vi.fn().mockResolvedValue(undefined) };
  vi.mocked(createPulseEngine).mockResolvedValue(engine as unknown as PulseEngine);
  fetchSpy = vi.fn();
  vi.stubGlobal("fetch", fetchSpy);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("VitalsPanel", () => {
  it("asks first and always shows the footer", async () => {
    await render();
    expect(container.textContent).toContain(en.consent);
    expect(byTestId("vitals-footer")?.textContent).toBe(en.footer);
    expect(getUserMedia).not.toHaveBeenCalled();
    expect(createPulseEngine).not.toHaveBeenCalled();
  });

  it("never opens the camera or loads the library when the patient declines", async () => {
    await render();
    await click("vitals-decline");
    expect(byTestId("vitals-status")?.textContent).toBe(en.declined);
    expect(byTestId("vitals-footer")?.textContent).toBe(en.footer);
    expect(getUserMedia).not.toHaveBeenCalled();
    expect(createPulseEngine).not.toHaveBeenCalled();
  });

  it("shows the bpm after the countdown when the reading is steady, then turns the camera off", async () => {
    engineReports({ bpm: 71.6, confidence: 0.92 });
    await render();
    await click("vitals-accept");
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(byTestId("vitals-countdown")?.textContent).toBe(en.remaining(MEASURE_SECONDS));
    expect(byTestId("vitals-result")).toBeNull();

    await act(async () => vi.advanceTimersByTimeAsync(MEASURE_SECONDS * 1000));
    expect(byTestId("vitals-result")?.textContent).toBe(en.result(72));
    expect(track.stop).toHaveBeenCalled();
    expect(engine.stop).toHaveBeenCalled();
    expect(byTestId("vitals-footer")?.textContent).toBe(en.footer);
    expect(fetchSpy).not.toHaveBeenCalled(); // the number goes nowhere
  });

  it("says it couldn't get a steady reading when confidence is low", async () => {
    engineReports({ bpm: 64, confidence: 0.3 });
    await render();
    await click("vitals-accept");
    await act(async () => vi.advanceTimersByTimeAsync(MEASURE_SECONDS * 1000));
    expect(byTestId("vitals-result")).toBeNull();
    expect(byTestId("vitals-status")?.textContent).toBe(en.unsteady);
    expect(container.textContent).not.toContain("64");
    expect(track.stop).toHaveBeenCalled();
  });

  it("treats no heart rate at all as an unsteady reading", async () => {
    engineReports(null);
    await render();
    await click("vitals-accept");
    await act(async () => vi.advanceTimersByTimeAsync(MEASURE_SECONDS * 1000));
    expect(byTestId("vitals-status")?.textContent).toBe(en.unsteady);
  });

  it("stops the camera tracks and the library when unmounted mid-reading", async () => {
    engineReports({ bpm: 70, confidence: 0.9 });
    await render();
    await click("vitals-accept");
    expect(byTestId("vitals-countdown")).not.toBeNull();
    expect(track.stop).not.toHaveBeenCalled();
    await act(async () => root.unmount());
    expect(track.stop).toHaveBeenCalled();
    expect(engine.stop).toHaveBeenCalled();
    root = createRoot(container); // afterEach unmounts again
  });

  it("stops the camera when the patient presses Stop", async () => {
    engineReports({ bpm: 70, confidence: 0.9 });
    await render();
    await click("vitals-accept");
    const stop = [...container.querySelectorAll("button")].find((b) => b.textContent === en.stop)!;
    await act(async () => stop.click());
    expect(track.stop).toHaveBeenCalled();
    expect(byTestId("vitals-status")?.textContent).toBe(en.declined);
  });

  it("says the camera isn't available when access is refused, and loads nothing", async () => {
    getUserMedia.mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    await render();
    await click("vitals-accept");
    expect(byTestId("vitals-status")?.textContent).toBe(en.unavailable);
    expect(createPulseEngine).not.toHaveBeenCalled();
  });

  it("releases the camera when the library cannot start", async () => {
    vi.mocked(createPulseEngine).mockRejectedValue(new Error("model not served"));
    await render();
    await click("vitals-accept");
    expect(byTestId("vitals-status")?.textContent).toBe(en.unavailable);
    expect(track.stop).toHaveBeenCalled();
  });

  it("speaks Spanish when the kiosk does", async () => {
    await render("es");
    expect(container.textContent).toContain(VITALS_COPY.es.consent);
    expect(byTestId("vitals-footer")?.textContent).toBe(VITALS_COPY.es.footer);
  });

  it("offers a recorded clip instead of the webcam with ?vitalsSource=file", async () => {
    window.history.replaceState(null, "", "/frontdesk?vitalsSource=file");
    try {
      await render();
      await click("vitals-accept");
      expect(byTestId("vitals-file")).not.toBeNull();
      expect(getUserMedia).not.toHaveBeenCalled();
    } finally {
      window.history.replaceState(null, "", "/");
    }
  });
});
