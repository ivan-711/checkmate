"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState } from "react";
import type {
  CandidatePairDetail,
  MatchDecision,
  ReasonCode,
  ReviewRequest,
  ReviewResponse,
} from "@/api/types";
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

function DecisionLine({ decision }: { decision: MatchDecision }) {
  const who = `${actorName(decision.actor)} at ${formatCt(decision.decidedAt)}`;
  if (decision.status === "LINKED") return <p>Approved by {who}.</p>;
  if (decision.status !== "REJECTED") return null;
  const reason = decision.reasonCode ? REASONS[decision.reasonCode] : "not recorded";
  return (
    <p>
      Rejected by {who}. Reason: {reason}. Records kept separate.
    </p>
  );
}

interface Props {
  detail: CandidatePairDetail;
  onDecided: (response: ReviewResponse) => void;
}

export function ReviewPanel({ detail, onDecided }: Props) {
  const source = useDataSource();
  const queryClient = useQueryClient();
  const ids = useId();
  const reasonRef = useRef<HTMLSelectElement>(null);
  const [registrar, setRegistrar] = useState(REGISTRARS[0]);
  const [reason, setReason] = useState<ReasonCode | "">("");
  const [note, setNote] = useState("");
  const [reasonMissing, setReasonMissing] = useState(false);
  // One Idempotency-Key per decision intent: resending the same decision after a failure
  // reuses it, while a different decision is a new intent with a new key.
  const intent = useRef<{ body: string; key: string } | null>(null);

  function keyFor(body: ReviewRequest): string {
    const serialized = JSON.stringify(body);
    if (intent.current?.body !== serialized) intent.current = { body: serialized, key: crypto.randomUUID() };
    return intent.current.key;
  }

  const decide = useMutation({
    mutationFn: (body: ReviewRequest) => source.review(detail.pair.id, body, keyFor(body)),
    onSuccess: async (response) => {
      intent.current = null;
      setReason("");
      setNote("");
      await queryClient.invalidateQueries({ queryKey: ["case"] });
      onDecided(response);
    },
  });

  const { decision } = detail.pair;
  const actor = `registrar:${registrar}`;
  const trimmedNote = note.trim() || null;

  function approve() {
    decide.mutate({ action: "APPROVE", actor, note: trimmedNote });
  }

  function reject() {
    if (!reason) {
      setReasonMissing(true);
      reasonRef.current?.focus();
      return;
    }
    decide.mutate({ action: "REJECT", actor, reasonCode: reason, note: trimmedNote });
  }

  const pendingAction = decide.isPending ? decide.variables?.action : null;

  return (
    <section aria-labelledby={`${ids}-h`} className="space-y-3 border-t border-border-subtle pt-4">
      <h2 id={`${ids}-h`} className="text-[18px] font-semibold uppercase tracking-wider">
        Review
      </h2>
      <DecisionLine decision={decision} />
      {decision.status !== "LINKED" && (
        <>
          <div className="grid grid-cols-[8rem_1fr] items-center gap-x-3 gap-y-2">
            <label htmlFor={`${ids}-registrar`}>Registrar</label>
            <div>
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
              <span id={`${ids}-fixture`} className="text-[14px] text-ink-3">
                Fixture name
              </span>
            </div>
            <label htmlFor={`${ids}-reason`}>Reason</label>
            <select
              id={`${ids}-reason`}
              ref={reasonRef}
              value={reason}
              aria-invalid={reasonMissing}
              aria-describedby={reasonMissing ? `${ids}-reason-error` : `${ids}-reason-hint`}
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
            {reasonMissing ? (
              <p id={`${ids}-reason-error`} className="col-start-2 text-[16px] text-error-ink">
                Select a reason to reject the link.
              </p>
            ) : (
              <p id={`${ids}-reason-hint`} className="col-start-2 text-[14px] text-ink-3">
                Required to reject
              </p>
            )}
            <label htmlFor={`${ids}-note`}>Note (optional)</label>
            <input
              id={`${ids}-note`}
              value={note}
              maxLength={NOTE_MAX}
              onChange={(e) => setNote(e.target.value)}
              className="h-11 w-full rounded-md border border-border-strong bg-surface px-2"
            />
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={approve}
              disabled={decide.isPending}
              className="h-14 rounded-md bg-accent px-6 font-semibold text-on-accent hover:bg-accent-hover disabled:bg-sunken disabled:text-ink-3"
            >
              {pendingAction === "APPROVE" ? "Linking..." : "Approve link"}
            </button>
            <button
              type="button"
              onClick={reject}
              disabled={decide.isPending}
              className="h-14 rounded-md border border-border-strong bg-surface px-6 font-semibold text-ink-1 hover:bg-sunken disabled:text-ink-3"
            >
              {pendingAction === "REJECT" ? "Rejecting..." : "Reject link"}
            </button>
          </div>
          {decide.isError && (
            <p className="rounded-md bg-error-bg p-2 text-error-ink">
              Decision not recorded: {decide.error.message} Nothing changed.
            </p>
          )}
        </>
      )}
    </section>
  );
}
