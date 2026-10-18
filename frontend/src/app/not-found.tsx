import Link from "next/link";
import { Mark } from "@/components/ui/Mark";

/** 404 (CONCEPT.md §3): the mark with its halves apart, and the way back to the Desk. */
export default function NotFound() {
  return (
    <div className="flex h-[calc(100dvh-var(--bar-h))] flex-col items-center justify-center gap-5 text-center">
      <span className="text-mulberry">
        <Mark apart size={84} />
      </span>
      <h1 className="font-display text-[44px] font-bold leading-[1.02] tracking-[-0.03em]">Nothing here</h1>
      <p className="max-w-[40ch] text-[18px] text-ink-2">
        This page does not exist. The demo lives on the Desk.
      </p>
      <Link
        href="/"
        className="inline-flex h-[52px] items-center rounded-control bg-ink px-5 text-[17px] font-semibold text-paper hover:bg-black"
      >
        Back to the Desk
      </Link>
    </div>
  );
}
