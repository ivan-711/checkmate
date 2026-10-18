"use client";

import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import type { IntakeSession, IntakeTurn } from "@/api/types";
import { useAnnounce } from "@/components/ui/LiveRegion";
import { RESOLVE_KEY, SESSION_CHANGE_KEY, useDemoReset } from "@/components/ui/demoReset";
import { useDataSource } from "@/data/DataSourceProvider";
import { scenario } from "@/data/scenario";
import { DataError } from "@/data/source";
import type { KioskState as DeskKioskState } from "@/lib/desk";
import { COPY, type KioskCopy, type KioskLanguage } from "./copy";
import { needsNewCheckIn } from "./checkIn";
import { GateCard } from "./GateCard";
import { HANDOFF_KEY, INTAKE_KEY, refreshHandoffOnMutation, SEND_TURN_KEY, useHandoffPairs } from "./intake";
import { KioskMark, Tick } from "./KioskMark";
import { gateDenial, kioskState, patientGivenName, type KioskState } from "./kioskState";
import { turnSteps } from "./turnSteps";
import { WorkChecklist } from "./WorkChecklist";
import "./kiosk.css";

const MAX_CHARS = 280; // UX 3.11 composer limit; the contract allows 500
const COUNTER_FROM = 240;
/** The language switch crossfades with no layout jump (CONCEPT.md §5, touch 12). */
const CROSSFADE_MS = 160;
/** Room kept between a revealed line and the edge of the kiosk's scroll area. */
const REVEAL_PAD_PX = 16;

const LANGUAGES: { value: KioskLanguage; label: string }[] = [
  { value: "en", label: "English" },
  { value: "es", label: "Español" },
];

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Start over is the full demo reset in every mode: fixture state includes the Desk's decision, so
 * clearing only the intake cache can leave the next check-in past the gate. It waits for what the
 * header's Reset demo waits for (useResetDemo), because a reset that overlaps a match run gets a 503
 * and leaves no candidate pair, and for a turn still being read. */
export function startOverBlocked(work: {
  sending: boolean;
  resetting: boolean;
  resolving: boolean;
}): boolean {
  return work.sending || work.resetting || work.resolving;
}

/** Runs the reset unless Start over is blocked; true when it ran. */
export function runStartOver(blocked: boolean, resetDemo: () => void): boolean {
  if (blocked) return false;
  resetDemo();
  return true;
}

/** Scrolls the kiosk's own scroll area so `el` is fully in view: the whole element when it fits,
 * its top otherwise. Only the kiosk region moves, never the window (BUILD-SPEC decision 6). */
function reveal(scroller: HTMLElement, el: HTMLElement) {
  const s = scroller.getBoundingClientRect();
  const e = el.getBoundingClientRect();
  const top = e.top - s.top + scroller.scrollTop;
  const view = scroller.clientHeight;
  let target = scroller.scrollTop;
  if (e.height + 2 * REVEAL_PAD_PX > view || top - REVEAL_PAD_PX < scroller.scrollTop) {
    target = top - REVEAL_PAD_PX;
  } else if (top + e.height + REVEAL_PAD_PX > scroller.scrollTop + view) {
    target = top + e.height + REVEAL_PAD_PX - view;
  }
  if (target !== scroller.scrollTop) {
    scroller.scrollTo({ top: Math.max(0, target), behavior: reducedMotion() ? "auto" : "smooth" });
  }
}

/** The patient's own line. Once the agent is done it settles to two lines; click to expand. */
function PatientLine({ text, settled, t }: { text: string; settled: boolean; t: KioskCopy }) {
  const [open, setOpen] = useState(false);
  if (!settled) {
    return (
      <li className="k-you-row">
        <p className="k-who">{t.you}</p>
        <p className="k-you">{text}</p>
      </li>
    );
  }
  return (
    <li className="k-you-row">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className={`k-you k-you-settled ${open ? "open" : ""}`}
      >
        {text}
      </button>
    </li>
  );
}

/** Words the model wrote are labelled as the AI agent's and set in the gray agent tone; text the
 * system wrote (templates, the registrar's outcome) is a fact and stays near-black. */
function AgentLine({
  text,
  automatic,
  t,
  children,
}: {
  text: string;
  automatic: boolean;
  t: KioskCopy;
  children?: React.ReactNode;
}) {
  return (
    <li className="k-agent">
      <p className="k-who">
        {t.speaker} · {automatic ? t.automatic : t.aiAgent}
      </p>
      <p
        data-voice={automatic ? "system" : "agent"}
        className={automatic ? "k-agent-system" : "k-agent-model"}
      >
        {text}
      </p>
      {children}
    </li>
  );
}

function Turn({
  turn,
  t,
  settled,
  reviewing,
  gateRef,
}: {
  turn: IntakeTurn;
  t: KioskCopy;
  settled: boolean;
  reviewing: boolean;
  gateRef: (el: HTMLDivElement | null) => void;
}) {
  const steps = turnSteps(turn, t);
  const denied = (turn.toolCalls ?? [])
    .map((call) => ({ call, candidate: gateDenial(call) }))
    .find((d) => d.candidate);
  return (
    <>
      <PatientLine text={turn.userText} settled={settled} t={t} />
      {steps && (
        <li className="k-work-row">
          <WorkChecklist steps={steps} t={t} />
          {denied && (
            <GateCard
              ref={gateRef}
              call={denied.call}
              candidate={denied.candidate!}
              t={t}
              reviewing={reviewing}
              steps={steps.done.length + 1}
            />
          )}
        </li>
      )}
      {/* A hand-off closes the turn with the gate card's held line (UX 3.11). The agent's reply
          would say the same thing again, and the model never speaks for the gate. */}
      {!denied && (
        <AgentLine text={turn.assistantText} automatic={turn.assistantTextSource === "TEMPLATE"} t={t} />
      )}
    </>
  );
}

/** A scripted check-in the presenter can drop into the composer: the replay knows its exact text. */
function DemoLine({
  label,
  line,
  language,
  use,
  disabled,
  onUse,
  alt = false,
}: {
  alt?: boolean;
  label: string;
  line: string;
  language: KioskLanguage;
  use: string;
  disabled: boolean;
  onUse: (line: string) => void;
}) {
  // Both buttons read "Use this"; the box's label tells a screen reader which line each one uses.
  const labelId = useId();
  return (
    <div className={alt ? "k-demo k-demo-alt" : "k-demo"}>
      <p id={labelId} className="k-demo-lbl">
        {label}
      </p>
      <q lang={language} className="k-demo-q">
        {line}
      </q>
      <button
        type="button"
        aria-describedby={labelId}
        disabled={disabled}
        onClick={() => onUse(line)}
        className="k-use"
      >
        {use}
      </button>
    </div>
  );
}

/** The patient's kiosk (CONCEPT.md §3): welcome and the demo line, then the working glow and the
 * checklist, the gate card, and "You're checked in" once a registrar has linked the chart.
 * `onStateChange` tells the Desk which still the kiosk is on; `registrarReviewing` is true while
 * the registrar has the held pair open, so the card can say so. */
export function KioskPane({
  onStateChange,
  registrarReviewing = false,
}: {
  onStateChange?: (state: DeskKioskState) => void;
  registrarReviewing?: boolean;
} = {}) {
  const source = useDataSource();
  const queryClient = useQueryClient();
  const [language, setLanguage] = useState<KioskLanguage>("en");
  const [fading, setFading] = useState(false);
  const [text, setText] = useState("");
  // Tied to the check-in it failed on, so a Reset or Start over never shows an old failure.
  const [failed, setFailed] = useState<{ text: string; sessionId: string } | null>(null);
  const key = useRef<{ text: string; key: string } | null>(null);
  const announce = useAnnounce();
  const t = COPY[language];
  const suggestion = source.suggestedCheckIn[language];
  const newPatient = source.suggestedCheckIn.newPatient?.[language];

  // The server picks the agent mode; the check-in's language picks the recording replay plays.
  const checkInLanguage = language === "es" ? "ES" : "EN";
  const startIntake = () => source.startIntake(checkInLanguage, scenario.frontdeskIntake.scenarioContextId);
  // A reset on the corpus takes seconds and wipes every check-in when it lands: nothing is sent
  // meanwhile, and the shared reset starts the new check-in once it has finished.
  const resetting = useIsMutating({ mutationKey: SESSION_CHANGE_KEY }) > 0;
  const sending = useIsMutating({ mutationKey: SEND_TURN_KEY }) > 0;
  const resolving = useIsMutating({ mutationKey: RESOLVE_KEY }) > 0;
  const startOverDisabled = startOverBlocked({ sending, resetting, resolving });
  const demoReset = useDemoReset();
  const session = useQuery({
    queryKey: INTAKE_KEY,
    queryFn: startIntake,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const turns = session.data?.turns ?? [];
  // The registrar's decisions, read from the server: the kiosk tells the patient what happens
  // next. One linked chart confirms the check-in; a new chart only when every pair was rejected.
  useEffect(() => refreshHandoffOnMutation(queryClient), [queryClient]);
  const statuses = useHandoffPairs().map((pair) => pair.data?.pair.decision.status);
  const decided = statuses.includes("LINKED")
    ? "LINKED"
    : statuses.length > 0 && statuses.every((status) => status === "REJECTED")
      ? "REJECTED"
      : null;

  const send = useMutation({
    mutationKey: SEND_TURN_KEY,
    mutationFn: async (message: { text: string; key: string }) => {
      try {
        return await source.sendTurn(session.data!.id, message.text, message.key);
      } catch (error) {
        // A Reset elsewhere removed this check-in. That is not an outage: start a new check-in
        // and send the message there.
        if (!(error instanceof DataError && error.code === "NOT_FOUND")) throw error;
        const fresh = await startIntake();
        queryClient.setQueryData(INTAKE_KEY, fresh);
        void queryClient.resetQueries({ queryKey: HANDOFF_KEY });
        return source.sendTurn(fresh.id, message.text, message.key);
      }
    },
    onSuccess: (turn) => {
      key.current = null;
      setFailed(null);
      void queryClient.invalidateQueries({ queryKey: ["tiles"] }); // the gate just counted this turn
      queryClient.setQueryData<IntakeSession>(INTAKE_KEY, (s) =>
        s ? { ...s, turns: [...(s.turns ?? []), turn], registration: turn.registration } : s,
      );
      const candidate = (turn.toolCalls ?? []).map(gateDenial).find(Boolean);
      if (candidate) announce(t.gateAnnounce(candidate.p.toFixed(2), t.band[candidate.band]));
    },
    onError: (_error, message) => {
      setFailed({ text: message.text, sessionId: session.data?.id ?? "" });
      setText((typed) => typed || message.text); // back into the composer, unless more was typed
    },
  });

  const scroller = useRef<HTMLDivElement>(null);
  const gateCard = useRef<HTMLDivElement | null>(null);
  const thread = useRef<HTMLOListElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const crossfade = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(crossfade.current), []);

  // The toggle changed before the first turn: start over in the new language, so the demo
  // script line goes into a check-in in its own language.
  const restart = !resetting && !sending && needsNewCheckIn(session.data, checkInLanguage);
  useEffect(() => {
    if (restart) void queryClient.resetQueries({ queryKey: INTAKE_KEY });
  }, [restart, queryClient]);

  // UX 3.10: after a reset the presenter types straight into the kiosk.
  const wasResetting = useRef(false);
  useEffect(() => {
    if (wasResetting.current && !resetting) composer.current?.focus();
    wasResetting.current = resetting;
  }, [resetting]);

  const pending = send.isPending ? send.variables?.text : null;
  const failedText = failed && failed.sessionId === session.data?.id ? failed.text : null;
  const state: KioskState = kioskState({
    session: session.data,
    pending: send.isPending,
    failed: !!failedText,
    decided,
  });
  const name = patientGivenName(session.data);
  const gateCount = turns.filter((turn) => (turn.toolCalls ?? []).some((c) => gateDenial(c))).length;

  // The Desk follows four of the kiosk's stills; a reply or a rejection reads as idle there.
  const deskState: DeskKioskState =
    state === "working" || state === "held" || state === "done" ? state : "idle";
  useEffect(() => {
    onStateChange?.(deskState);
  }, [deskState, onStateChange]);

  // New lines come into view inside the kiosk's own scroll area, never by scrolling the window.
  // A new gate card comes first, the whole card (it is the moment the demo is about); otherwise
  // the newest line when a turn, a "reading" row or a failure is added.
  const shown = useRef({ turns: 0, gates: 0, pending: false, failed: false });
  useEffect(() => {
    const was = shown.current;
    const now = { turns: turns.length, gates: gateCount, pending: !!pending, failed: !!failedText };
    shown.current = now;
    const box = scroller.current;
    if (!box) return;
    if (now.gates > was.gates && gateCard.current) {
      reveal(box, gateCard.current);
      return;
    }
    const added = now.turns > was.turns || (now.pending && !was.pending) || (now.failed && !was.failed);
    const last = thread.current?.lastElementChild;
    if (added && last instanceof HTMLElement) reveal(box, last);
  }, [turns.length, gateCount, pending, failedText]);

  function switchLanguage(next: KioskLanguage) {
    if (next === language) return;
    announce(COPY[next].switched);
    clearTimeout(crossfade.current);
    if (reducedMotion()) {
      setLanguage(next);
      return;
    }
    setFading(true);
    crossfade.current = setTimeout(() => {
      setLanguage(next);
      setFading(false);
    }, CROSSFADE_MS);
  }

  function submit() {
    const message = text.trim();
    if (!message || sending || resetting || !session.data) return;
    // One key per typed message, reused when the same message is retried.
    if (key.current?.text !== message) key.current = { text: message, key: crypto.randomUUID() };
    setText("");
    composer.current?.focus(); // Send is disabled once the text clears; keep focus in the composer
    send.mutate(key.current);
  }

  function startOver() {
    // Checked here as well as on the button, so a click queued before the button re-renders cannot
    // start a reset that overlaps the work.
    runStartOver(startOverDisabled, () => {
      setFailed(null);
      setText("");
      key.current = null;
      send.reset();
      demoReset.mutate(undefined, { onSettled: () => composer.current?.focus() });
    });
  }

  const idle = state === "idle";
  const finished = state === "done" || state === "rejected";
  // The demo line sends the one recorded turn: not while a turn runs, not after the first turn.
  const demoLineDisabled = resetting || sending || turns.length > 0;
  const useLine = (line: string) => {
    setText(line);
    composer.current?.focus();
  };
  const sendDisabled = !text.trim() || sending || resetting || !session.data;

  return (
    <div data-testid="kiosk" data-k={state} lang={language} className="kiosk">
      <div className="k-head">
        <KioskMark />
        <b>FrontDesk</b>
        {session.data?.agentMode && (
          <span data-testid="agent-mode-badge" className="k-mode">
            {session.data.agentMode}
          </span>
        )}
        <div role="group" aria-label={t.language} className="k-lang">
          {LANGUAGES.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              lang={value}
              aria-pressed={language === value}
              onClick={() => switchLanguage(value)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div ref={scroller} className={`k-swap ${fading ? "fading" : ""}`}>
        {session.isError ? (
          <div data-testid="kiosk-start-error" className="k-start-error">
            <p>{t.startFailed}</p>
            <button type="button" onClick={() => void session.refetch()} className="k-link">
              {t.tryAgain}
            </button>
          </div>
        ) : idle ? (
          <div className="k-welcome">
            <h2 className="k-title">{t.title}</h2>
            <p className="k-sub">{t.sub}</p>
            <DemoLine
              label={t.demoLabel}
              line={suggestion}
              language={language}
              use={t.suggestUse}
              disabled={demoLineDisabled}
              onUse={useLine}
            />
            {newPatient && (
              <DemoLine
                alt
                label={t.newPatientLabel}
                line={newPatient}
                language={language}
                use={t.suggestUse}
                disabled={demoLineDisabled}
                onUse={useLine}
              />
            )}
          </div>
        ) : finished ? (
          <div className="k-done">
            <KioskMark className="k-bigmark" />
            <h2 className="k-title">{state === "done" ? t.doneTitle(name) : t.rejectedTitle(name)}</h2>
            <p className="k-sub">{state === "done" ? t.doneSub : t.rejected}</p>
            {state === "done" && (
              <ol className="k-steps k-steps-done">
                {t.doneSteps.map((step, i) => (
                  <li key={step} className="k-step on" style={{ "--i": i } as React.CSSProperties}>
                    <Tick />
                    <span className="k-step-body">{step}</span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        ) : (
          <section aria-label={t.region} className="k-thread-region">
            <ol ref={thread} aria-live="off" className="k-thread">
              {turns.map((turn) => (
                <Turn
                  key={turn.turnIndex}
                  turn={turn}
                  t={t}
                  settled={state !== "working"}
                  reviewing={registrarReviewing}
                  gateRef={(el) => (gateCard.current = el)}
                />
              ))}
              {pending && (
                <>
                  <PatientLine text={pending} settled={false} t={t} />
                  <li aria-busy="true" className="k-work-row">
                    <WorkChecklist steps={null} t={t} />
                  </li>
                </>
              )}
              {failedText && !send.isPending && (
                <AgentLine text={t.agentDown} automatic t={t}>
                  <button type="button" onClick={submit} className="k-link">
                    {t.tryAgain}
                  </button>
                </AgentLine>
              )}
            </ol>
          </section>
        )}
      </div>

      {!finished && (
        <form
          className="k-composer"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <textarea
            ref={composer}
            data-testid="kiosk-composer"
            aria-label={idle ? t.placeholder : t.reply}
            placeholder={idle ? t.placeholder : t.reply}
            value={text}
            maxLength={MAX_CHARS}
            rows={idle ? 3 : 1}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <div className="k-crow">
            {idle && (
              <p data-testid="kiosk-promise" className="k-promise">
                {t.promise[0]} <br />
                {t.promise[1]}
              </p>
            )}
            {text.length >= COUNTER_FROM && <span className="k-counter num">{t.counter(text.length)}</span>}
            <button type="submit" data-testid="kiosk-send" disabled={sendDisabled} className="k-send">
              {t.send}
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden>
                <path
                  d="M9 6l6 6-6 6"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
          </div>
        </form>
      )}

      <div className="k-foot">
        {!idle && state !== "working" && (
          <button
            type="button"
            disabled={startOverDisabled}
            onClick={startOver}
            className={finished ? "k-restart" : "k-link"}
          >
            {t.startOver}
          </button>
        )}
        {state === "working" ? <p>{t.wait}</p> : idle || finished ? <p>{t.foot}</p> : null}
      </div>
    </div>
  );
}
