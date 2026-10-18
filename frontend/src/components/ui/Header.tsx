"use client";

import Link from "next/link";
import { useEffect } from "react";
import { CommandBar } from "@/components/desk/CommandBar";
import { useDesk } from "@/components/desk/DeskContext";
import { StoryStepper } from "@/components/desk/StoryStepper";
import { useDataSource } from "@/data/DataSourceProvider";
import { Mark } from "./Mark";
import { ModeBadge } from "./ModeBadge";
import { ProvisionalBadge } from "./ProvisionalBadge";
import { ResetButton, useResetDemo } from "./ResetButton";

/** True while the key press belongs to a text control, so single-letter shortcuts stay out of it. */
export function typingInField(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || el.isContentEditable;
}

/** The top bar (CONCEPT.md §3): the mark and wordmark, the synthetic-data line, the story
 * stepper, then the mode badge, Commands ⌘K and Reset demo ⇧R. No tabs: the queue opens from ⌘K. */
export function Header() {
  const { mode } = useDataSource();
  const { desk, commandsOpen, setCommandsOpen } = useDesk();
  const { reset } = useResetDemo();

  // ⌘K and ⇧R work on every route; the Desk adds its own keys (DeskScreen).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCommandsOpen(!commandsOpen);
        return;
      }
      if (commandsOpen || typingInField(e.target)) return;
      if (e.shiftKey && e.key === "R" && !e.metaKey && !e.ctrlKey && !e.altKey) reset();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [commandsOpen, setCommandsOpen, reset]);

  return (
    <header className="flex h-[var(--bar-h)] items-center gap-6 px-7">
      <Link
        href="/"
        className="flex items-center gap-2.5 font-display text-[22px] font-[650] tracking-[-0.02em] text-ink"
      >
        <span className="text-mulberry">
          <Mark joined={desk === "linked"} />
        </span>
        CheckMate
      </Link>
      <p className="flex items-center gap-2 text-[14px] text-ink-2">
        <span aria-hidden="true" className="block h-[7px] w-[7px] rounded-full border-[1.5px] border-ink-2" />
        Synthetic data. Not for clinical use.
      </p>
      <div className="flex min-w-0 flex-1 justify-center">
        <StoryStepper />
      </div>
      <div className="flex items-center gap-2.5">
        <ProvisionalBadge />
        <ModeBadge mode={mode} />
        <button
          type="button"
          onClick={() => setCommandsOpen(true)}
          aria-label="Commands"
          aria-haspopup="dialog"
          className="inline-flex h-9 items-center rounded-[10px] border border-hair px-3 text-[14px] text-ink-2 hover:bg-ink/5"
        >
          <span className="compact-hidden">Commands</span>
          <kbd aria-hidden="true" className="compact-nomargin">
            ⌘K
          </kbd>
        </button>
        <ResetButton />
      </div>
      <CommandBar />
    </header>
  );
}
