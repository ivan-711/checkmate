"use client";

import { STORY_STEPS, currentStep, stepStatus } from "@/lib/desk";
import { useDesk } from "./DeskContext";

const STATUS_RING = {
  done: "bg-ink border-ink text-paper",
  current: "border-ink text-ink",
  upcoming: "border-hair-strong text-ink-3",
} as const;

const STATUS_LABEL = {
  done: "font-medium text-ink-2",
  current: "font-semibold text-ink",
  upcoming: "font-medium text-ink-3",
} as const;

/** The story in five steps (BUILD-SPEC decision 3), driven by the Desk state: the current step
 * is marked, the ones before it are done. It says where the demo is from across the room. */
export function StoryStepper() {
  const { desk, kiosk, facts } = useDesk();
  const current = currentStep(desk, kiosk, facts.flagRaised);
  return (
    <ol data-testid="story-stepper" aria-label="Story" className="flex items-center gap-1 text-[14px]">
      {STORY_STEPS.map((step, i) => {
        const status = stepStatus(step.id, current);
        return (
          <li
            key={step.id}
            data-step={step.id}
            data-status={status}
            aria-current={status === "current" ? "step" : undefined}
            className="flex items-center gap-2"
          >
            {i > 0 && <span aria-hidden="true" className="mr-1 h-px w-3 bg-hair-strong" />}
            <span
              aria-hidden="true"
              className={`grid h-[18px] w-[18px] place-items-center rounded-full border-[1.5px] ${STATUS_RING[status]}`}
            >
              {status === "done" && (
                <svg viewBox="0 0 24 24" width="11" height="11">
                  <path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
              {status === "current" && <span className="block h-2 w-2 rounded-full bg-ink" />}
            </span>
            <span className={STATUS_LABEL[status]}>{step.label}</span>
            <span className="sr-only">{status === "done" ? ", done" : status === "current" ? ", current step" : ""}</span>
          </li>
        );
      })}
    </ol>
  );
}
