"use client";

import { skipToken, useQueries, useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import type { Band, DecisionStatus, MatchRunResponse, PairOrigin, SourceCard } from "@/api/types";
import { BAND_LABELS, BandChip } from "@/components/ui/BandChip";
import { LATEST_MATCH_RUN_KEY, WORK_QUEUE_KEY } from "@/components/ui/ResetButton";
import { useDataSource } from "@/data/DataSourceProvider";
import type { Mode } from "@/data/source";

const BANDS = ["AUTO_LINK", "REVIEW", "KEEP_SEPARATE"] as const satisfies readonly Band[];
const STATUSES = ["PROPOSED", "LINKED", "REJECTED", "REVOKED"] as const satisfies readonly DecisionStatus[];
const ORIGINS = { MATCH_RUN: "Match run", FRONTDESK_HANDOFF: "FrontDesk hand-off" } as const satisfies Record<
  PairOrigin,
  string
>;
const PAGE_SIZE = 12;
const FUNNEL_STYLE = { clipPath: "polygon(4% 0, 96% 0, 89% 100%, 11% 100%)" };
// The queue only reads. Refocusing the window must not send anything, not even a re-read.
const READ_ONLY = { refetchOnWindowFocus: false } as const;
const NO_FUNNEL: Record<Mode, string> = {
  LOCAL: "Press Resolve identity on Case to see the match-run funnel.",
  REPLAY: "The recorded scenario comes already scored, so REPLAY has no match-run funnel.",
};

function name(card: SourceCard | undefined, failed: boolean): string {
  if (!card) return failed ? "Name unavailable" : "Loading name…";
  const { givenName, familyName } = card.normalized;
  return [givenName, familyName].filter(Boolean).join(" ") || "Name not given";
}

function readable(value: string): string {
  return value
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/^./, (letter) => letter.toUpperCase());
}

function Funnel({ run }: { run: MatchRunResponse }) {
  return (
    <section
      aria-labelledby="funnel-heading"
      className="rounded-lg border border-border-subtle bg-surface p-4"
    >
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="funnel-heading" className="text-[18px] font-semibold uppercase tracking-wider">
          Latest match run
        </h2>
        <p className="font-mono text-[14px] text-ink-3">{run.elapsedMs.toLocaleString()} ms</p>
      </div>
      <ol aria-label="Match run funnel" className="mx-auto max-w-4xl space-y-1 text-center font-semibold">
        <li style={FUNNEL_STYLE} className="mx-auto w-full bg-ink-2 px-8 py-2 text-surface">
          {run.allPairs.toLocaleString()} all possible pairs
        </li>
        <li style={FUNNEL_STYLE} className="mx-auto w-3/4 bg-accent px-8 py-2 text-on-accent">
          {run.candidatePairs.toLocaleString()} compared
        </li>
        <li className="mx-auto flex w-1/2 overflow-hidden rounded-b-md" aria-hidden="true">
          {BANDS.map((item) => {
            const count = run.bandCounts[item] ?? 0;
            return count ? (
              <span
                key={item}
                style={{ flexGrow: count }}
                className={`h-9 min-w-2 ${
                  item === "AUTO_LINK"
                    ? "bg-band-auto"
                    : item === "REVIEW"
                      ? "bg-band-review"
                      : "bg-band-keep"
                }`}
              />
            ) : null;
          })}
        </li>
      </ol>
      <dl className="mt-3 grid grid-cols-3 gap-2 text-center text-[14px] max-[540px]:grid-cols-1">
        {BANDS.map((item) => (
          <div key={item} className="rounded-md bg-sunken px-2 py-2">
            <dt>{BAND_LABELS[item]}</dt>
            <dd className="font-mono text-[18px] font-semibold">
              {(run.bandCounts[item] ?? 0).toLocaleString()}
            </dd>
          </div>
        ))}
      </dl>
      {run.pairsSkippedOversized > 0 && (
        <p className="mt-2 text-[14px] text-ink-2">
          {run.pairsSkippedOversized.toLocaleString()} pairs not compared: their block was over the size
          limit.
        </p>
      )}
    </section>
  );
}

export function WorkQueue() {
  const source = useDataSource();
  const [band, setBand] = useState<Band | "">("");
  const [status, setStatus] = useState<DecisionStatus | "">("");
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const cursor = cursors.at(-1) ?? null;
  // Written only by Resolve on Case; this screen never posts a match run.
  const run = useQuery<MatchRunResponse>({ queryKey: LATEST_MATCH_RUN_KEY, queryFn: skipToken });
  const page = useQuery({
    ...READ_ONLY,
    queryKey: [...WORK_QUEUE_KEY, "pairs", band, status, cursor],
    queryFn: () =>
      source.getCandidatePairs({
        ...(band ? { band } : {}),
        ...(status ? { status } : {}),
        ...(cursor ? { cursor } : {}),
        limit: PAGE_SIZE,
      }),
  });
  const details = useQueries({
    queries: (page.data?.items ?? []).map((pair) => ({
      ...READ_ONLY,
      queryKey: [...WORK_QUEUE_KEY, "pair", pair.id],
      queryFn: () => source.getCandidatePair(pair.id),
    })),
  });

  function changeFilter(nextBand: Band | "", nextStatus: DecisionStatus | "") {
    setBand(nextBand);
    setStatus(nextStatus);
    setCursors([null]);
  }

  return (
    <div className="space-y-5">
      <div>
        <p className="text-[14px] font-semibold uppercase tracking-widest text-ink-3">Registrar console</p>
        <h1 className="text-[32px] font-semibold tracking-tight">Work queue</h1>
        <p className="max-w-2xl text-ink-2">
          Every stored candidate pair, most uncertain first. Open one to see its evidence. A decision takes a
          confirm step and a registrar label, and every decision is logged.
        </p>
      </div>

      {run.data ? (
        <Funnel run={run.data} />
      ) : (
        <p data-testid="work-queue-no-funnel" className="text-ink-3">
          {NO_FUNNEL[source.mode]}
        </p>
      )}

      <section aria-labelledby="pairs-heading" className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 id="pairs-heading" className="text-[22px] font-semibold">
            Candidate pairs
          </h2>
          <div className="flex flex-wrap gap-3">
            <label className="text-[14px] font-semibold">
              <span className="mb-1 block">Decision band</span>
              <select
                value={band}
                onChange={(event) => changeFilter(event.target.value as Band | "", status)}
                className="h-11 rounded-md border border-border-strong bg-surface px-3 text-[16px] font-normal"
              >
                <option value="">All bands</option>
                {BANDS.map((item) => (
                  <option key={item} value={item}>
                    {BAND_LABELS[item]}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-[14px] font-semibold">
              <span className="mb-1 block">Status</span>
              <select
                value={status}
                onChange={(event) => changeFilter(band, event.target.value as DecisionStatus | "")}
                className="h-11 rounded-md border border-border-strong bg-surface px-3 text-[16px] font-normal"
              >
                <option value="">All statuses</option>
                {STATUSES.map((item) => (
                  <option key={item} value={item}>
                    {readable(item)}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        {page.isPending && (
          <p aria-busy="true" className="text-ink-3">
            Loading candidate pairs…
          </p>
        )}
        {page.isError && (
          <div className="rounded-md bg-error-bg p-3 text-error-ink">
            <p>Work queue unavailable: {page.error.message}. Nothing was changed.</p>
            <button
              type="button"
              onClick={() => page.refetch()}
              className="mt-2 inline-flex h-11 items-center rounded-md border border-border-strong bg-surface px-4 font-semibold text-ink-1"
            >
              Try again
            </button>
          </div>
        )}
        {page.data?.items.length === 0 && (
          <p className="rounded-lg border border-border-subtle bg-surface p-6 text-ink-3">
            {band || status
              ? "No candidate pairs match these filters."
              : "No candidate pairs yet. Resolve identity on Case scores the loaded records."}
          </p>
        )}
        {page.data && page.data.items.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-border-subtle bg-surface">
            <div
              data-testid="work-queue-columns"
              className="grid grid-cols-[minmax(0,1fr)_auto_9rem_9rem] items-end gap-4 border-b border-border-subtle bg-sunken px-4 py-2 text-[14px] text-ink-2 max-[700px]:grid-cols-[minmax(0,1fr)_auto]"
            >
              <span className="font-semibold">Records</span>
              <span className="font-semibold">Decision band</span>
              <span className="max-[700px]:col-start-2">
                <span className="block font-semibold">Probability estimate</span>
                <span className="block text-[12px]">fitted on our synthetic development distribution</span>
              </span>
              <span className="font-semibold max-[700px]:hidden">Status</span>
            </div>
            <ul aria-label="Candidate pairs" className="divide-y divide-border-subtle">
              {page.data.items.map((pair, index) => {
                const detail = details[index];
                return (
                  <li key={pair.id}>
                    <Link
                      href={`/queue/${pair.id}`}
                      data-testid="work-queue-row"
                      className="grid min-h-16 grid-cols-[minmax(0,1fr)_auto_9rem_9rem] items-center gap-4 px-4 py-3 hover:bg-accent-soft max-[700px]:grid-cols-[minmax(0,1fr)_auto]"
                    >
                      <span className="min-w-0">
                        <span className="block font-semibold">
                          {name(detail.data?.recordA, detail.isError)}
                        </span>
                        <span className="block text-ink-2">{name(detail.data?.recordB, detail.isError)}</span>
                      </span>
                      <BandChip band={pair.decision.band} />
                      <span className="font-mono tabular-nums max-[700px]:col-start-2">
                        {pair.decision.p.toFixed(2)}
                      </span>
                      <span className="text-[14px] text-ink-2 max-[700px]:col-start-1">
                        <span className="block font-semibold">{readable(pair.decision.status)}</span>
                        <span className="block">{ORIGINS[pair.origin]}</span>
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
        {page.data && (cursors.length > 1 || page.data.nextCursor) && (
          <nav aria-label="Candidate pair pages" className="flex items-center justify-between">
            <button
              type="button"
              disabled={cursors.length === 1}
              onClick={() => setCursors((items) => items.slice(0, -1))}
              className="inline-flex h-11 items-center gap-2 rounded-md border border-border-strong bg-surface px-4 disabled:text-ink-3"
            >
              <ArrowLeft aria-hidden size={18} /> Previous
            </button>
            <span className="text-[14px] text-ink-3">Page {cursors.length}</span>
            <button
              type="button"
              disabled={!page.data.nextCursor}
              onClick={() => setCursors((items) => [...items, page.data!.nextCursor!])}
              className="inline-flex h-11 items-center gap-2 rounded-md border border-border-strong bg-surface px-4 disabled:text-ink-3"
            >
              Next <ArrowRight aria-hidden size={18} />
            </button>
          </nav>
        )}
      </section>
    </div>
  );
}
