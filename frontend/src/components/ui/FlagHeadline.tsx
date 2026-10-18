import type { SafetyAlert } from "@/api/types";
import { sourceSystemLabel } from "@/components/frontdesk/copy";
import { flagFacts } from "@/lib/flagHeadline";

function SourcePill({ source }: { source: SafetyAlert["allergyRef"] }) {
  return (
    <span
      data-testid="flag-source-pill"
      title={`Source record ${source.resourceId}`}
      className="whitespace-nowrap rounded border border-border-strong bg-surface px-2 align-middle text-[14px] font-medium text-ink-2"
    >
      <span className="sr-only">from </span>
      {sourceSystemLabel(source.sourceSystem)}
    </span>
  );
}

/** The flag's one line, each fact followed by a pill naming the source record it came from. One
 * component for the Case flag card and the registrar pane, so both read the same. */
export function FlagHeadline({ alert, testId }: { alert: SafetyAlert; testId: string }) {
  const { allergy, order } = flagFacts(alert);
  return (
    <p data-testid={testId} className="text-[18px] font-semibold leading-relaxed">
      {allergy} <SourcePill source={alert.allergyRef} /> · {order} <SourcePill source={alert.orderRef} />
    </p>
  );
}
