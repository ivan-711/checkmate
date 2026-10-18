import { KioskPane } from "@/components/frontdesk/KioskPane";

// The kiosk on its own (CONCEPT.md §3): the same component as the Desk's left region, full
// screen for a second display or a tablet.
export default function KioskPage() {
  return (
    <div className="grid h-[calc(100dvh-var(--bar-h))] grid-cols-[min(640px,100%)] justify-center px-6 pb-5 pt-1">
      <section
        aria-label="Patient kiosk"
        className="desk-region overflow-hidden rounded-device bg-paper shadow-[0_0_0_1px_var(--hair),0_24px_60px_-30px_var(--scrim)]"
      >
        <KioskPane />
      </section>
    </div>
  );
}
