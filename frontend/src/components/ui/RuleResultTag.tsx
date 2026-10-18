import { BadgeCheck } from "lucide-react";

/** Marks a rule's outcome (the gate's decision, the safety rule's flag), as opposed to words the
 * agent wrote. Near-black, small, no colour of its own: the claim is in the word. */
export function RuleResultTag({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded border border-ink-3 px-1.5 text-[16px] font-semibold leading-6 text-ink-1">
      <BadgeCheck aria-hidden size={16} />
      {label}
    </span>
  );
}
