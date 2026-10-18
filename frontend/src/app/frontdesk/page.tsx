import { AuditTile } from "@/components/frontdesk/AuditTile";
import { KioskPane } from "@/components/frontdesk/KioskPane";
import { RegistrarPane } from "@/components/frontdesk/RegistrarPane";

export default function FrontDeskPage() {
  return (
    <div className="grid grid-cols-[600px_1fr] gap-4 max-[1100px]:grid-cols-1">
      <h1 className="sr-only">FrontDesk</h1>
      <KioskPane />
      <section aria-labelledby="registrar-label" className="flex min-w-0 flex-col gap-4">
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
