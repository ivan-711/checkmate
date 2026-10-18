"use client";

import { Check, Copy } from "lucide-react";
import { motion, usePresenceData, type Variants } from "motion/react";
import { useMemo, useState, type ReactNode } from "react";
import type { SourceCard } from "@/api/types";
import { ConstructedChip } from "@/components/ui/ConstructedChip";
import { fieldText, type NameDiff } from "./cite";
import { FUSE_SHIFT, LEAN_SHIFT, PUSH_SHIFT, seamPolygon, type Side } from "./geometry";
import { SourceGlyph } from "./Glyph";
import { phoneLabel, sexLabel, sourceFormat, sourceName } from "./labels";
import {
  CROSSFADE_S,
  EASE_FUSE,
  FILL_S,
  FRAGMENT_HOLD_S,
  FUSE_S,
  LEAN_S,
  PUSH,
  TEXT_OUT_S,
  type MorphMode,
} from "./motion";

/** What the Organism passes to every variant: which sheet is open, and how a link should play. */
export interface FragmentCustom {
  sheet: "approve" | "reject" | null;
  mode: MorphMode;
}

/** A node that has no custom of its own changes at once: a missing custom never throws. */
const AT_ONCE: FragmentCustom = { sheet: null, mode: "instant" };

export interface FragmentProps {
  card: SourceCard;
  side: Side;
  /** The live sheet and morph mode; while the fragment exits, AnimatePresence's copy wins. */
  custom?: FragmentCustom;
  /** The one-insertion difference between the two family names, when there is one (touch 6). */
  diff?: NameDiff | null;
}

const COPIED_MS = 1200;

const translate = (px: number) => `translateX(${px}px)`;

/** The fragment's stage variants, keyed by DeskState so the Organism's `animate={stage}` reaches
 * them. "linked" is the exit: the fuse, or a crossfade, or nothing. */
export function fragmentVariants(side: Side): Variants {
  // The ER fragment moves right to meet the Clinic fragment, which moves left.
  const dir = side === "er" ? 1 : -1;
  const rest = { transform: translate(0), transition: { transform: { duration: LEAN_S, ease: EASE_FUSE } } };
  return {
    idle: rest,
    held: rest,
    review: rest,
    confirm: ({ sheet }: FragmentCustom = AT_ONCE) => ({
      transform: translate(dir * (sheet === "reject" ? -LEAN_SHIFT : LEAN_SHIFT)),
      transition: { transform: { duration: LEAN_S, ease: EASE_FUSE } },
    }),
    // A recorded reject pushes them apart, then they settle.
    rejected: {
      transform: [null, translate(-dir * PUSH_SHIFT), translate(0)],
      transition: { transform: { duration: PUSH.duration, times: [...PUSH.times], ease: EASE_FUSE } },
    },
    linked: ({ mode }: FragmentCustom = AT_ONCE) =>
      mode === "morph"
        ? {
            transform: translate(dir * FUSE_SHIFT),
            transition: { transform: { duration: FUSE_S, ease: EASE_FUSE } },
          }
        : { opacity: 0, transition: { duration: mode === "crossfade" ? CROSSFADE_S : 0 } },
  };
}

/** The clipped body: the wave straightens as the fragments fuse. */
export function bodyVariants(side: Side): Variants {
  return {
    linked: ({ mode }: FragmentCustom = AT_ONCE) =>
      mode === "morph"
        ? {
            clipPath: seamPolygon(side, true),
            transition: { clipPath: { duration: FUSE_S, ease: EASE_FUSE } },
          }
        : {},
  };
}

/** The field text sinks away as the fuse begins. */
export const contentVariants: Variants = {
  linked: ({ mode }: FragmentCustom = AT_ONCE) =>
    mode === "morph" ? { opacity: 0, transition: { duration: TEXT_OUT_S } } : {},
};

/** The fill deepens the tint into mulberry, then holds until the joined record is fully in: opacity
 * on an overlay, which the compositor animates, rather than a background-color repaint. */
export const fillVariants: Variants = {
  linked: ({ mode }: FragmentCustom = AT_ONCE) =>
    mode === "morph"
      ? {
          opacity: [0, 1, 1],
          transition: { duration: FRAGMENT_HOLD_S, times: [0, FILL_S / FRAGMENT_HOLD_S, 1], ease: "easeOut" },
        }
      : {},
};

function CopyId({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(id);
    } catch {
      // The clipboard can be unavailable (no permission, no secure context); the id stays readable.
    }
    setCopied(true);
    setTimeout(() => setCopied(false), COPIED_MS);
  }
  return (
    <button type="button" className="org-rid" title="Copy record ID" data-copied={copied} onClick={copy}>
      {id}
      {copied ? <Check aria-hidden size={14} /> : <Copy aria-hidden size={14} />}
      <span className="sr-only">{copied ? ", copied" : ", copy record ID"}</span>
    </button>
  );
}

/** A family name with the one run the other spelling lacks underlined, or a gap where this
 * spelling lacks it. */
function markedName(name: string, side: Side, diff: NameDiff | null | undefined): ReactNode {
  if (!diff) return name;
  const mine = side === "er" ? "a" : "b";
  if (diff.side === mine) {
    return (
      <>
        {name.slice(0, diff.start)}
        <i className="org-d">{name.slice(diff.start, diff.end)}</i>
        {name.slice(diff.end)}
      </>
    );
  }
  return (
    <>
      {name.slice(0, diff.start)}
      <i className="org-gap" aria-hidden="true" />
      {name.slice(diff.start)}
    </>
  );
}

function Row({
  field,
  label,
  children,
  missing,
}: {
  field: string;
  label: string;
  children: ReactNode;
  missing?: boolean;
}) {
  return (
    <div data-field={field}>
      <dt>{label}</dt>
      <dd className={missing ? "org-missing" : undefined}>{children}</dd>
    </div>
  );
}

/** One source record as a fragment of the living record (CONCEPT.md §1): pale, with a wavy seam
 * on the side that faces the other record. Keeps the source-card hooks the acceptance script reads. */
export function Fragment({ card, side, diff, custom = AT_ONCE }: FragmentProps) {
  const { record, normalized } = card;
  // Motion resolves a variant with the node's own custom, so every variant node carries one: the
  // exit's from AnimatePresence (its sheet and mode are current), otherwise the Organism's.
  const live = usePresenceData() as FragmentCustom | undefined;
  const c = live ?? custom;
  const name = sourceName(record.sourceSystem, card.displayLabel);
  const variants = useMemo(() => fragmentVariants(side), [side]);
  const body = useMemo(() => bodyVariants(side), [side]);
  const given = fieldText("given", normalized);
  const family = fieldText("family", normalized);
  const address = fieldText("addr", normalized);
  return (
    <motion.article
      data-testid="source-card"
      data-source-system={record.sourceSystem}
      data-side={side}
      aria-label={`${name} record`}
      className="org-frag"
      variants={variants}
      custom={c}
      exit="linked"
    >
      <motion.div
        className="org-frag-body"
        variants={body}
        custom={c}
        style={{ clipPath: seamPolygon(side, false) }}
      >
        <motion.div className="org-frag-in" variants={contentVariants} custom={c}>
          <header className="org-src">
            <SourceGlyph sourceSystem={record.sourceSystem} />
            <div>
              <b>{name}</b>
              <span>{sourceFormat(record.kind)}</span>
            </div>
          </header>
          <CopyId id={record.sourceLocalId} />
          <h3 className="org-nm">
            <span data-field="given">{given ?? <span className="org-missing">Not given</span>}</span>
            <span data-field="family">
              {family ? markedName(family, side, diff) : <span className="org-missing">Not given</span>}
            </span>
          </h3>
          <dl>
            <Row field="dob" label="Born" missing={!normalized.birthDate}>
              {normalized.birthDate ? (
                <span className="tabular-nums">{normalized.birthDate}</span>
              ) : (
                "Not given"
              )}
            </Row>
            <Row field="sex" label="Sex" missing={!normalized.sex}>
              {normalized.sex ? sexLabel(normalized.sex) : "Not given"}
            </Row>
            <Row field="addr" label="Address" missing={!address}>
              {address ?? "Not given"}
            </Row>
            <Row field="phone" label="Phone" missing={!normalized.phoneE164}>
              {normalized.phoneE164 ? (
                <span className="tabular-nums">{phoneLabel(normalized.phoneE164)}</span>
              ) : (
                "Not given"
              )}
            </Row>
          </dl>
        </motion.div>
        <motion.div className="org-fill" aria-hidden="true" variants={fillVariants} custom={c} />
      </motion.div>
      {/* Outside the clipped body, so the chip's explanation is never cut by the seam. */}
      {record.isConstructed && (
        <motion.div className="org-cs" variants={contentVariants} custom={c}>
          <ConstructedChip />
        </motion.div>
      )}
    </motion.article>
  );
}
