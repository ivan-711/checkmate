"use client";

import { useEffect, useRef } from "react";
import { AuditTile } from "./AuditTile";
import { useHandoffPairs, useIntakeSession } from "./intake";
import { RegistrarPane } from "./RegistrarPane";

/** The registrar's side of FrontDesk. Side by side it is its own scroll pane (globals.css, .pane):
 * a new held check-in brings its first pair's heading to the top of the pane, and focus stays in
 * the kiosk. Stacked and portrait it is not displayed: that screen is the patient-facing kiosk. */
export function StaffPane() {
  const pane = useRef<HTMLElement>(null);
  const first = useIntakeSession()?.registration.handoffPairIds?.[0];
  const firstLoaded = useHandoffPairs()[0]?.isSuccess ?? false;
  useEffect(() => {
    const box = pane.current;
    // The id RegistrarPane gives the first held pair's heading, rendered once that pair has loaded.
    const heading = box?.querySelector<HTMLElement>("#held-heading-0");
    if (!box || !first || !firstLoaded || !heading) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // The pane itself scrolls, not scrollIntoView: stacked, that would move the page off the kiosk.
    const top = box.scrollTop + heading.getBoundingClientRect().top - box.getBoundingClientRect().top;
    box.scrollTo({ top, behavior: reduce ? "auto" : "smooth" });
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
