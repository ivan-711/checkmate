"use client";

import { useIsMutating, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type ReactNode, type Ref } from "react";
import type {
  CandidatePairDetail,
  MatchDecision,
  ReasonCode,
  ReviewRequest,
  ReviewResponse,
} from "@/api/types";
import { RESOLVE_KEY, SESSION_CHANGE_KEY } from "@/components/ui/ResetButton";
import { useDataSource } from "@/data/DataSourceProvider";
import { scenario } from "@/data/scenario";
import { actorName, formatCt } from "@/lib/display";

// Fixture names, recorded as a label on the decision; not an authenticated identity.
const REGISTRARS = scenario.registrarLabels;
const NOTE_MAX = 500;

export const REASONS: Record<ReasonCode, string> = {
  DIFFERENT_PERSON: "Different person",
  INSUFFICIENT_EVIDENCE: "Insufficient evidence",
};

type Action = "APPROVE" | "REJECT";

/** One Idempotency-Key per user intent: minted when the decision dialog opens for a pair
 * version, kept until a response arrives, so a retry or a second click resends the same key. */
interface Intent {
  action: Action;
  key: string;
}

function DecisionLine({
  decision,
  lineRef,
}: {
  decision: MatchDecision;
  lineRef: Ref<HTMLParagraphElement>;
}) {
  const who = `${actorName(decision.actor)} at ${formatCt(decision.decidedAt)}`;
  if (decision.status === "LINKED") return <p>Approved by {who}.</p>;
  if (decision.status !== "REJECTED") return null;
  const reason = decision.reasonCode ? REASONS[decision.reasonCode] : "not recorded";
  // Focusable so a keyboard user lands on the result after recording a reject.
  return (
    <p ref={lineRef} tabIndex={-1} className="outline-none focus-visible:outline-2">
      Rejected by {who}. Reason: {reason}. Records kept separate.
    </p>
  );
}

interface Props {
  detail: CandidatePairDetail;
  onDecided: (response: ReviewResponse) => void;
  /** Shown right under the decision line: what the decision led to, where the caller has it. */
  children?: ReactNode;
}

export function ReviewPanel({ detail, onDecided, children }: Props) {
  const source = useDataSource();
  const queryClient = useQueryClient();
  const ids = useId();
  const reasonRef = useRef<HTMLSelectElement>(null);
  const noteRef = useRef<HTMLInputElement>(null);
  const [registrar, setRegistrar] = useState(REGISTRARS[0]);
  const [intent, setIntent] = useState<Intent | null>(null);
  const [reason, setReason] = useState<ReasonCode | "">("");
  const [note, setNote] = useState("");
  const [reasonMissing, setReasonMissing] = useState(false);
  // Where keyboard focus goes once the step closes: back to its opener, or to the line for the
  // decision just recorded (by id, so no later render can pull focus to some other decision).
  const [returnTo, setReturnTo] = useState<Action | { decisionId: string } | null>(null);
  const approveRef = useRef<HTMLButtonElement>(null);
  const rejectRef = useRef<HTMLButtonElement>(null);
  const decisionRef = useRef<HTMLParagraphElement>(null);
  // While a match run or a session change is in flight the pair on screen may be about to change,
  // so no decision can be recorded against it.
  const pairChanging =
    useIsMutating({ mutationKey: RESOLVE_KEY }) + useIsMutating({ mutationKey: SESSION_CHANGE_KEY }) > 0;

  const decide = useMutation({
    mutationFn: ({ body, key }: { body: ReviewRequest; key: string }) =>
      source.review(detail.pair.id, body, key),
    onSuccess: async (response) => {
      // A recorded approve moves focus to the golden record (CaseScreen); a reject stays here.
      if (response.decision.status === "REJECTED") setReturnTo({ decisionId: response.decision.id });
      setIntent(null);
      setReason("");
      setNote("");
      await queryClient.invalidateQueries({ queryKey: ["case"] });
      await queryClient.invalidateQueries({ queryKey: ["events"] });
      await queryClient.invalidateQueries({ queryKey: ["tiles"] });
      onDecided(response);
    },
  });

  const blocked = decide.isPending || pairChanging;

  // The refreshed decision can arrive a render after the request, so the request waits until
  // its target is on screen.
  const currentDecisionId = detail.pair.decision.id;
  useEffect(() => {
    if (intent || !returnTo) return;
    const target =
      typeof returnTo === "string"
        ? { APPROVE: approveRef, REJECT: rejectRef }[returnTo].current
        : returnTo.decisionId === currentDecisionId
          ? decisionRef.current
          : null;
    if (!target) return;
    target.focus();
    setReturnTo(null);
  }, [intent, returnTo, currentDecisionId]);

  useEffect(() => {
    if (!intent) return;
    (intent.action === "REJECT" ? reasonRef.current : noteRef.current)?.focus();
  }, [intent]);

  const { decision } = detail.pair;
  const actor = `registrar:${registrar}`;

  function open(action: Action) {
    setReturnTo(null); // a new step drops any focus request still waiting
    decide.reset();
    setReasonMissing(false);
    setIntent({ action, key: crypto.randomUUID() });
  }

  function submit() {
    if (!intent) return;
    const trimmedNote = note.trim() || null;
    if (intent.action === "APPROVE") {
      decide.mutate({ body: { action: "APPROVE", actor, note: trimmedNote }, key: intent.key });
      return;
    }
    if (!reason) {
      setReasonMissing(true);
      reasonRef.current?.focus();
      return;
    }
    decide.mutate({
      body: { action: "REJECT", actor, reasonCode: reason, note: trimmedNote },
      key: intent.key,
    });
  }

  const approving = intent?.action === "APPROVE";

  return (
    <section aria-labelledby={`${ids}-h`} className="space-y-2 border-t border-border-subtle pt-3">
      <h2 id={`${ids}-h`} className="text-[18px] font-semibold uppercase tracking-wider">
        Review
      </h2>
      <DecisionLine decision={decision} lineRef={decisionRef} />
      {children}
      {decision.status !== "LINKED" && (
        <>
          <div className="grid grid-cols-[8rem_1fr] items-center gap-x-3 gap-y-2">
            <label htmlFor={`${ids}-registrar`} className="leading-tight">
              Registrar
              <span id={`${ids}-fixture`} className="block text-[14px] text-ink-3">
                Fixture name
              </span>
            </label>
            <select
              id={`${ids}-registrar`}
              aria-describedby={`${ids}-fixture`}
              value={registrar}
              onChange={(e) => setRegistrar(e.target.value)}
              className="h-11 w-full rounded-md border border-border-strong bg-surface px-2"
            >
              {REGISTRARS.map((name) => (
                <option key={name}>{name}</option>
              ))}
            </select>
          </div>
          {!intent && (
            <div className="flex gap-2">
              <button
                type="button"
                data-testid="approve-button"
                ref={approveRef}
                onClick={() => open("APPROVE")}
                aria-expanded={false}
                disabled={blocked}
                className="h-12 rounded-md bg-accent px-6 font-semibold text-on-accent hover:bg-accent-hover disabled:bg-sunken disabled:text-ink-3"
              >
                Approve link
              </button>
              <button
                type="button"
                data-testid="reject-button"
                ref={rejectRef}
                onClick={() => open("REJECT")}
                aria-expanded={false}
                disabled={blocked}
                className="h-12 rounded-md border border-border-strong bg-surface px-6 font-semibold text-ink-1 hover:bg-sunken disabled:text-ink-3"
              >
                Reject link
              </button>
            </div>
          )}
          {intent && (
            <form
              aria-label={approving ? "Approve this link" : "Reject this link"}
              className="space-y-2 rounded-lg border border-border-strong bg-sunken p-3"
              onSubmit={(e) => {
                e.preventDefault();
                submit();
              }}
            >
              <div className="grid grid-cols-[8rem_1fr] items-center gap-x-3 gap-y-2">
                {!approving && (
                  <>
                    <label htmlFor={`${ids}-reason`}>Reason (required)</label>
                    <select
                      id={`${ids}-reason`}
                      data-testid="review-reason-select"
                      ref={reasonRef}
                      value={reason}
                      aria-invalid={reasonMissing}
                      aria-describedby={reasonMissing ? `${ids}-reason-error` : undefined}
                      onChange={(e) => {
                        setReason(e.target.value as ReasonCode | "");
                        setReasonMissing(false);
                      }}
                      className="h-11 w-full rounded-md border border-border-strong bg-surface px-2"
                    >
                      <option value="">Select a reason</option>
                      {Object.entries(REASONS).map(([code, label]) => (
                        <option key={code} value={code}>
                          {label}
                        </option>
                      ))}
                    </select>
                    {reasonMissing && (
                      <p id={`${ids}-reason-error`} className="col-start-2 text-[16px] text-error-ink">
                        Select a reason to reject the link.
                      </p>
                    )}
                  </>
                )}
                <label htmlFor={`${ids}-note`}>Note (optional)</label>
                <input
                  id={`${ids}-note`}
                  data-testid="review-note-input"
                  ref={noteRef}
                  value={note}
                  maxLength={NOTE_MAX}
                  onChange={(e) => setNote(e.target.value)}
                  className="h-11 w-full rounded-md border border-border-strong bg-surface px-2"
                />
              </div>
              <div className="flex gap-2">
                <button
                  type="submit"
                  data-testid="review-submit-button"
                  disabled={blocked}
                  className="h-11 rounded-md bg-accent px-5 font-semibold text-on-accent hover:bg-accent-hover disabled:bg-sunken disabled:text-ink-3"
                >
                  {decide.isPending
                    ? approving
                      ? "Linking..."
                      : "Rejecting..."
                    : approving
                      ? "Confirm approve"
                      : "Confirm reject"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setReturnTo(intent.action);
                    setIntent(null);
                  }}
                  disabled={decide.isPending}
                  className="h-11 rounded-md border border-border-strong bg-surface px-5 font-semibold text-ink-1 hover:bg-sunken disabled:text-ink-3"
                >
                  Cancel
                </button>
              </div>
              {decide.isError && (
                <p className="rounded-md bg-error-bg p-2 text-error-ink">
                  Decision not recorded: {decide.error.message} Nothing changed. Confirm again to retry with
                  the same request key.
                </p>
              )}
            </form>
          )}
        </>
      )}
      <p className="font-mono text-[14px] text-ink-3">
        scorer {decision.scorerVersion} · thresholds {decision.thresholdSetId}
      </p>
    </section>
  );
}
