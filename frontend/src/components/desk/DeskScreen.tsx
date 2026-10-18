"use client";

import { useEffect, useState } from "react";
import { FlagCard } from "@/components/case/FlagCard";
import { GoldenRecord } from "@/components/case/GoldenRecord";
import { SourceCardView } from "@/components/case/SourceCardView";
import { KioskPane } from "@/components/frontdesk/KioskPane";
import { typingInField } from "@/components/ui/Header";
import { DataError } from "@/data/source";
import { agoText, formatHeld, stageHead, type DeskState } from "@/lib/desk";
import { differingFields, type CardField } from "@/lib/display";
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
  const head = stageHead(desk, facts);
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
      <h1 data-testid="stage-title" className="stage-title">
        {head.title}
      </h1>
      <p data-testid="stage-subtitle" className="mt-3 max-w-[760px] text-[18px] text-ink-2">
        {head.subtitle}
      </p>
    </div>
  );
}

/** The Desk (CONCEPT.md §3): the kiosk device on the left, the registrar's stage on the right,
 * three fixed rows so nothing jumps between states. Until the Organism (L3) and the decision
 * column (L4) land, the body slots compose the current case components so every G16 hook stays
 * live; the kiosk slot holds the current KioskPane until L2's. */
export function DeskScreen() {
  const { desk, kiosk, actions, commandsOpen, cite, setCite } = useDesk();
  const c = useDeskCase();
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
  const differs =
    cards.length === 2 ? differingFields(cards[0].normalized, cards[1].normalized) : new Set<CardField>();
  const noSession =
    c.caseQuery.isError && c.caseQuery.error instanceof DataError && c.caseQuery.error.code === "NO_SESSION";

  return (
    <div className="desk">
      <section
        aria-label="Patient kiosk"
        className="desk-region overflow-y-auto rounded-device bg-paper shadow-[0_0_0_1px_var(--hair),0_24px_60px_-30px_rgba(60,20,55,0.18)]"
        data-kiosk={kiosk}
      >
        <KioskPane />
      </section>

      <section aria-label="Registrar" className="desk-region stage">
        <StageHead />

        <CiteProvider value={{ cite, setCite }}>
          <div className="stage-body">
            {/* The Organism slot (L3). Interim: the two source cards, then the record, notice and history. */}
            <div className="organism-slot overflow-auto" data-testid="organism-slot">
              {c.caseQuery.isPending && <p aria-busy="true">Loading records…</p>}
              {noSession && <p data-testid="reset-prompt">{c.caseQuery.error?.message}</p>}
              {c.caseQuery.isError && !noSession && (
                <p className="text-ink-2">Records unavailable: {c.caseQuery.error.message}</p>
              )}
              {c.linked && c.entity ? (
                <div className="space-y-4">
                  <GoldenRecord
                    entity={c.entity}
                    cards={cards}
                    focusOnMount={c.justApproved && !c.flagRaised}
                    onFocused={() => c.setJustApproved(false)}
                  />
                  <div ref={c.flagRef}>
                    <FlagCard state={c.flag} />
                  </div>
                </div>
              ) : (
                cards.length > 0 && (
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                      {cards.map((card) => (
                        <SourceCardView key={card.record.id} card={card} differs={differs} />
                      ))}
                    </div>
                    <FlagCard state={c.flag} />
                  </div>
                )
              )}
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
