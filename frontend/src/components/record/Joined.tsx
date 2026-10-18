"use client";

import { Flag } from "lucide-react";
import { motion } from "motion/react";
import type { ReactNode } from "react";
import type { Entity, GoldenField, SourceCard } from "@/api/types";
import { ConstructedChip } from "@/components/ui/ConstructedChip";
import { goldenValueText } from "@/lib/display";
import type { FlagState } from "@/lib/flagState";
import { HEAL_X, STEM } from "./geometry";
import { RecordMark, SourceGlyph } from "./Glyph";
import { holdsLine, phoneLabel, sexLabel, sourceNameFrom } from "./labels";
import { CROSSFADE_S, EASE_OUT, HEAL, JOINED_IN, STEM_IN, type MorphMode } from "./motion";
import { Notice } from "./Notice";
import { Tabs } from "./Tabs";

export interface JoinedProps {
  entity: Entity;
  cards: SourceCard[];
  flag: FlagState;
  mode: MorphMode;
}

const QUIET_LINES = {
  none: "The rule did not flag this linked record. Absence of a flag is not evidence that no conflict exists.",
  unavailable:
    "The safety check result for this link is not available on this screen. No conclusion is shown.",
} as const;

function entrance(mode: MorphMode) {
  if (mode === "morph") {
    return {
      initial: { opacity: 0 },
      animate: { opacity: 1 },
      transition: { duration: JOINED_IN.duration, delay: JOINED_IN.delay, ease: EASE_OUT },
    };
  }
  if (mode === "crossfade") {
    return { initial: { opacity: 0 }, animate: { opacity: 1 }, transition: { duration: CROSSFADE_S } };
  }
  return { initial: false as const, animate: { opacity: 1 }, transition: { duration: 0 } };
}

/** One golden value with where it came from: a glyph for the eye, the source and record for
 * assistive tech and the pointer. */
function Value({ field, cards, children }: { field: GoldenField; cards: SourceCard[]; children: ReactNode }) {
  const from = `from ${sourceNameFrom(field.crosswalk.sourceSystem, cards)}, record ${field.crosswalk.sourceRecordId}`;
  return (
    <>
      {children}
      <span className="org-from" title={from}>
        <SourceGlyph sourceSystem={field.crosswalk.sourceSystem} />
        <span className="sr-only">, {from}</span>
      </span>
    </>
  );
}

/** The joined record (CONCEPT.md §1): one object, drawn in mulberry, with the notice rising from
 * its seam and the crosswalk tabs hanging under it. Keeps the golden-record hook. */
export function Joined({ entity, cards, flag, mode }: JoinedProps) {
  const golden = entity.golden ?? [];
  const field = (name: string) => golden.find((g) => g.field === name);
  const text = (g: GoldenField | undefined) => (g ? goldenValueText(g.value) : null);
  const given = field("givenName");
  const family = field("familyName");
  const name = [text(given), text(family)].filter(Boolean).join(" ") || "Patient record";
  // Spellings the other sources hold, each with its source: "Also recorded as MesaLópez (Clinic)".
  const alternates = [given, family].flatMap((g) =>
    (g?.alternates ?? [])
      .filter((alt) => goldenValueText(alt.value) !== goldenValueText(g!.value))
      .map((alt) => `${goldenValueText(alt.value)} (${sourceNameFrom(alt.crosswalk.sourceSystem, cards)})`),
  );
  const born = field("birthDate");
  const sex = field("sex");
  const phone = field("phone");
  const address = field("address");
  const zip = field("zip5");
  const holds = holdsLine({
    allergies: golden.filter((g) => g.field === "allergy").length,
    orders: golden.filter((g) => g.field === "activeMedicationOrder").length,
  });
  const constructed = entity.members.some((m) => m.isConstructed);
  return (
    <motion.section
      data-testid="golden-record"
      aria-labelledby="golden-heading"
      className="org-joined on-mulberry"
      {...entrance(mode)}
    >
      {mode === "morph" && (
        <motion.div
          className="org-heal"
          aria-hidden="true"
          style={{ left: HEAL_X }}
          initial={{ opacity: 1 }}
          animate={{ opacity: 0 }}
          transition={{ duration: HEAL.duration, delay: HEAL.delay, ease: EASE_OUT }}
        />
      )}
      {flag.kind === "raised" && (
        <motion.div
          className="org-stem"
          aria-hidden="true"
          style={{ left: HEAL_X, top: STEM.top, height: STEM.height }}
          initial={mode === "morph" ? { opacity: 0 } : false}
          animate={{ opacity: 1 }}
          transition={{ duration: STEM_IN.duration, delay: STEM_IN.delay, ease: EASE_OUT }}
        />
      )}
      <div className="org-g-top">
        <RecordMark joined />
        Patient record · linked
        {constructed && (
          <span className="org-cs2">
            <ConstructedChip />
          </span>
        )}
      </div>
      <h2 id="golden-heading" tabIndex={-1}>
        {name}
      </h2>
      {alternates.length > 0 && <p className="org-alt">Also recorded as {alternates.join("; ")}</p>}
      <dl className="org-g-grid">
        {born && (
          <div>
            <dt>Born</dt>
            <dd className="tabular-nums">
              <Value field={born} cards={cards}>
                {text(born)}
              </Value>
            </dd>
          </div>
        )}
        {sex && (
          <div>
            <dt>Sex</dt>
            <dd>
              <Value field={sex} cards={cards}>
                {sexLabel(text(sex) ?? "")}
              </Value>
            </dd>
          </div>
        )}
        {phone && (
          <div>
            <dt>Phone</dt>
            <dd className="tabular-nums">
              <Value field={phone} cards={cards}>
                {phoneLabel(text(phone) ?? "")}
              </Value>
            </dd>
          </div>
        )}
        {(address || zip) && (
          <div className="org-wide">
            <dt>Address</dt>
            <dd>
              <Value field={address ?? zip!} cards={cards}>
                {[text(address), text(zip)].filter(Boolean).join(", ")}
              </Value>
            </dd>
          </div>
        )}
        {holds && (
          <div>
            <dt>Holds</dt>
            <dd>{holds}</dd>
          </div>
        )}
      </dl>
      {flag.kind === "raised" && <Notice alert={flag.alert} mode={mode} cards={cards} />}
      {(flag.kind === "none" || flag.kind === "unavailable") && (
        <p data-testid="flag-quiet" className="org-quiet">
          <Flag aria-hidden size={16} strokeWidth={1.7} />
          {QUIET_LINES[flag.kind]}
        </p>
      )}
      <Tabs members={entity.members} cards={cards} mode={mode} />
    </motion.section>
  );
}
