/* The Organism's drawing (CONCEPT.md §3, §4): a 600x520 box holding two 272 px fragments with a
 * wavy seam between them. Every number below is in that box's own pixels; the Desk scales the box
 * for the compact layer (globals.css, .organism-scale), so nothing here depends on the viewport. */

export const ORGANISM_W = 600;
export const ORGANISM_H = 520;
export const FRAG_W = 272;
/** The Clinic fragment's left edge while the records are apart. */
export const CLINIC_LEFT = ORGANISM_W - FRAG_W;
/** How far each fragment travels to meet the other at the centre line. */
export const FUSE_SHIFT = (ORGANISM_W - 2 * FRAG_W) / 2;
export const JOINED_LEFT = FUSE_SHIFT;
export const JOINED_W = 2 * FRAG_W;
/** The seam's x once the fragments have fused; the thread nodes sit on it. */
export const SEAM_X = ORGANISM_W / 2;
/** The wave's depth. */
export const SEAM_A = 12;
const SEAM_STEPS = 26;
const SEAM_CYCLES = 1.5;
/** The fragments drift toward each other while the confirm sheet is open (touch 9). */
export const LEAN_SHIFT = 10;
/** The reject sheet, then a recorded reject, push them apart. */
export const PUSH_SHIFT = 14;
/** A thread starts and ends just inside each fragment's seam edge. */
const THREAD_INSET = 2;

/** The heal line and the stem sit on the seam, measured from the joined record's left edge. */
export const HEAL_X = SEAM_X - JOINED_LEFT - 1;
export const STEM = { top: 292, height: 14 } as const;
/** The notice rises out of the seam: its resting place, how far it rises, its corner radius. */
export const NOTICE = { left: 72, width: 456, top: 306, rise: 34, radius: 22 } as const;
/** How far the notice slides up to make room when its Details fold opens. */
export const NOTICE_EXPAND_RISE = 190;
/** The crosswalk tabs hang under the record's bottom edge, from the organism's left. */
export const TABS = { left: 52, drop: 12 } as const;

export type Side = "er" | "cl";

/** How deep the wave cuts at height y: flush at the top, full depth a third of the way down. */
export function seamOffset(y: number): number {
  return SEAM_A * (0.5 - 0.5 * Math.cos((2 * Math.PI * SEAM_CYCLES * y) / ORGANISM_H));
}

/** The clip polygon of one fragment, in its own pixels: the ER fragment keeps its left edge and
 * its right edge waves; the Clinic fragment is the complement. Flat straightens the seam. Both
 * shapes carry the same point count, so the browser interpolates one into the other. */
export function seamPoints(side: Side, flat: boolean): [number, number][] {
  const points: [number, number][] = [];
  if (side === "er") {
    points.push([0, 0]);
    for (let i = 0; i <= SEAM_STEPS; i++) {
      const y = (ORGANISM_H * i) / SEAM_STEPS;
      points.push([flat ? FRAG_W : FRAG_W - seamOffset(y), y]);
    }
    points.push([0, ORGANISM_H]);
  } else {
    for (let i = 0; i <= SEAM_STEPS; i++) {
      const y = (ORGANISM_H * i) / SEAM_STEPS;
      points.push([flat ? 0 : SEAM_A - seamOffset(y), y]);
    }
    points.push([FRAG_W, ORGANISM_H], [FRAG_W, 0]);
  }
  return points;
}

export function seamPolygon(side: Side, flat: boolean): string {
  const px = (n: number) => `${n.toFixed(1)}px`;
  return `polygon(${seamPoints(side, flat)
    .map(([x, y]) => `${px(x)} ${px(y)}`)
    .join(", ")})`;
}

/** Where a thread at height y starts (inside the ER seam) and ends (inside the Clinic seam). */
export function threadEnds(y: number): { x1: number; x2: number } {
  const offset = seamOffset(y);
  return { x1: FRAG_W - offset - THREAD_INSET, x2: CLINIC_LEFT + SEAM_A - offset + THREAD_INSET };
}
