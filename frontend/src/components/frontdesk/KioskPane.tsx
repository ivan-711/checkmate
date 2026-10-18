"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { IntakeSession, IntakeTurn, ToolCallRecord } from "@/api/types";
import { ConstructedChip } from "@/components/ui/ConstructedChip";
import { useAnnounce } from "@/components/ui/LiveRegion";
import { useDataSource } from "@/data/DataSourceProvider";
import { scenario } from "@/data/scenario";
import { DataError } from "@/data/source";
import { COPY, type KioskCopy, type KioskLanguage } from "./copy";
import { GateCard } from "./GateCard";
import { HANDOFF_KEY, INTAKE_KEY, useHandoffPairs } from "./intake";
import { ToolCallChip } from "./ToolCallChip";

const MAX_CHARS = 280; // UX 3.11 composer limit; the contract allows 500
const COUNTER_FROM = 240;

const LANGUAGES: { value: KioskLanguage; label: string }[] = [
  { value: "en", label: "English" },
  { value: "es", label: "Español" },
];

/** The denied new chart that a registrar now holds: the card the demo is about. */
function gateDenial(call: ToolCallRecord) {
  const candidate = call.candidates?.[0];
  const held = call.gate.outcome === "DENY" && call.gate.reasonCode === "CANDIDATE_IN_REVIEW_OR_HIGHER";
  return held && candidate ? candidate : null;
}

function Agent({ text, automatic, t }: { text: string; automatic: boolean; t: KioskCopy }) {
  return (
    <li className="max-w-[80%] text-[20px]">
      <p className="text-[14px] font-semibold text-ink-2">
        {t.speaker}
        {automatic && <span className="ml-2 font-normal text-ink-3">{t.automatic}</span>}
      </p>
      <p>{text}</p>
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
      {calls.map((call) => {
        const candidate = gateDenial(call);
        return (
          <li key={call.id} className="space-y-2">
            <ToolCallChip call={call} t={t} hasGateCard={!!candidate} />
            {candidate && <GateCard ref={gateRef} call={call} candidate={candidate} t={t} />}
          </li>
        );
      })}
      {handedOff && <Agent text={t.handoff} automatic t={t} />}
      <Agent text={turn.assistantText} automatic={turn.assistantTextSource === "TEMPLATE"} t={t} />
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

  // The server picks the agent mode; the session language only seeds the first reply.
  const startIntake = () =>
    source.startIntake(language === "es" ? "ES" : "EN", scenario.frontdeskIntake.scenarioContextId);
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
  const gateCount = turns.filter((turn) => (turn.toolCalls ?? []).some((c) => gateDenial(c))).length;
  useEffect(() => {
    // A new gate card always scrolls fully into view: it is the moment the demo is about.
    if (gateCount === 0) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    gateCard.current?.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
  }, [gateCount]);

  function submit() {
    const message = text.trim();
    if (!message || send.isPending || !session.data) return;
    // One key per typed message, reused when the same message is retried.
    if (key.current?.text !== message) key.current = { text: message, key: crypto.randomUUID() };
    setText("");
    composer.current?.focus(); // Send is disabled once the text clears; keep focus in the composer
    send.mutate(key.current);
  }

  const agentMode = session.data?.agentMode;
  const pending = send.isPending ? send.variables?.text : null;
  const failedText = failed && failed.sessionId === session.data?.id ? failed.text : null;

  return (
    <section lang={language} aria-labelledby="kiosk-label" className="flex min-w-0 flex-col gap-4">
      <h2 id="kiosk-label" className="text-[16px] font-semibold uppercase tracking-wider text-ink-3">
        {t.pane}
      </h2>
      <div className="flex min-h-[560px] flex-col gap-4 rounded-lg border border-border-subtle bg-kiosk p-6">
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
                className="inline-flex items-center gap-1 rounded border border-dashed border-ink-2 px-2 text-[14px] font-semibold text-ink-2"
              >
                Agent: {agentMode}
              </span>
            )}
            {turns.length > 0 && (
              <button
                type="button"
                disabled={send.isPending}
                onClick={() => {
                  setFailed(null);
                  setText("");
                  key.current = null;
                  send.reset();
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
          ) : turns.length === 0 && !pending ? (
            <p className="m-auto text-ink-3">{t.empty}</p>
          ) : (
            <ol aria-live="off" className="mt-3 flex flex-col gap-3">
              {turns.map((turn) => (
                <Turn key={turn.turnIndex} turn={turn} t={t} gateRef={(el) => (gateCard.current = el)} />
              ))}
              {decided === "LINKED" && <Agent text={t.approved} automatic t={t} />}
              {decided === "REJECTED" && <Agent text={t.rejected} automatic t={t} />}
              {pending && (
                <>
                  <li className="ml-auto max-w-[80%] rounded-lg border border-border-subtle bg-surface px-4 py-3 text-[20px]">
                    {pending}
                  </li>
                  <li aria-busy="true" className="text-[14px] text-ink-3">
                    {t.reading}
                    <span className="indeterminate mt-1 block h-0.5 w-40" />
                  </li>
                </>
              )}
              {failedText && !send.isPending && (
                <li className="max-w-[80%] text-[20px]">
                  <p className="text-[14px] font-semibold text-ink-2">
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
              disabled={!text.trim() || send.isPending || !session.data}
              className="h-14 rounded-md bg-accent px-6 font-semibold text-on-accent hover:bg-accent-hover disabled:bg-sunken disabled:text-ink-3"
            >
              {t.send}
            </button>
          </div>
          <p className="text-[14px] text-ink-3">
            {send.isPending ? t.wait : t.helper}
            {text.length >= COUNTER_FROM && (
              <span className="ml-2 tabular-nums">{t.counter(text.length)}</span>
            )}
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
              onClick={() => {
                setText(suggestion);
                composer.current?.focus();
              }}
              className="font-semibold text-accent underline underline-offset-2"
            >
              {t.suggestUse}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
