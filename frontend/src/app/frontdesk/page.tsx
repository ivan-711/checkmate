import { AuditTile } from "@/components/frontdesk/AuditTile";
import { KioskPane } from "@/components/frontdesk/KioskPane";
import { RegistrarPane } from "@/components/frontdesk/RegistrarPane";

// Side by side, each pane scrolls on its own (globals.css, .pane-layout). Stacked and portrait,
// the screen is the patient-facing kiosk: the staff pane, which shows the other chart's name,
// date of birth, address and phone, is not displayed. Stacked and landscape (a laptop at 200%
// zoom, a presenter's narrow window) keeps both panes, one under the other.
export default function FrontDeskPage() {
  return (
    <div className="pane-layout grid grid-cols-[600px_1fr] gap-4 max-[1100px]:grid-cols-1">
      <h1 className="sr-only">FrontDesk</h1>
      <div className="pane min-w-0">
        <KioskPane />
      </div>
      <section
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
    </div>
  );
}
