"use client";

import { CaseScreen } from "@/components/case/CaseScreen";
import { KioskPane } from "@/components/frontdesk/KioskPane";

/** The Desk grid (CONCEPT.md §3): the kiosk device on the left, the registrar's stage on the
 * right, fixed rows so nothing jumps between states. First push: the slots hold the current
 * kiosk and case screens so every G16 hook stays live on lane/redesign; L2 replaces the kiosk,
 * L3 the Organism, L4 the decision column, and the shell fills in the header, stepper and strip. */
export function DeskScreen() {
  return (
    <div className="desk">
      <section
        aria-label="Patient kiosk"
        className="desk-region rounded-device bg-paper shadow-[0_0_0_1px_var(--hair)] overflow-y-auto"
      >
        <KioskPane />
      </section>
      <section aria-label="Registrar" className="desk-region stage">
        {/* Row 1: eyebrow, title, subtitle (stage header; filled by the shell's second push). */}
        <div className="stage-head" />
        {/* Row 2: the Organism slot and the decision column. */}
        <div className="stage-body">
          <div className="col-span-2 min-w-0 overflow-auto">
            <CaseScreen />
          </div>
        </div>
        {/* Row 3: the Activity strip and the human-review meter. */}
        <div className="strip" />
      </section>
    </div>
  );
}
