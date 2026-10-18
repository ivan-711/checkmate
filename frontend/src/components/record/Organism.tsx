"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import type { Entity, SourceCard } from "@/api/types";
import type { CiteField, DeskState, Sheet } from "@/lib/desk";
import type { FlagState } from "@/lib/flagState";
import { fieldMark, nameDiff, type Mark } from "./cite";
import { useCite } from "./CiteContext";
import { Fragment, type FragmentCustom } from "./Fragment";
import { Joined } from "./Joined";
import { FOCUS_AFTER_MORPH_MS, morphMode, threadsArmed } from "./motion";
import { Threads } from "./Threads";
import "./organism.css";

export interface OrganismProps {
  /** The session's showcase sources, ER first: the two fragments. */
  cards: SourceCard[];
  stage: DeskState;
  /** Which confirm sheet is open: the fragments lean in to approve, apart to reject. */
  sheet?: Sheet;
  /** The linked record, once the stage is linked. */
  entity: Entity | null;
  flag: FlagState;
  /** The fields the shown evidence cites (citedFields), strongest first: one thread each. */
  threads?: CiteField[];
  /** Carries the candidate-pair hook once a pair exists (CONCEPT.md §7). */
  isPair?: boolean;
  /** After an approval made here, focus moves to the notice's heading (or the record's). */
  focusAfterLink?: boolean;
  onFocused?: () => void;
}

/** The stage change this render is showing: from the last stage to this one. Held in state so it
 * stays the same across re-renders until the stage changes again. */
function useStageChange(stage: DeskState): { from: DeskState | undefined; to: DeskState } {
  const [change, setChange] = useState<{ from: DeskState | undefined; to: DeskState }>({ from: undefined, to: stage });
  if (change.to !== stage) setChange({ from: change.to, to: stage });
  return change.to === stage ? change : { from: change.to, to: stage };
}

/** The living record (CONCEPT.md §1): two fragments with matching wavy edges, threads across the
 * gap at each cited field, and on approval the fusion into one record with the notice rising out of
 * the join. The fragments leave the DOM at the end of the morph (AnimatePresence), so the acceptance
 * script counts zero source cards. */
export function Organism({
  cards,
  stage,
  sheet = null,
  entity,
  flag,
  threads = [],
  isPair = false,
  focusAfterLink = false,
  onFocused,
}: OrganismProps) {
  const reduced = useReducedMotion() ?? false;
  const change = useStageChange(stage);
  const mode = morphMode({ ...change, reduced });
  const armed = threadsArmed(change);
  const { cite } = useCite();
  const host = useRef<HTMLDivElement>(null);

  const [er, cl] = cards;
  const diff = er && cl ? nameDiff(er.normalized.familyName ?? "", cl.normalized.familyName ?? "") : null;
  const marks: Partial<Record<CiteField, Mark>> = {};
  for (const field of threads) {
    const mark = er && cl ? fieldMark(field, er.normalized, cl.normalized) : null;
    if (mark) marks[field] = mark;
  }
  const drawn = threads.filter((field) => marks[field]);

  const linked = stage === "linked" && entity !== null;
  const custom: FragmentCustom = { sheet, mode };

  // Focus follows the eye after an approval made here (DESIGN.md, Focus): the notice's heading
  // once it has risen, or the record's heading when the rule was silent. Never on load.
  useEffect(() => {
    if (!focusAfterLink || !linked) return;
    const timer = setTimeout(
      () => {
        const target = host.current?.querySelector<HTMLElement>(
          flag.kind === "raised" ? "#flag-heading" : "#golden-heading",
        );
        target?.focus({ preventScroll: true });
        target?.scrollIntoView({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
        onFocused?.();
      },
      mode === "morph" ? FOCUS_AFTER_MORPH_MS : 0,
    );
    return () => clearTimeout(timer);
  }, [focusAfterLink, linked, flag.kind, mode, reduced, onFocused]);

  return (
    <motion.div
      ref={host}
      className="organism"
      data-testid={isPair ? "candidate-pair" : undefined}
      data-cite={cite ?? undefined}
      initial={false}
      animate={stage}
      custom={custom}
    >
      <AnimatePresence initial={false} custom={custom}>
        {!linked && er && <Fragment key="er" card={er} side="er" diff={diff} custom={custom} />}
        {!linked && cl && <Fragment key="cl" card={cl} side="cl" diff={diff} custom={custom} />}
        {(stage === "review" || stage === "confirm") && drawn.length > 0 && (
          <Threads key="threads" fields={drawn} marks={marks} host={host} armed={armed} />
        )}
      </AnimatePresence>
      {linked && <Joined entity={entity} cards={cards} flag={flag} mode={mode} />}
    </motion.div>
  );
}
