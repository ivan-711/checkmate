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
    <header className="app-header">
      {/* The wordmark with the synthetic-data sentence under it: always visible, never clipped,
          so the stepper keeps its room at 1280 wide. */}
      <div className="header-brand flex shrink-0 items-center gap-2.5">
        <span className="text-mulberry">
          <Mark size={26} state={desk === "linked" ? "closed" : "open"} />
        </span>
        <div>
          <Link
            href="/"
            className="block font-display text-[22px] font-[650] leading-[1.05] tracking-[-0.02em] text-ink"
          >
            CheckMate
          </Link>
          <p
            data-testid="synthetic-notice"
            className="mt-0.5 flex items-center gap-1.5 whitespace-nowrap text-[13px] leading-[1.2] text-ink-2"
          >
            <span
              aria-hidden="true"
              className="block h-[7px] w-[7px] rounded-full border-[1.5px] border-ink-2"
            />
            Synthetic data. Not for clinical use.
          </p>
        </div>
      </div>
      <div className="header-story flex min-w-0 flex-1 justify-center">
        <StoryStepper />
      </div>
      <div className="header-actions flex shrink-0 items-center gap-2.5">
        <span className="header-provisional contents">
          <ProvisionalBadge />
        </span>
        <span className="header-mode contents">
          <ModeBadge mode={mode} />
        </span>
        <button
          type="button"
          onClick={() => setCommandsOpen(true)}
          aria-label="Commands, shortcut ⌘K"
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
