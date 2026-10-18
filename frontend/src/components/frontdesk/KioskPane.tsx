"use client";

import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ShieldAlert, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { IntakeSession, IntakeTurn, ToolCallRecord } from "@/api/types";
import { ConstructedChip } from "@/components/ui/ConstructedChip";
import { SESSION_CHANGE_KEY, useDemoReset } from "@/components/ui/ResetButton";
import { RuleResultTag } from "@/components/ui/RuleResultTag";
import { useAnnounce } from "@/components/ui/LiveRegion";
import { useDataSource } from "@/data/DataSourceProvider";
import { scenario } from "@/data/scenario";
import { DataError } from "@/data/source";
import { COPY, type KioskCopy, type KioskLanguage } from "./copy";
import { needsNewCheckIn } from "./checkIn";
import { GateCard } from "./GateCard";
import { HANDOFF_KEY, INTAKE_KEY, SEND_TURN_KEY, useHandoffPairs } from "./intake";
import { ToolCallChip } from "./ToolCallChip";
import { turnSteps } from "./turnSteps";

const MAX_CHARS = 280; // UX 3.11 composer limit; the contract allows 500
const COUNTER_FROM = 240;

const LANGUAGES: { value: KioskLanguage; label: string }[] = [
  { value: "en", label: "English" },
  { value: "es", label: "Español" },
];

/** The pane the kiosk scrolls in when the panes sit side by side (globals.css, .pane); null when
 * they stack and the page scrolls. */
function scrollPane(el: Element): HTMLElement | null {
  for (let box = el.parentElement; box; box = box.parentElement) {
    if (/auto|scroll/.test(getComputedStyle(box).overflowY)) return box;
  }
  return null;
}

/** How a new gate card's row (the tool chip, then the card) scrolls into view: the whole row when
 * it fits; else its foot, which shows the whole card; else its top, so the card's top shows. */
function gateRowBlock(row: HTMLElement, card: HTMLElement): ScrollLogicalPosition {
  const margin = parseFloat(getComputedStyle(row).scrollMarginTop) || 0;
  const room = (scrollPane(row)?.clientHeight ?? window.innerHeight) - 2 * margin;
  if (row.offsetHeight <= room) return "nearest";
  return card.offsetHeight <= room ? "end" : "start";
}

/** The denied new chart that a registrar now holds: the card the demo is about. */
function gateDenial(call: ToolCallRecord) {
  const candidate = call.candidates?.[0];
  const held = call.gate.outcome === "DENY" && call.gate.reasonCode === "CANDIDATE_IN_REVIEW_OR_HIGHER";
  return held && candidate ? candidate : null;
}

/** Words the model wrote are set in the gray agent tone; text the system wrote (templates, the
 * gate's hand-off, the registrar's outcome) is a fact and stays near-black. */
function Agent({ text, automatic, t }: { text: string; automatic: boolean; t: KioskCopy }) {
  return (
    <li className="max-w-[80%] text-[20px]">
      <p className="text-[18px] font-semibold text-ink-2">
        {t.speaker}
        {automatic && <span className="ml-2 font-normal text-ink-3">{t.automatic}</span>}
      </p>
      <p data-voice={automatic ? "system" : "agent"} className={automatic ? "text-ink-1" : "text-ink-2"}>
        {text}
      </p>
    </li>
  );
}

/** The turn as a past-tense checklist whose last line is the gate's fact (HELD or PASSED). */
function Steps({ turn, t }: { turn: IntakeTurn; t: KioskCopy }) {
  const steps = turnSteps(turn, t);
  if (!steps) return null;
  const { fact } = steps;
  return (
    <li data-testid="turn-steps">
      <ol aria-label={t.stepsLabel} className="space-y-1 text-[18px]">
        {/* The same tool can run twice in a turn, so rows are keyed by position. */}
        {steps.done.map((step, i) => (
          <li key={i} className="flex items-center gap-2 text-ink-2">
            <Check aria-hidden size={18} className="shrink-0" />
            {step}
          </li>
        ))}
        <li
          data-testid="gate-fact"
          data-voice="verified"
          data-outcome={fact.outcome}
          data-reason={fact.reasonCode ?? undefined}
          className={`flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-l-4 bg-surface px-3 py-2 text-ink-1 ${
            fact.outcome === "HELD" ? "border-denied-border border-l-gate-bar" : "border-allowed-border"
          }`}
        >
          {fact.outcome === "HELD" ? (
            <ShieldAlert aria-hidden size={18} className="shrink-0 text-denied-ink" />
          ) : (
            <ShieldCheck aria-hidden size={18} className="shrink-0 text-allowed-ink" />
          )}
          <span>{t.gateName}:</span>
          <span className="font-semibold">{fact.label}</span>
          {fact.reason && <span>{fact.reason}</span>}
          <span className="font-mono text-[16px] text-ink-2">{fact.policy}</span>
          <span className="ml-auto">
            <RuleResultTag label={t.ruleResult} />
          </span>
        </li>
      </ol>
    </li>
  );
}

function Turn({
  turn,
  t,
  gateRef,
}: {
  turn: IntakeTurn;
  t: KioskCopy;
  gateRef: (el: HTMLDivElement | null) => void;
}) {
  const calls = turn.toolCalls ?? [];
  const handedOff = calls.some((c) => gateDenial(c));
  return (
    <>
      <li className="ml-auto max-w-[80%] rounded-lg border border-border-subtle bg-surface px-4 py-3 text-[20px]">
        {turn.userText}
      </li>
      <Steps turn={turn} t={t} />
      {calls.map((call) => {
        const candidate = gateDenial(call);
        return (
          // scroll-my-4: a gate card scrolled into view keeps 16 px from the pane's edge.
          <li key={call.id} className="scroll-my-4 space-y-2">
            <ToolCallChip call={call} t={t} hasGateCard={!!candidate} />
            {candidate && <GateCard ref={gateRef} call={call} candidate={candidate} t={t} />}
          </li>
        );
      })}
      {/* A hand-off closes the turn with the gate's automatic line (UX 3.11). The agent's reply
          would say the same thing again, and the model never speaks for the gate. */}
      {handedOff ? (
        <Agent text={t.handoff} automatic t={t} />
      ) : (
        <Agent text={turn.assistantText} automatic={turn.assistantTextSource === "TEMPLATE"} t={t} />
      )}
    </>
  );
}

export function KioskPane() {
  const source = useDataSource();
  const queryClient = useQueryClient();
  const [language, setLanguage] = useState<KioskLanguage>("en");
  const [text, setText] = useState("");
  // Tied to the check-in it failed on, so a Reset or Start over never shows an old failure.
  const [failed, setFailed] = useState<{ text: string; sessionId: string } | null>(null);
  const key = useRef<{ text: string; key: string } | null>(null);
  const announce = useAnnounce();
  const t = COPY[language];
  const suggested = source.suggestedCheckIn;
  const suggestion = suggested[language];

  // The server picks the agent mode; the check-in's language picks the recording replay plays.
  const checkInLanguage = language === "es" ? "ES" : "EN";
  const startIntake = () => source.startIntake(checkInLanguage, scenario.frontdeskIntake.scenarioContextId);
  // A reset on the corpus takes seconds and wipes every check-in when it lands: nothing is sent
  // meanwhile, and ResetButton starts the new check-in once it has finished.
  const resetting = useIsMutating({ mutationKey: SESSION_CHANGE_KEY }) > 0;
  const demo = useDemoReset();
  // The message in flight, read from the cache like `resetting`: the suggestion bar and Start
  // over are locked while it is being read, so nothing else lands in the same check-in.
  const sending = useIsMutating({ mutationKey: SEND_TURN_KEY }) > 0;
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

  const gateCard = useRef<HTMLDivElement | null>(null);
  const composer = useRef<HTMLTextAreaElement>(null);

  // The toggle changed before the first turn: start over in the new language, so the demo
  // script line goes into a check-in in its own language.
  const restart = !resetting && !send.isPending && needsNewCheckIn(session.data, checkInLanguage);
  useEffect(() => {
    if (restart) void queryClient.resetQueries({ queryKey: INTAKE_KEY });
  }, [restart, queryClient]);

  // UX 3.10: after a reset the presenter types straight into the kiosk.
  const wasResetting = useRef(false);
  useEffect(() => {
    if (wasResetting.current && !resetting) composer.current?.focus();
    wasResetting.current = resetting;
  }, [resetting]);
  const gateCount = turns.filter((turn) => (turn.toolCalls ?? []).some((c) => gateDenial(c))).length;

  function submit() {
    const message = text.trim();
    if (!message || send.isPending || resetting || !session.data) return;
    // One key per typed message, reused when the same message is retried.
    if (key.current?.text !== message) key.current = { text: message, key: crypto.randomUUID() };
    setText("");
    composer.current?.focus(); // Send is disabled once the text clears; keep focus in the composer
    send.mutate(key.current);
  }

  const agentMode = session.data?.agentMode;
  // Held and not yet decided: say what did not happen, so the patient is not left guessing.
  const held = session.data?.registration?.state === "PENDING_REGISTRAR" && decided === null;
  const pending = send.isPending ? send.variables?.text : null;
  const failedText = failed && failed.sessionId === session.data?.id ? failed.text : null;

  // New lines come into view. A new gate card comes first: its row is scrolled into view, the whole
  // card at least (it is the moment the demo is about; the row, as the card's entrance transform
  // would skew the card), and lines under it may stay below. Otherwise the newest line scrolls into
  // view when a turn, a decision, a "reading" row or a failure is added; the "reading" row going
  // away is not an addition, so it never pulls the gate card off. Side by side only the kiosk pane
  // scrolls (globals.css, .pane); stacked, only a new gate card moves the page, so a registrar's
  // decision never pulls the page away from the staff pane.
  const transcript = useRef<HTMLOListElement>(null);
  const shown = useRef({ turns: 0, gates: 0, decided: null as string | null, pending: false, failed: false });
  useEffect(() => {
    const was = shown.current;
    const now = { turns: turns.length, gates: gateCount, decided, pending: !!pending, failed: !!failedText };
    shown.current = now;
    const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
    const card = gateCard.current;
    const row = card?.parentElement;
    if (now.gates > was.gates && card && row) {
      row.scrollIntoView({ block: gateRowBlock(row, card), behavior });
      return;
    }
    const added =
      now.turns > was.turns ||
      (now.decided !== null && now.decided !== was.decided) ||
      (now.pending && !was.pending) ||
      (now.failed && !was.failed);
    const last = transcript.current?.lastElementChild;
    if (added && last && scrollPane(last)) last.scrollIntoView({ block: "nearest", behavior });
  }, [turns.length, gateCount, decided, pending, failedText]);

  return (
    <section lang={language} aria-labelledby="kiosk-label" className="flex min-w-0 flex-col gap-4">
      <h2 id="kiosk-label" className="text-[16px] font-semibold uppercase tracking-wider text-ink-3">
        {t.pane}
      </h2>
      <div
        data-working={send.isPending}
        className="kiosk-frame flex min-h-[560px] flex-col gap-4 rounded-lg border border-border-subtle bg-kiosk p-6"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-[24px] font-semibold">FrontDesk</span>
          <div
            role="group"
            aria-label={t.language}
            className="flex rounded-md border border-border-strong p-0.5"
          >
            {LANGUAGES.map(({ value, label }) => (
              <button
                key={value}
                type="button"
                lang={value}
                aria-pressed={language === value}
                onClick={() => {
                  setLanguage(value);
                  announce(COPY[value].switched);
                }}
                className={`h-10 rounded px-4 text-[16px] ${
                  language === value ? "bg-surface font-semibold text-ink-1 shadow-sm" : "text-ink-2"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div>
          <p className="text-[40px] font-semibold leading-[48px] tracking-tight">{t.title}</p>
          <p className="text-[20px] text-ink-2">{t.sub}</p>
          <p className="text-[16px] text-ink-3">{t.disclosure}</p>
        </div>
        <section aria-label={t.region} className="flex flex-1 flex-col border-t border-border-subtle pt-3">
          <div className="flex flex-wrap items-center gap-3">
            <h3 className="text-[16px] font-semibold tracking-wider text-ink-3">{t.transcript}</h3>
            {agentMode && (
              <span
                data-testid="agent-mode-badge"
                className="inline-flex items-center gap-1 rounded border border-dashed border-ink-2 px-2 text-[16px] font-semibold text-ink-2"
              >
                {t.agentMode(agentMode)}
              </span>
            )}
            {turns.length > 0 && (
              <button
                type="button"
                disabled={sending || resetting}
                onClick={() => {
                  setFailed(null);
                  setText("");
                  key.current = null;
                  send.reset();
                  if (source.mode === "LOCAL") {
                    // Every check-in leaves an intake record on the server, and the next check-in's
                    // gate would match it: the patient's own earlier entry scores AUTO_LINK and takes
                    // the card from the hero chart. Only the demo reset removes it (the kiosk then
                    // starts a new check-in and takes focus); the fixture keeps no such record.
                    demo.reset.mutate();
                    return;
                  }
                  void queryClient.resetQueries({ queryKey: INTAKE_KEY });
                  void queryClient.resetQueries({ queryKey: HANDOFF_KEY });
                  composer.current?.focus();
                }}
                className="ml-auto font-semibold text-accent underline underline-offset-2 disabled:text-ink-3"
              >
                {t.startOver}
              </button>
            )}
          </div>
          {session.isError ? (
            <div data-testid="kiosk-start-error" className="m-auto text-center text-[16px]">
              <p>{t.startFailed}</p>
              <button
                type="button"
                onClick={() => void session.refetch()}
                className="mt-1 font-semibold text-accent underline underline-offset-2"
              >
                {t.tryAgain}
              </button>
            </div>
          ) : turns.length === 0 && !pending && !failedText ? (
            // pt-4 matches the 16 px gap to the composer below, so the line sits centred between them.
            <p className="m-auto pt-4 text-center text-ink-3">{t.empty}</p>
          ) : (
            <ol ref={transcript} aria-live="off" className="mt-3 flex flex-col gap-3">
              {turns.map((turn) => (
                <Turn key={turn.turnIndex} turn={turn} t={t} gateRef={(el) => (gateCard.current = el)} />
              ))}
              {held && (
                <li data-testid="kiosk-finish-held" className="text-[20px] font-semibold text-ink-1">
                  {t.heldFinish}
                </li>
              )}
              {decided === "LINKED" && <Agent text={t.approved} automatic t={t} />}
              {decided === "REJECTED" && <Agent text={t.rejected} automatic t={t} />}
              {pending && (
                <>
                  <li className="ml-auto max-w-[80%] rounded-lg border border-border-subtle bg-surface px-4 py-3 text-[20px]">
                    {pending}
                  </li>
                  <li aria-busy="true" className="text-[18px] text-ink-3">
                    {t.reading}
                    <span className="indeterminate mt-1 block h-0.5 w-40" />
                  </li>
                </>
              )}
              {failedText && !send.isPending && (
                <li className="max-w-[80%] text-[20px]">
                  <p className="text-[18px] font-semibold text-ink-2">
                    {t.speaker} <span className="ml-2 font-normal text-ink-3">{t.automatic}</span>
                  </p>
                  <p>{t.agentDown}</p>
                  <button
                    type="button"
                    onClick={submit}
                    className="mt-1 font-semibold text-accent underline underline-offset-2"
                  >
                    {t.tryAgain}
                  </button>
                </li>
              )}
            </ol>
          )}
        </section>
        <form
          className="flex flex-col gap-1"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <div className="flex items-end gap-2">
            <textarea
              ref={composer}
              data-testid="kiosk-composer"
              aria-label={t.placeholder}
              placeholder={t.placeholder}
              value={text}
              maxLength={MAX_CHARS}
              rows={2}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
              className="min-h-16 min-w-0 flex-1 resize-none rounded-md border border-border-strong bg-surface px-3 py-2 text-[20px]"
            />
            <button
              type="submit"
              data-testid="kiosk-send"
              disabled={!text.trim() || send.isPending || resetting || !session.data}
              className="h-14 rounded-md bg-accent px-6 font-semibold text-on-accent hover:bg-accent-hover disabled:bg-sunken disabled:text-ink-3"
            >
              {t.send}
            </button>
          </div>
          <p className="text-[16px] text-ink-3">
            {send.isPending ? t.wait : t.helper}
            {text.length >= COUNTER_FROM && (
              <span className="ml-2 tabular-nums">{t.counter(text.length)}</span>
            )}
          </p>
          <p data-testid="kiosk-promise" className="text-[18px] text-ink-1">
            {t.promise}
          </p>
        </form>
        {turns.length === 0 && (
          <div className="flex flex-wrap items-center gap-2 rounded-md bg-sunken px-3 py-2 text-[16px]">
            {suggested.demoScript ? (
              <span lang="en" className="font-semibold">
                Demo script
              </span>
            ) : (
              <span className="font-semibold">{t.suggestLabel}</span>
            )}
            <q lang={language} className="min-w-0 flex-1 text-ink-2">
              {suggestion}
            </q>
            <ConstructedChip label={t.constructed} explanation={t.constructedKiosk} />
            <button
              type="button"
              disabled={resetting || sending}
              onClick={() => {
                setText(suggestion);
                composer.current?.focus();
              }}
              className="font-semibold text-accent underline underline-offset-2 disabled:text-ink-3"
            >
              {t.suggestUse}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
