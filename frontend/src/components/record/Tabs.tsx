"use client";

import { motion } from "motion/react";
import type { EntityMember, SourceCard } from "@/api/types";
import { TABS } from "./geometry";
import { SourceGlyph } from "./Glyph";
import { sourceNameFrom } from "./labels";
import { CROSSFADE_S, EASE_OUT, TABS_IN, type MorphMode } from "./motion";

export interface TabsProps {
  members: EntityMember[];
  cards: SourceCard[];
  mode: MorphMode;
}

const translate = (px: number) => `translateY(${px}px)`;

function entrance(mode: MorphMode) {
  if (mode === "morph") {
    return {
      initial: { opacity: 0, transform: translate(-TABS.drop) },
      animate: { opacity: 1, transform: translate(0) },
      transition: {
        opacity: { duration: TABS_IN.opacity, delay: TABS_IN.delay, ease: EASE_OUT },
        transform: { duration: TABS_IN.move, delay: TABS_IN.delay, ease: EASE_OUT },
      },
    };
  }
  if (mode === "crossfade") {
    return { initial: { opacity: 0 }, animate: { opacity: 1 }, transition: { duration: CROSSFADE_S } };
  }
  return { initial: false as const, animate: { opacity: 1 }, transition: { duration: 0 } };
}

/** The crosswalk: one tab per source record, hanging from the record's bottom edge (CONCEPT.md §4,
 * Shape). Each names its source and the record id it holds. */
export function Tabs({ members, cards, mode }: TabsProps) {
  const localId = (member: EntityMember) =>
    cards.find((c) => c.record.id === member.sourceRecordId)?.record.sourceLocalId ?? member.sourceRecordId;
  return (
    <motion.div className="org-tabs" {...entrance(mode)}>
      {members.map((member) => {
        const id = localId(member);
        return (
          <span
            key={member.sourceRecordId}
            data-testid="crosswalk-chip"
            data-source-system={member.sourceSystem}
            title={`Source record ${id}`}
            className="org-tab"
          >
            <SourceGlyph sourceSystem={member.sourceSystem} />
            {sourceNameFrom(member.sourceSystem, cards)}
            <code>{id}</code>
            <span className="sr-only">, source record {id}</span>
          </span>
        );
      })}
    </motion.div>
  );
}
