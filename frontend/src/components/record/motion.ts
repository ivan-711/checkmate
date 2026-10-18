import type { DeskState } from "@/lib/desk";

/* The one orchestrated moment (CONCEPT.md §4), timed in seconds from R, the render in which the
 * server-confirmed link is on screen. Motion drives every value below so the stage never animates
 * on load, Reset, Undo or a tab return (motion-polish.md): the morph plays only when the approval
 * happened on this stage, and under reduced motion it is a crossfade. */

export type MorphMode = "morph" | "crossfade" | "instant";

export const EASE_OUT = [0.16, 1, 0.3, 1] as const;
export const EASE_FUSE = [0.7, 0, 0.2, 1] as const;
export const EASE_SPRING = [0.34, 1.36, 0.64, 1] as const;

/** The fragments slide together and the seam straightens. */
export const FUSE_S = 0.72;
/** The tint deepens into mulberry. */
export const FILL_S = 0.52;
/** The field text sinks out of the fragments. */
export const TEXT_OUT_S = 0.22;
/** The fused fragments stay under the record until it is fully in, so no background shows. */
export const FRAGMENT_HOLD_S = 0.95;
export const JOINED_IN = { delay: 0.64, duration: 0.26 } as const;
export const HEAL = { delay: 0.9, duration: 0.9 } as const;
export const TABS_IN = { delay: 0.9, opacity: 0.3, move: 0.42 } as const;
export const NOTICE_IN = { delay: 1.18, duration: 0.52, opacity: 0.16 } as const;
export const STEM_IN = { delay: 1.3, duration: 0.4 } as const;
/** The notice slides up when its Details fold opens. */
export const NOTICE_EXPAND_S = 0.32;
/** Every reduced-motion fallback, and the crossfade that stands in for the morph. */
export const CROSSFADE_S = 0.15;
/** The threads draw with a stagger of 40 to 280 ms when Resolve lands (touch 5). */
export const THREAD = { draw: 0.52, node: 0.36, firstDelay: 0.04, stagger: 0.08 } as const;
/** The lean-in while the confirm sheet is open, and the push-apart on a reject. */
export const LEAN_S = 0.72;
export const PUSH = { duration: 1.0, times: [0, 0.4, 1] } as const;
/** Focus moves to the notice's heading once it has risen. */
export const FOCUS_AFTER_MORPH_MS = Math.round((NOTICE_IN.delay + NOTICE_IN.duration) * 1000);

const DECIDING: readonly DeskState[] = ["review", "confirm"];

interface StageChange {
  from: DeskState | undefined;
  to: DeskState;
}

/** The morph plays only for a link approved on this stage (review or confirm into linked). A page
 * that loads linked, an Undo reset, or any other change renders at rest. */
export function morphMode({ from, to, reduced }: StageChange & { reduced: boolean }): MorphMode {
  if (to !== "linked" || !from || !DECIDING.includes(from)) return "instant";
  return reduced ? "crossfade" : "morph";
}

/** The threads draw when Resolve lands on this stage; between review and confirm they hold still. */
export function threadsArmed({ from, to }: StageChange): boolean {
  return DECIDING.includes(to) && !!from && !DECIDING.includes(from);
}
