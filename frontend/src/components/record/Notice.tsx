"use client";

import { ChevronRight, Flag } from "lucide-react";
import { motion } from "motion/react";
import { useState } from "react";
import type { SafetyAlert, SourceCard } from "@/api/types";
import { sourceSystemLabel } from "@/components/frontdesk/copy";
import { ConstructedChip } from "@/components/ui/ConstructedChip";
import { RuleResultTag } from "@/components/ui/RuleResultTag";
import { footerWithoutRule } from "@/lib/display";
import { flagFacts } from "@/lib/flagHeadline";
import { NOTICE, NOTICE_EXPAND_RISE } from "./geometry";
import { sourceName } from "./labels";
import { CROSSFADE_S, EASE_OUT, NOTICE_EXPAND_S, NOTICE_IN, type MorphMode } from "./motion";

export interface NoticeProps {
  alert: SafetyAlert;
  mode: MorphMode;
  /** The session's cards, for the sources' names; the system code's words otherwise. */
  cards?: SourceCard[];
}

const translate = (px: number) => `translateY(${px}px)`;
const inset = (sides: number) => `inset(0 ${sides}% 0 ${sides}% round ${NOTICE.radius}px)`;

function entrance(mode: MorphMode) {
  if (mode === "morph") {
    return {
      initial: { clipPath: inset(50), transform: translate(NOTICE.rise), opacity: 0 },
      animate: { clipPath: inset(0), transform: translate(0), opacity: 1 },
      transition: {
        clipPath: { duration: NOTICE_IN.duration, ease: EASE_OUT, delay: NOTICE_IN.delay },
        transform: { duration: NOTICE_IN.duration, ease: EASE_OUT, delay: NOTICE_IN.delay },
        opacity: { duration: NOTICE_IN.opacity, delay: NOTICE_IN.delay },
      },
    };
  }
  if (mode === "crossfade") {
    return { initial: { opacity: 0 }, animate: { opacity: 1 }, transition: { duration: CROSSFADE_S } };
  }
  return { initial: false as const, animate: { opacity: 1 }, transition: { duration: 0 } };
}

/** The flag card, risen out of the seam (CONCEPT.md §1, touch 10): paper and ink on the record,
 * one sentence, the rule named, the full text one click away. Neutral by design: it flags for
 * review and does not alarm, so no red, no role="alert"; the stage's polite live region says it. */
export function Notice({ alert, mode, cards = [] }: NoticeProps) {
  const [expanded, setExpanded] = useState(false);
  const { allergy, order } = flagFacts(alert);
  const nameOf = (system: string) =>
    sourceName(system, cards.find((c) => c.record.sourceSystem === system)?.displayLabel ?? sourceSystemLabel(system));
  const { initial, animate, transition } = entrance(mode);
  return (
    <motion.article
      id="flag"
      data-testid="flag-card"
      aria-labelledby="flag-heading"
      className="org-notice"
      initial={false}
      animate={{ transform: translate(expanded ? -NOTICE_EXPAND_RISE : 0) }}
      transition={{ duration: mode === "instant" ? 0 : NOTICE_EXPAND_S, ease: EASE_OUT }}
    >
      <motion.div className="org-notice-card" initial={initial} animate={animate} transition={transition}>
        <header className="org-n-top">
          <Flag aria-hidden size={20} strokeWidth={1.7} />
          <h3 id="flag-heading" tabIndex={-1}>
            Flagged for clinician review
          </h3>
          <span className="org-rule">
            <span data-testid="flag-card-rule-id">{alert.ruleId}</span>
            <span>{alert.ruleVersion}</span>
          </span>
        </header>
        <p data-testid="flag-card-headline">
          <b>{allergy}</b> on the {nameOf(alert.allergyRef.sourceSystem)} record, and an <b>{order}</b> on the{" "}
          {nameOf(alert.orderRef.sourceSystem)} record. A clinician decides.
        </p>
        <div className="org-n-foot">
          {alert.constructedScenario && <ConstructedChip />}
          <RuleResultTag label="Rule result" />
          <span>{alert.revealedByMerge ? "Surfaced by the link" : "On the linked record"}</span>
        </div>
        {/* The full text (codes, the citation, the rule's limits) is one click away, so the notice reads in a glance. */}
        <details className="org-n-details" onToggle={(e) => setExpanded(e.currentTarget.open)}>
          <summary>
            {expanded ? "Less" : "Details"}
            <ChevronRight aria-hidden size={14} className="org-chev" />
          </summary>
          <div className="org-n-body">
            <p className="org-n-text">{alert.cardText}</p>
            {alert.citation && (
              <p className="org-n-source">
                Source:{" "}
                <a href={alert.citation.url} target="_blank" rel="noreferrer">
                  {alert.citation.labelName}, DailyMed, revised {alert.citation.revised}
                </a>
              </p>
            )}
            <p className="org-n-limits">{footerWithoutRule(alert.cardFooter, alert.ruleId, alert.ruleVersion)}</p>
          </div>
        </details>
      </motion.div>
    </motion.article>
  );
}
