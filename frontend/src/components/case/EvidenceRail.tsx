"use client";

import { animate } from "motion";
import { useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import type { CandidatePairDetail, NormalizedRecord, SourceCard, ThresholdSet } from "@/api/types";
import { useCite } from "@/components/desk/CiteProvider";
import { BandStamp } from "@/components/ui/BandStamp";
import type { CiteField } from "@/lib/desk";
import { CITE_CARD_FIELDS, citeFieldFor, evidenceDots, evidenceNote, rankContributions } from "@/lib/display";
import styles from "./EvidenceRail.module.css";

const TOP_CONTRIBUTIONS = 5;
/** On the compact layer the rail shows this many rows with "Show all" (EvidenceRail.module.css). */
const COMPACT_ROWS = 4;
/** The score ticks up from 0 over this long (CONCEPT.md §5, touch 7), ease-out cubic. */
const TICK_MS = 700;
const TICK_EASE: [number, number, number, number] = [0.33, 1, 0.68, 1];

function signed(logit: number): string {
  return `${logit >= 0 ? "+" : "-"}${Math.abs(logit).toFixed(2)}`;
}

/** The value a record holds for a cited field, as the claim reads it out. */
function citedValue(record: NormalizedRecord, field: CiteField | null): string | null {
  if (!field) return null;
  const parts = CITE_CARD_FIELDS[field].map((k) => record[k]).filter((v) => v != null);
  return parts.length ? parts.join(" ") : null;
}

function claim(
  label: string,
  note: string,
  logit: number,
  field: CiteField | null,
  a: SourceCard,
  b: SourceCard,
): string {
  const lower = note.charAt(0).toLowerCase() + note.slice(1);
  const side = (card: SourceCard) => {
    const value = citedValue(card.normalized, field);
    return value ? `${card.displayLabel} ${value}.` : `Not given on ${card.displayLabel}.`;
  };
  const values = field ? ` ${side(a)} ${side(b)}` : "";
  return `${label}, ${lower}, weight ${signed(logit)}.${values}`;
}

/** The score, ticking: the final value is in the markup (honest without JavaScript); on mount it
 * runs up from 0.00 with motion's animate(), unless the person asked for reduced motion. */
function Score({ p, decisionId }: { p: number; decisionId: string }) {
  const el = useRef<HTMLSpanElement>(null);
  const reduce = useReducedMotion();
  useEffect(() => {
    const node = el.current;
    if (!node || reduce) return;
    const controls = animate(0, p, {
      duration: TICK_MS / 1000,
      ease: TICK_EASE,
      onUpdate: (v) => {
        node.textContent = v.toFixed(2);
      },
    });
    return () => controls.stop();
  }, [p, reduce, decisionId]);
  return (
    <span
      ref={el}
      data-testid="pair-score"
      className="font-display text-[64px] font-bold leading-[0.9] tracking-[-0.04em] tabular-nums text-ink"
    >
      {p.toFixed(2)}
    </span>
  );
}

function Dots({ logit }: { logit: number }) {
  const fills = evidenceDots(logit);
  return (
    <span data-testid="evidence-dots" aria-hidden className="flex gap-[3px]">
      {fills.map((f, i) => (
        <i
          key={i}
          data-testid="evidence-dot"
          className={`${styles.dot} ${logit < 0 ? styles.dotAgainst : ""}`}
          style={{ "--f": `${Math.round(f * 100)}%` } as React.CSSProperties}
        />
      ))}
    </span>
  );
}

interface Props {
  detail: CandidatePairDetail;
  /** The threshold set the band came from; undefined while it loads (then no claim is made). */
  thresholds: ThresholdSet | undefined;
}

export function EvidenceRail({ detail, thresholds }: Props) {
  const { decision } = detail.pair;
  const { recordA, recordB } = detail;
  const ranked = rankContributions(detail.contributions).slice(0, TOP_CONTRIBUTIONS);
  const [showAll, setShowAll] = useState(false);
  const { cite, setCite } = useCite();

  return (
    <section data-testid="evidence-rail" aria-labelledby="evidence-heading">
      <h2 id="evidence-heading" className="text-[13px] font-semibold text-ink-2">
        Match score
      </h2>
      <div className="mt-2.5 flex items-end gap-3.5">
        <Score p={decision.p} decisionId={decision.id} />
        <div className="flex flex-col gap-1 pb-1">
          <BandStamp band={decision.band} testId="pair-band" />
          {thresholds && !thresholds.autoLinkEnabled && (
            <small className="text-[13px] leading-tight text-ink-2">Auto-link is off. You decide.</small>
          )}
        </div>
      </div>
      <ul aria-label="Top evidence" className="mt-4 mb-1 list-none">
        {ranked.map((c, i) => {
          const field = citeFieldFor(c.feature);
          const note = c.missing ? "Not given on one side" : evidenceNote(c.feature, c.value);
          const cited = field !== null && cite === field;
          return (
            <li
              key={c.feature}
              data-testid="evidence-feature-row"
              data-cite={field ?? undefined}
              data-cited={cited}
              tabIndex={0}
              aria-label={claim(c.label, note, c.logit, field, recordA, recordB)}
              onMouseEnter={() => setCite(field)}
              onMouseLeave={() => setCite(null)}
              onFocus={() => setCite(field)}
              onBlur={() => setCite(null)}
              className={`-mx-2 grid min-h-11 grid-cols-[1fr_auto_42px] items-center gap-2.5 rounded-[10px] px-2 py-1.5 transition-colors duration-[var(--t-micro)] hover:bg-mulberry-tint focus-visible:bg-mulberry-tint ${
                cited ? "bg-mulberry-tint" : ""
              } ${i >= COMPACT_ROWS && !showAll ? styles.compactHidden : ""}`}
            >
              <span className="text-[15px] leading-[1.25] text-ink">
                {c.label}
                <small className="block text-[13px] text-ink-2">{note}</small>
              </span>
              {c.missing ? (
                <span className="col-span-2 text-right text-[13px] text-ink-3">no evidence</span>
              ) : (
                <>
                  <Dots logit={c.logit} />
                  <span className="text-right font-mono text-[14px] leading-none text-ink">{signed(c.logit)}</span>
                </>
              )}
            </li>
          );
        })}
      </ul>
      {!showAll && ranked.length > COMPACT_ROWS && (
        <button
          type="button"
          onClick={() => setShowAll(true)}
          className={`${styles.compactOnly} min-h-6 text-[13px] font-semibold text-ink underline underline-offset-2`}
        >
          Show all ({ranked.length})
        </button>
      )}
      <p className="mb-4 mt-1.5 text-[13px] leading-snug text-ink-2">
        {thresholds && !thresholds.isCalibrated && "Hand-set demo weights, not calibrated. "}
        Ask the patient for a phone number or photo ID.
      </p>
    </section>
  );
}
