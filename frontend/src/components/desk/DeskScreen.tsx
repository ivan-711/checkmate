"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { KioskPane } from "@/components/frontdesk/KioskPane";
import { citedFields } from "@/components/record/cite";
import { Organism } from "@/components/record/Organism";
import { typingInField } from "@/components/ui/Header";
import { DataError } from "@/data/source";
import { useIntakeSession } from "@/components/frontdesk/intake";
import {
  agoText,
  formatHeld,
  newChartStageHead,
  stageHead,
  type CiteContext,
  type DeskState,
} from "@/lib/desk";
import { newChartFacts } from "@/lib/kioskNewChart";
import { ActivityStrip } from "./ActivityStrip";
import { CiteProvider } from "./CiteProvider";
import { DecisionColumn } from "./DecisionColumn";
import { useDesk, useDeskAction } from "./DeskContext";
import { useDeskCase } from "./useDeskCase";

const SECOND_MS = 1000;
const WAITING_STATES: DeskState[] = ["held", "review", "confirm"];

/** A clock that ticks once a second while `active`, for the live eyebrow times. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), SECOND_MS);
    return () => clearInterval(id);
  }, [active]);
  return now;
}

/** Row 1 of the stage: an eyebrow with the live wait, a plain-language title, one gray line. */
function StageHead() {
  const { desk, kiosk, facts } = useDesk();
  const newChart = newChartFacts(useIntakeSession());
  const head = desk === "idle" && newChart ? newChartStageHead(newChart.name) : stageHead(desk, facts);
  const waiting = WAITING_STATES.includes(desk) && kiosk === "held";
  const now = useNow(waiting || desk === "linked");
  const [heldSince, setHeldSince] = useState<number | null>(null);
  useEffect(() => {
    setHeldSince(kiosk === "held" ? Date.now() : null);
  }, [kiosk]);
  const linkedAt = facts.linkedAt ? Date.parse(facts.linkedAt) : null;
  const suffix =
    waiting && heldSince
      ? ` · held ${formatHeld((now - heldSince) / SECOND_MS)}`
      : desk === "linked" && linkedAt
        ? ` · ${agoText((now - linkedAt) / SECOND_MS)}`
        : "";
  const dot = kiosk === "working" ? "working" : WAITING_STATES.includes(desk) ? "waiting" : null;
  return (
    <div className="stage-head" data-desk={desk}>
      <p className="flex h-[22px] items-center gap-2.5 text-[15px] font-semibold text-ink-2">
        {dot && (
          <span
            aria-hidden="true"
            className={`block h-2 w-2 rounded-full ${dot === "working" ? "animate-pulse bg-mulberry" : "bg-ink"}`}
          />
        )}
        <span data-testid="stage-eyebrow">
          {head.eyebrow}
          {suffix}
        </span>
      </p>
      <h2 data-testid="stage-title" className="stage-title">
        {head.title}
      </h2>
      <p data-testid="stage-subtitle" className="mt-3 max-w-[760px] text-[18px] text-ink-2">
        {head.subtitle}
      </p>
    </div>
  );
}

/** The Desk (CONCEPT.md §3): the kiosk device on the left, the registrar's stage on the right,
 * three fixed rows so nothing jumps between states. The body holds the Organism (L3) beside the
 * decision column (L4). The kiosk (L2) reports its state through setKiosk. */
export function DeskScreen() {
  const { desk, kiosk, setKiosk, sheet, cite, setCite, actions, commandsOpen } = useDesk();
  const c = useDeskCase();
  const { setJustApproved } = c;
  // The Organism reads the cite the evidence rail writes; DeskContext owns it, so both meet there.
  const citeValue = useMemo<CiteContext>(() => ({ cite, setCite }), [cite, setCite]);
  // Stable, so the Organism's focus timer is not restarted by unrelated re-renders.
  const onFocused = useCallback(() => setJustApproved(false), [setJustApproved]);
  const resolveNow = () => {
    if (!c.resolve.isPending && !c.sessionChanging) c.resolve.mutate();
  };
  // Resolve is offered while the pair is not under review: before the first run and after a reject.
  const canResolve = !c.caseQuery.isPending && !c.linked && !c.underReview;
  useDeskAction("resolve", canResolve ? resolveNow : null);

  // The keyboard map (CONCEPT.md §5, touch 11): R, A, X, Enter, Escape. ⌘K and ⇧R are the
  // header's. Letters never fire inside a text control; Enter only on the confirm sheet.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (commandsOpen || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "Escape") {
        actions.cancel?.();
        return;
      }
      if (
        e.key === "Enter" &&
        desk === "confirm" &&
        (e.target as HTMLElement | null)?.tagName !== "TEXTAREA"
      ) {
        if (actions.confirm) {
          e.preventDefault();
          actions.confirm();
        }
        return;
      }
      if (typingInField(e.target) || e.shiftKey) return;
      const run = { r: actions.resolve, a: actions.approve, x: actions.reject }[e.key.toLowerCase()];
      if (run) {
        e.preventDefault();
        run();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [actions, desk, commandsOpen]);

  const cards = c.cards;
  // A check-in that opened a new chart matched none of the records on file: show only the new patient.
  const intake = useIntakeSession();
  const newChart = desk === "idle" && newChartFacts(intake) !== null;
  // One thread per field the shown evidence cites, once Resolve has scored the pair.
  const threads = c.detail && (c.resolved || c.linked) ? citedFields(c.detail.contributions) : [];
  const noSession =
    c.caseQuery.isError && c.caseQuery.error instanceof DataError && c.caseQuery.error.code === "NO_SESSION";

  return (
    <div className="desk">
      <h1 className="sr-only">CheckMate identity desk</h1>
      <section
        aria-label="Patient kiosk"
        className="desk-region overflow-y-auto rounded-device bg-paper shadow-[0_0_0_1px_var(--hair),0_24px_60px_-30px_rgba(60,20,55,0.18)]"
        data-kiosk={kiosk}
      >
        {/* "Looking at it now" only once the registrar opens the confirm sheet: the hand-off itself
            already proposes the pair, so "review" starts the moment the check-in is held. */}
        <KioskPane onStateChange={setKiosk} registrarReviewing={desk === "confirm"} />
      </section>

      <section aria-label="Registrar" className="desk-region stage">
        <StageHead />

        <CiteProvider value={citeValue}>
          <div className="stage-body">
            {/* The Organism (L3): the fragments, their threads, and after Approve the one record with
                the notice risen from the join. History lives in the decision column. */}
            <div className="min-w-0">
              <div className="organism-slot" data-testid="organism-slot">
                {c.caseQuery.isPending && <p aria-busy="true">Loading records…</p>}
                {noSession && <p data-testid="reset-prompt">{c.caseQuery.error?.message}</p>}
                {c.caseQuery.isError && !noSession && (
                  <p className="text-ink-2">Records unavailable: {c.caseQuery.error.message}</p>
                )}
                {cards.length > 0 && !newChart && (
                  <div className="organism-scale">
                    <Organism
                      cards={cards}
                      stage={desk}
                      sheet={sheet}
                      entity={c.entity}
                      flag={c.flag}
                      threads={threads}
                      focusAfterLink={c.justApproved}
                      onFocused={onFocused}
                    />
                  </div>
                )}
              </div>
            </div>

            {/* The decision column (L4): Resolve, the evidence and Approve, the confirm sheet, History. */}
            <div className="decision-col" data-testid="decision-column">
              <DecisionColumn c={c} onResolve={resolveNow} />
            </div>
          </div>
        </CiteProvider>

        <ActivityStrip />
      </section>
    </div>
  );
}
