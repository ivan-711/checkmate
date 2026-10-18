"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import type { Band, DecisionStatus, SourceCard } from "@/api/types";
import { BandChip } from "@/components/ui/BandChip";
import { ApiSource } from "@/data/apiSource";

const BANDS = ["AUTO_LINK", "REVIEW", "KEEP_SEPARATE"] as const satisfies readonly Band[];
const STATUSES = ["PROPOSED", "LINKED", "REJECTED", "REVOKED"] as const satisfies readonly DecisionStatus[];
const PAGE_SIZE = 12;
const FUNNEL_STYLE = { clipPath: "polygon(4% 0, 96% 0, 89% 100%, 11% 100%)" };

function name(card?: SourceCard): string {
  if (!card) return "Loading name…";
  const { givenName, familyName } = card.normalized;
  return [givenName, familyName].filter(Boolean).join(" ") || "Name not given";
}

function readable(value: string): string {
  return value
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/^./, (letter) => letter.toUpperCase());
}

export function WorkQueue() {
  const source = useMemo(() => new ApiSource(), []);
  const [band, setBand] = useState<Band | "">("");
  const [status, setStatus] = useState<DecisionStatus | "">("");
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const cursor = cursors.at(-1) ?? null;
  const run = useQuery({ queryKey: ["work-queue", "match-run"], queryFn: () => source.runMatch() });
  const page = useQuery({
    queryKey: ["work-queue", "pairs", run.data?.runId, band, status, cursor],
    queryFn: () =>
      source.getCandidatePairs({
        ...(band ? { band } : {}),
        ...(status ? { status } : {}),
        ...(cursor ? { cursor } : {}),
        limit: PAGE_SIZE,
      }),
    enabled: run.isSuccess,
  });
  const details = useQueries({
    queries: (page.data?.items ?? []).map((pair) => ({
      queryKey: ["candidate-pair", pair.id],
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
        <p className="max-w-2xl text-ink-2">Every candidate pair scored by the latest match run.</p>
      </div>

      {run.isPending && <p aria-busy="true">Running the local matcher…</p>}
      {run.isError && (
        <p className="rounded-md bg-error-bg p-3 text-error-ink">
          Match run unavailable: {run.error.message}
        </p>
      )}
      {run.data && (
        <section
          aria-labelledby="funnel-heading"
          className="rounded-lg border border-border-subtle bg-surface p-4"
        >
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h2 id="funnel-heading" className="text-[18px] font-semibold uppercase tracking-wider">
              Match run funnel
            </h2>
            <p className="font-mono text-[14px] text-ink-3">{run.data.elapsedMs.toLocaleString()} ms</p>
          </div>
          <ol aria-label="Match run funnel" className="mx-auto max-w-4xl space-y-1 text-center font-semibold">
            <li style={FUNNEL_STYLE} className="mx-auto w-full bg-ink-2 px-8 py-2 text-surface">
              {run.data.allPairs.toLocaleString()} all possible pairs
            </li>
            <li style={FUNNEL_STYLE} className="mx-auto w-3/4 bg-accent px-8 py-2 text-on-accent">
              {run.data.candidatePairs.toLocaleString()} compared
            </li>
            <li className="mx-auto flex w-1/2 overflow-hidden rounded-b-md" aria-hidden="true">
              {BANDS.map((item) => {
                const count = run.data.bandCounts[item] ?? 0;
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
                <dt>{readable(item)}</dt>
                <dd className="font-mono text-[18px] font-semibold">
                  {(run.data.bandCounts[item] ?? 0).toLocaleString()}
                </dd>
              </div>
            ))}
          </dl>
        </section>
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
                    {readable(item)}
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

        {page.isPending && run.isSuccess && <p aria-busy="true">Loading candidate pairs…</p>}
        {page.isError && (
          <p className="rounded-md bg-error-bg p-3 text-error-ink">Queue unavailable: {page.error.message}</p>
        )}
        {page.data?.items.length === 0 && (
          <p className="rounded-lg border border-border-subtle bg-surface p-6 text-ink-2">
            No candidate pairs match these filters.
          </p>
        )}
        {page.data && page.data.items.length > 0 && (
          <ul
            aria-label="Candidate pairs"
            className="divide-y divide-border-subtle overflow-hidden rounded-lg border border-border-subtle bg-surface"
          >
            {page.data.items.map((pair, index) => {
              const detail = details[index].data;
              const left = name(detail?.recordA);
              const right = name(detail?.recordB);
              return (
                <li key={pair.id}>
                  <Link
                    href={`/queue/${pair.id}`}
                    data-testid="work-queue-row"
                    aria-label={`Open ${left} and ${right}`}
                    className="grid min-h-16 grid-cols-[minmax(0,1fr)_auto_auto_auto] items-center gap-4 px-4 py-3 hover:bg-accent-soft max-[700px]:grid-cols-[minmax(0,1fr)_auto]"
                  >
                    <span className="min-w-0">
                      <span className="block font-semibold">{left}</span>
                      <span className="block text-ink-2">{right}</span>
                    </span>
                    <BandChip band={pair.decision.band} />
                    <span className="font-mono tabular-nums max-[700px]:col-start-2">
                      {(pair.decision.p * 100).toFixed(1)}%
                    </span>
                    <span className="text-[14px] font-semibold text-ink-2 max-[700px]:col-start-1">
                      {readable(pair.decision.status)}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
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
