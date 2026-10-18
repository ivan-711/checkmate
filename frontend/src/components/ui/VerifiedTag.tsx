import { BadgeCheck } from "lucide-react";

/** Marks text the system established (a gate result, a rule outcome), as opposed to words the
 * agent wrote. Near-black, small, no colour of its own: the claim is in the word. */
export function VerifiedTag({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded border border-ink-3 px-1.5 text-[16px] font-semibold leading-6 text-ink-1">
      <BadgeCheck aria-hidden size={16} />
      {label}
    </span>
  );
}
