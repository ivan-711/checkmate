"use client";

import { useIsMutating, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import type { CandidatePairDetail, ReasonCode, ReviewRequest, ReviewResponse } from "@/api/types";
import { useDeskAction } from "@/components/desk/DeskContext";
import { HANDOFF_KEY } from "@/components/frontdesk/intake";
import { RESOLVE_KEY, SESSION_CHANGE_KEY } from "@/components/ui/ResetButton";
import { useDataSource } from "@/data/DataSourceProvider";
import { scenario } from "@/data/scenario";
import type { Sheet } from "@/lib/desk";
import {
  attachablePair,
  planReviews,
  reviewable,
  runReviews,
  type ReviewKeys,
  type ReviewRun,
} from "./reviewPlan";

// Fixture names, recorded as a label on the decision; not an authenticated identity.
const REGISTRARS = scenario.registrarLabels;
const NOTE_MAX = 500;
// The kiosk's own record; the attach row names the chart it matched, never the kiosk.
const KIOSK_SYSTEM = "AGENT_INTAKE";

export const REASONS: Record<ReasonCode, string> = {
  INSUFFICIENT_EVIDENCE: "Not enough evidence",
  DIFFERENT_PERSON: "Different person",
};

const COPY = {
  approve: {
    eyebrow: "Approve",
    title: "Link these two records?",
    lead: "They become one record, saved under your name.",
    confirm: "Confirm link",
    pending: "Linking…",
    form: "Approve this link",
  },
  reject: {
    eyebrow: "Reject",
    title: "Keep these records apart?",
    lead: "Nothing is linked. The reason is saved with your name.",
    confirm: "Confirm reject",
    pending: "Rejecting…",
    form: "Reject this link",
  },
} as const;

const PRIMARY_BUTTON =
  "flex h-[52px] w-full items-center justify-center gap-2 rounded-control bg-mulberry text-[17px] font-semibold text-paper hover:bg-mulberry-deep disabled:bg-hair disabled:text-ink-3";
const LINE_BUTTON =
  "flex h-[46px] w-full items-center justify-center gap-2 rounded-control text-[17px] font-semibold text-ink shadow-[inset_0_0_0_1.5px_var(--ink)] hover:bg-ink/5 disabled:text-ink-3 disabled:shadow-[inset_0_0_0_1.5px_var(--hair-strong)]";
const FIELD = "w-full rounded-control bg-paper px-3 text-[16px] shadow-[inset_0_0_0_1px_var(--hair-strong)]";

function attachLabel(pair: CandidatePairDetail): string {
  const other = [pair.recordA, pair.recordB].find((card) => card.record.sourceSystem !== KIOSK_SYSTEM);
  return other?.displayLabel ?? "existing";
}

function mintKeys(): ReviewKeys {
  return { primary: crypto.randomUUID(), attach: crypto.randomUUID() };
}

interface Props {
  detail: CandidatePairDetail;
  /** The pairs the kiosk's held check-in waits on; the strongest still proposed can be attached. */
  handoffPairs: CandidatePairDetail[];
  sheet: Sheet;
  /** True after Resolve again on a rejection for not enough evidence (see reviewable). */
  reopened?: boolean;
  onSheetChange: (sheet: Sheet) => void;
  /** Called first, synchronously, with the server's responses, so the caller can draw the result
   * in the same frame the sheet closes (motion-polish finding 2: no Approve flash-back). */
  onConfirmed: (run: ReviewRun) => void;
  /** Called once the refetches have landed: announcements and focus. */
  onDecided: (response: ReviewResponse) => void;
}

/** Approve and Reject for the pair under review, and the confirm sheet that records the decision
 * (BUILD-SPEC decision 1: one Confirm may record the pair and the kiosk's check-in). */
export function ReviewPanel({
  detail,
  handoffPairs,
  sheet,
  reopened = false,
  onSheetChange,
  onConfirmed,
  onDecided,
}: Props) {
  const source = useDataSource();
  const queryClient = useQueryClient();
  const ids = useId();
  const reasonRef = useRef<HTMLSelectElement>(null);
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const approveRef = useRef<HTMLButtonElement>(null);
  const [registrar, setRegistrar] = useState(REGISTRARS[0]);
  const [reason, setReason] = useState<ReasonCode | "">("");
  const [note, setNote] = useState("");
  const [attachOn, setAttachOn] = useState(true);
  const [reasonMissing, setReasonMissing] = useState(false);
  // One Idempotency-Key per intent: minted when the sheet opens, kept until a response, so a
  // retry or a second click resends the same keys.
  const keys = useRef<ReviewKeys | null>(null);
  // While a match run or a session change is in flight the pair on screen may be about to change.
  const pairChanging =
    useIsMutating({ mutationKey: RESOLVE_KEY }) + useIsMutating({ mutationKey: SESSION_CHANGE_KEY }) > 0;

  const attach = sheet === "approve" ? attachablePair(handoffPairs, detail.pair.id) : null;

  const decide = useMutation({
    mutationFn: (steps: ReturnType<typeof planReviews>) => runReviews(source.review.bind(source), steps),
    onSuccess: async (run) => {
      onConfirmed(run);
      keys.current = null;
      onSheetChange(null);
      setReason("");
      setNote("");
      setAttachOn(true);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["case"] }),
        queryClient.invalidateQueries({ queryKey: ["events"] }),
        queryClient.invalidateQueries({ queryKey: ["tiles"] }),
        queryClient.invalidateQueries({ queryKey: HANDOFF_KEY }),
      ]);
      onDecided(run.primary);
    },
  });
  const blocked = decide.isPending || pairChanging;
  const proposed = reviewable(detail.pair.decision, reopened);

  useEffect(() => {
    if (!sheet) {
      keys.current = null;
      return;
    }
    keys.current ??= mintKeys();
    setReasonMissing(false);
    (sheet === "reject" ? reasonRef.current : noteRef.current)?.focus();
  }, [sheet]);

  function open(next: Exclude<Sheet, null>) {
    decide.reset();
    onSheetChange(next);
  }

  function cancel() {
    if (decide.isPending) return;
    onSheetChange(null);
    // Back to the opener, so a keyboard user does not lose their place.
    requestAnimationFrame(() => approveRef.current?.focus());
  }

  function submit() {
    if (!sheet || blocked) return;
    const actor = `registrar:${registrar}`;
    const trimmedNote = note.trim() || null;
    let body: ReviewRequest;
    if (sheet === "approve") {
      body = { action: "APPROVE", actor, note: trimmedNote };
    } else {
      if (!reason) {
        setReasonMissing(true);
        reasonRef.current?.focus();
        return;
      }
      body = { action: "REJECT", actor, reasonCode: reason, note: trimmedNote };
    }
    keys.current ??= mintKeys();
    decide.mutate(
      planReviews({
        pairId: detail.pair.id,
        body,
        attach: attach ? { pairId: attach.pair.id, on: attachOn } : null,
        keys: keys.current,
      }),
    );
  }

  const canOpen = proposed && !sheet && !blocked;
  useDeskAction("approve", canOpen ? () => open("approve") : null);
  useDeskAction("reject", canOpen ? () => open("reject") : null);
  useDeskAction("confirm", sheet && !blocked ? submit : null);
  useDeskAction("cancel", sheet ? cancel : null);

  if (!proposed && !sheet) return null;

  if (!sheet) {
    return (
      <div className="space-y-2.5" data-testid="review-controls">
        <button
          type="button"
          data-testid="approve-button"
          ref={approveRef}
          onClick={() => open("approve")}
          disabled={blocked}
          className={PRIMARY_BUTTON}
        >
          Approve link
          <kbd aria-hidden="true">A</kbd>
        </button>
        <button
          type="button"
          data-testid="reject-button"
          onClick={() => open("reject")}
          disabled={blocked}
          className={LINE_BUTTON}
        >
          Reject
          <kbd aria-hidden="true">X</kbd>
        </button>
      </div>
    );
  }

  const copy = COPY[sheet];
  const approving = sheet === "approve";
  return (
    <form
      aria-label={copy.form}
      data-testid="confirm-sheet"
      data-sheet={sheet}
      className="enter flex h-full flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      {/* The fields scroll inside the column; Confirm and Cancel stay in view at every size. */}
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
        <div>
          <p className="text-[15px] font-semibold text-ink-2">{copy.eyebrow}</p>
          <h2 className="mt-1 font-display text-[26px] font-[680] leading-[1.12] tracking-[-0.02em]">
            {copy.title}
          </h2>
          <p className="mt-2 text-[16px] leading-[1.45] text-ink-2">{copy.lead}</p>
        </div>
        {!approving && (
          <div className="space-y-1.5">
            <label htmlFor={`${ids}-reason`} className="block text-[15px] font-semibold">
              Reason
            </label>
            <select
              id={`${ids}-reason`}
              data-testid="review-reason-select"
              ref={reasonRef}
              value={reason}
              required
              aria-invalid={reasonMissing}
              aria-describedby={reasonMissing ? `${ids}-reason-error` : undefined}
              onChange={(e) => {
                setReason(e.target.value as ReasonCode | "");
                setReasonMissing(false);
              }}
              className={`${FIELD} h-11`}
            >
              <option value="">Select a reason</option>
              {Object.entries(REASONS).map(([code, label]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </select>
            {reasonMissing && (
              <p id={`${ids}-reason-error`} className="text-[15px] font-semibold text-ink">
                Select a reason to keep these records apart.
              </p>
            )}
          </div>
        )}
        <div className="space-y-1.5">
          <label htmlFor={`${ids}-registrar`} className="block text-[15px] font-semibold">
            Registrar
          </label>
          <select
            id={`${ids}-registrar`}
            value={registrar}
            onChange={(e) => setRegistrar(e.target.value)}
            className={`${FIELD} h-11`}
          >
            {REGISTRARS.map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <label htmlFor={`${ids}-note`} className="block text-[15px] font-semibold">
            Note (optional)
          </label>
          <textarea
            id={`${ids}-note`}
            data-testid="review-note-input"
            ref={noteRef}
            rows={2}
            value={note}
            maxLength={NOTE_MAX}
            onChange={(e) => setNote(e.target.value)}
            className={`${FIELD} resize-none py-2 leading-[1.4]`}
          />
        </div>
        {attach && (
          <label className="flex gap-2.5 rounded-control p-3 shadow-[inset_0_0_0_1px_var(--hair)]">
            <input
              type="checkbox"
              data-testid="attach-checkin"
              checked={attachOn}
              onChange={(e) => setAttachOn(e.target.checked)}
              className="mt-1 size-4 shrink-0 accent-mulberry"
            />
            <span>
              <span className="block text-[15px] font-semibold">Also attach the kiosk check-in</span>
              <span className="block text-[14px] leading-[1.35] text-ink-2">
                Matches the {attachLabel(attach)} record at {attach.pair.decision.p.toFixed(2)}. Saved as a
                second approval.
              </span>
            </span>
          </label>
        )}
        {decide.isError && (
          <p role="status" className="rounded-control bg-porcelain p-2 text-[15px] text-ink">
            Decision not recorded: {decide.error.message} Nothing changed. Confirm again to retry with the
            same request key.
          </p>
        )}
      </div>
      <div className="shrink-0 space-y-2.5">
        <button
          type="submit"
          data-testid="review-submit-button"
          disabled={blocked}
          className={PRIMARY_BUTTON}
        >
          {decide.isPending ? copy.pending : copy.confirm}
          <kbd aria-hidden="true">⏎</kbd>
        </button>
        <button type="button" onClick={cancel} disabled={decide.isPending} className={LINE_BUTTON}>
          Cancel
          <kbd aria-hidden="true">esc</kbd>
        </button>
      </div>
    </form>
  );
}
