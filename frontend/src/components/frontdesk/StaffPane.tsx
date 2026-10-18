"use client";

import { useEffect, useRef } from "react";
import { AuditTile } from "./AuditTile";
import { useHandoffPairs, useIntakeSession } from "./intake";
import { RegistrarPane } from "./RegistrarPane";

/** The registrar's side of FrontDesk. Side by side it is its own scroll pane (globals.css, .pane):
 * a new held check-in scrolls it so the first pair's Approve is in view, with the pair's heading at
 * the top when both fit, and focus stays in the kiosk. Stacked and portrait it is not displayed:
 * that screen is the patient-facing kiosk. */
// The room kept under Approve, so its focus ring is not cut by the pane's edge.
const EDGE_GAP_PX = 16;

export function StaffPane() {
  const pane = useRef<HTMLElement>(null);
  const first = useIntakeSession()?.registration.handoffPairIds?.[0];
  const firstLoaded = useHandoffPairs()[0]?.isSuccess ?? false;
  useEffect(() => {
    const box = pane.current;
    // The id RegistrarPane gives the first held pair's heading, rendered once that pair has loaded.
    const heading = box?.querySelector<HTMLElement>("#held-heading-0");
    if (!box || !first || !firstLoaded || !heading) return;
    const approve = heading.closest("article")?.querySelector<HTMLElement>('[data-testid="approve-button"]');
    const view = box.getBoundingClientRect();
    const headingAtTop = box.scrollTop + heading.getBoundingClientRect().top - view.top;
    const approveAtBottom = approve
      ? box.scrollTop + approve.getBoundingClientRect().bottom - view.bottom + EDGE_GAP_PX
      : 0;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // The pane itself scrolls, not scrollIntoView: stacked, that would move the page off the kiosk.
    box.scrollTo({ top: Math.max(headingAtTop, approveAtBottom), behavior: reduce ? "auto" : "smooth" });
  }, [first, firstLoaded]);

  return (
    <section
      ref={pane}
      aria-labelledby="registrar-label"
      className="pane flex min-w-0 flex-col gap-4 max-[1100px]:portrait:hidden"
    >
      <h2 id="registrar-label" className="text-[16px] font-semibold uppercase tracking-wider text-ink-3">
        Registrar workspace · staff view
      </h2>
      <RegistrarPane />
      <div className="mt-auto">
        <AuditTile />
      </div>
    </section>
  );
}
