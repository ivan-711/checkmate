import type { Band, CandidatePairDetail, ThresholdSet } from "@/api/types";

/** The orbit's drawing space ("Why the gate held her", CONCEPT §3). Rings are concentric around the
 * kiosk check-in; a chart sits in the ring of the band the API decided for its hand-off pair. */
export const ORBIT = { width: 280, height: 214, cx: 140, cy: 107 } as const;

/** Outer radius of each band's ring. The REVIEW ring is the gate: inside it no new chart opens. */
export const BAND_RINGS = { AUTO_LINK: 36, REVIEW: 70, KEEP_SEPARATE: 102 } as const satisfies Record<
  Band,
  number
>;
const RING_INNER = { AUTO_LINK: 0, REVIEW: BAND_RINGS.AUTO_LINK, KEEP_SEPARATE: BAND_RINGS.REVIEW } as const;
/** Room kept between a chart mark (radius 12.5) and the ring lines, and around the kiosk at the centre. */
const MARK_MARGIN = 10;
const CENTRE_CLEARANCE = 12;
/** Charts spread across the lower half so their labels never sit on the ring captions at the top. */
const ANGLE_FROM = 30;
const ANGLE_TO = 150;
const GATE_BANDS: ReadonlySet<Band> = new Set(["AUTO_LINK", "REVIEW"]);

export function ringForBand(band: Band): number {
  return BAND_RINGS[band];
}

export interface OrbitChart {
  pairId: string;
  band: Band;
  sourceSystem: string;
  label: string;
  /** The display probability, two decimals, as the rail shows it. */
  p: string;
  radius: number;
  /** Degrees, clockwise from the right, SVG convention. */
  angle: number;
  x: number;
  y: number;
}

export interface OrbitPlacement {
  charts: OrbitChart[];
  /** Charts in REVIEW or AUTO_LINK: the ones that make the gate hold the check-in. */
  insideGate: number;
  /** The raw-score line the gate ring stands for (c_low) and the auto-link line (c_high). */
  gateAt: number;
  autoAt: number;
}

const clamp01 = (t: number) => Math.max(0, Math.min(1, t));

/** Where in its ring a chart sits: nearer the centre the stronger its raw score, but never past
 * the ring lines. The band comes from the decision; the thresholds only shade the position. */
function radiusFor(band: Band, logit: number, { cLow, cHigh }: ThresholdSet): number {
  const width = Math.max(cHigh - cLow, 1);
  const outer = BAND_RINGS[band] - MARK_MARGIN;
  const inner = band === "AUTO_LINK" ? CENTRE_CLEARANCE : RING_INNER[band] + MARK_MARGIN;
  const closeness =
    band === "AUTO_LINK"
      ? clamp01((logit - cHigh) / width)
      : band === "REVIEW"
        ? clamp01((logit - cLow) / width)
        : 1 - clamp01((cLow - logit) / width);
  return outer - closeness * (outer - inner);
}

export function orbitPlacement(
  pairs: CandidatePairDetail[],
  thresholds: ThresholdSet,
  intakeRecordId: string,
): OrbitPlacement {
  const step = pairs.length > 1 ? (ANGLE_TO - ANGLE_FROM) / (pairs.length - 1) : 0;
  const charts = pairs.map((detail, i) => {
    const { pair, recordA, recordB } = detail;
    const other = pair.recordAId === intakeRecordId ? recordB : recordA;
    const { band, logit, p } = pair.decision;
    const radius = radiusFor(band, logit, thresholds);
    const angle = ANGLE_FROM + i * step;
    const rad = (angle * Math.PI) / 180;
    return {
      pairId: pair.id,
      band,
      sourceSystem: other.record.sourceSystem,
      label: other.displayLabel,
      p: p.toFixed(2),
      radius,
      angle,
      x: ORBIT.cx + radius * Math.cos(rad),
      y: ORBIT.cy + radius * Math.sin(rad),
    };
  });
  return {
    charts,
    insideGate: charts.filter((c) => GATE_BANDS.has(c.band)).length,
    gateAt: thresholds.cLow,
    autoAt: thresholds.cHigh,
  };
}
