import { describe, expect, it } from "vitest";
import {
  CLINIC_LEFT,
  FRAG_W,
  FUSE_SHIFT,
  JOINED_LEFT,
  JOINED_W,
  ORGANISM_H,
  ORGANISM_W,
  SEAM_A,
  SEAM_X,
  seamOffset,
  seamPoints,
  seamPolygon,
  threadEnds,
} from "./geometry";

describe("the organism's geometry", () => {
  it("fuses the two fragments at the centre line: both shift by the same amount to meet there", () => {
    expect(FRAG_W + FUSE_SHIFT).toBe(ORGANISM_W / 2);
    expect(CLINIC_LEFT - FUSE_SHIFT).toBe(ORGANISM_W / 2);
    expect(SEAM_X).toBe(ORGANISM_W / 2);
  });

  it("draws the joined record exactly where the fused fragments end up", () => {
    expect(JOINED_LEFT).toBe(FUSE_SHIFT);
    expect(JOINED_W).toBe(2 * FRAG_W);
    expect(JOINED_LEFT + JOINED_W).toBe(ORGANISM_W - FUSE_SHIFT);
  });
});

describe("seamOffset", () => {
  it("starts flush, peaks at a third of the height and ends at full amplitude", () => {
    expect(seamOffset(0)).toBeCloseTo(0);
    expect(seamOffset(ORGANISM_H / 3)).toBeCloseTo(SEAM_A);
    expect(seamOffset(ORGANISM_H)).toBeCloseTo(SEAM_A);
  });

  it("never cuts deeper than the amplitude", () => {
    for (let y = 0; y <= ORGANISM_H; y += 7) {
      expect(seamOffset(y)).toBeGreaterThanOrEqual(0);
      expect(seamOffset(y)).toBeLessThanOrEqual(SEAM_A + 1e-9);
    }
  });
});

describe("seamPoints", () => {
  it("keeps the same point count wave and flat, so the clip-path can interpolate", () => {
    for (const side of ["er", "cl"] as const) {
      expect(seamPoints(side, false)).toHaveLength(seamPoints(side, true).length);
      expect(seamPoints(side, false).length).toBeGreaterThan(20);
    }
  });

  it("cuts the ER fragment's right edge inward by the wave, and straightens it when flat", () => {
    const wave = seamPoints("er", false).slice(1, -1); // the seam edge, between the two left corners
    for (const [x] of wave) {
      expect(x).toBeGreaterThanOrEqual(FRAG_W - SEAM_A);
      expect(x).toBeLessThanOrEqual(FRAG_W);
    }
    for (const [x] of seamPoints("er", true).slice(1, -1)) expect(x).toBe(FRAG_W);
  });

  it("cuts the Clinic fragment's left edge with the complementary wave, so the gap stays constant", () => {
    const er = seamPoints("er", false).slice(1, -1);
    const cl = seamPoints("cl", false).slice(0, -2);
    expect(cl).toHaveLength(er.length);
    const gaps = er.map(([erX, y], i) => {
      const [clX, clY] = cl[i];
      expect(clY).toBeCloseTo(y);
      return CLINIC_LEFT + clX - erX;
    });
    for (const gap of gaps) expect(gap).toBeCloseTo(gaps[0]);
    for (const [x] of seamPoints("cl", true).slice(0, -2)) expect(x).toBe(0);
  });
});

describe("seamPolygon", () => {
  it("writes a CSS polygon in px", () => {
    expect(seamPolygon("er", false)).toMatch(/^polygon\((-?[\d.]+px -?[\d.]+px)(, ?-?[\d.]+px -?[\d.]+px)+\)$/);
    expect(seamPolygon("cl", true)).toMatch(/^polygon\(/);
  });
});

describe("threadEnds", () => {
  it("runs a thread from just inside the ER seam to just inside the Clinic seam at that height", () => {
    const y = 180;
    const { x1, x2 } = threadEnds(y);
    expect(x1).toBeLessThan(FRAG_W - seamOffset(y));
    expect(x1).toBeGreaterThan(FRAG_W - seamOffset(y) - 4);
    expect(x2).toBeGreaterThan(CLINIC_LEFT + SEAM_A - seamOffset(y));
    expect(x2).toBeLessThan(CLINIC_LEFT + SEAM_A - seamOffset(y) + 4);
    expect(x1).toBeLessThan(SEAM_X);
    expect(x2).toBeGreaterThan(SEAM_X);
  });
});
