"use client";

import { motion } from "motion/react";
import { useLayoutEffect, useState, type RefObject } from "react";
import type { CiteField } from "@/lib/desk";
import type { Mark } from "./cite";
import { ORGANISM_H, ORGANISM_W, SEAM_X, threadEnds } from "./geometry";
import { CROSSFADE_S, EASE_OUT, EASE_SPRING, THREAD } from "./motion";

export interface ThreadsProps {
  /** The cited fields, strongest first: the first thread draws first. */
  fields: CiteField[];
  marks: Partial<Record<CiteField, Mark>>;
  /** The Organism's box: the rows are measured inside it. */
  host: RefObject<HTMLDivElement | null>;
  /** True when Resolve just landed here: the threads draw in. Otherwise they are simply there. */
  armed: boolean;
}

/** The vertical centre of each cited row in the ER fragment, in the Organism's pixels. Offsets,
 * not client rects, so the lean-in transform never moves the threads. */
function measure(host: HTMLElement | null, fields: CiteField[]): Partial<Record<CiteField, number>> {
  const ys: Partial<Record<CiteField, number>> = {};
  if (!host) return ys;
  for (const field of fields) {
    const row = host.querySelector<HTMLElement>(`[data-side="er"] [data-field="${field}"]`);
    if (row) ys[field] = row.offsetTop + row.offsetHeight / 2;
  }
  return ys;
}

/** One thread per cited field, seam edge to seam edge, with its node on the centre line (touch 5).
 * Hover-to-cite lights a thread through the Organism's data-cite (organism.css). */
export function Threads({ fields, marks, host, armed }: ThreadsProps) {
  const [ys, setYs] = useState<Partial<Record<CiteField, number>>>({});
  useLayoutEffect(() => {
    setYs(measure(host.current, fields));
  }, [host, fields]);

  const delay = (i: number) => THREAD.firstDelay + i * THREAD.stagger;
  return (
    <motion.div
      className="org-threads-layer"
      aria-hidden="true"
      initial={false}
      exit={{ opacity: 0, transition: { duration: CROSSFADE_S } }}
    >
      <svg className="org-threads" width={ORGANISM_W} height={ORGANISM_H}>
        {fields.map((field, i) => {
          const y = ys[field] ?? 0;
          const { x1, x2 } = threadEnds(y);
          return (
            <motion.line
              key={field}
              data-k={field}
              x1={x1}
              x2={x2}
              y1={y}
              y2={y}
              initial={armed ? { pathLength: 0, opacity: 0 } : false}
              animate={{ pathLength: 1, opacity: 1 }}
              transition={{
                pathLength: { duration: THREAD.draw, ease: EASE_OUT, delay: delay(i) },
                opacity: { duration: 0.2, delay: delay(i) },
              }}
            />
          );
        })}
      </svg>
      {fields.map((field, i) => (
        <motion.div
          key={field}
          className="org-node"
          data-k={field}
          style={{ left: SEAM_X, top: ys[field] ?? 0 }}
          initial={armed ? { transform: "scale(0.4)", opacity: 0 } : false}
          animate={{ transform: "scale(1)", opacity: 1 }}
          transition={{
            transform: { duration: THREAD.node, ease: EASE_SPRING, delay: delay(i) },
            opacity: { duration: 0.2, delay: delay(i) },
          }}
        >
          {marks[field]}
        </motion.div>
      ))}
    </motion.div>
  );
}
