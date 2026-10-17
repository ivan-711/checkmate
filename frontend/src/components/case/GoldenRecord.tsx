"use client";

import { useEffect, useRef } from "react";
import type { Entity, SourceCard } from "@/api/types";
import { ConstructedChip } from "@/components/ui/ConstructedChip";
import { sourceLabel } from "@/lib/display";

const FIELD_LABELS: Record<string, string> = {
  givenName: "Given name",
  familyName: "Family name",
  birthDate: "Date of birth",
  sex: "Sex",
  address: "Address",
  phone: "Phone",
};

function CrosswalkChip({
  system,
  recordId,
  cards,
}: {
  system: string;
  recordId: string;
  cards: SourceCard[];
}) {
  return (
    <span
      data-testid="crosswalk-chip"
      title={`Source record ${recordId}`}
      className="rounded border border-border-strong bg-surface px-2 text-[14px] font-medium text-ink-2"
    >
      {sourceLabel(system, cards)}
      <span className="sr-only">, source record {recordId}</span>
    </span>
  );
}

interface Props {
  entity: Entity;
  cards: SourceCard[];
  focusOnMount: boolean;
  onFocused: () => void;
}

export function GoldenRecord({ entity, cards, focusOnMount, onFocused }: Props) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (!focusOnMount) return;
    heading.current?.focus();
    onFocused();
  }, [focusOnMount, onFocused]);

  const golden = entity.golden ?? [];
  return (
    <section
      data-testid="golden-record"
      aria-labelledby="golden-heading"
      className="enter rounded-lg border border-border-subtle bg-surface p-4"
    >
      <h2 id="golden-heading" ref={heading} tabIndex={-1} className="text-[24px] font-semibold outline-none">
        Golden record
      </h2>
      <p className="mb-3 flex flex-wrap items-center gap-2 text-[16px] text-ink-2">
        Linked records:
        {entity.members.map((m) => (
          <span key={m.sourceRecordId} className="inline-flex items-center gap-1">
            <span className="font-semibold text-ink-1">{sourceLabel(m.sourceSystem, cards)}</span>
            {m.isConstructed && <ConstructedChip />}
          </span>
        ))}
      </p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
        {golden.map((g) => (
          <div key={g.field} className="contents">
            <dt className="text-[16px] text-ink-3">{FIELD_LABELS[g.field] ?? g.field}</dt>
            <dd className="flex flex-wrap items-center gap-2 break-words">
              {g.value == null ? <span className="text-ink-3">not given</span> : String(g.value)}
              <CrosswalkChip
                system={g.crosswalk.sourceSystem}
                recordId={g.crosswalk.sourceRecordId}
                cards={cards}
              />
              {g.alternates?.map((alt) => (
                <span key={alt.crosswalk.sourceRecordId} className="text-[16px] text-ink-3">
                  also {String(alt.value)}{" "}
                  <CrosswalkChip
                    system={alt.crosswalk.sourceSystem}
                    recordId={alt.crosswalk.sourceRecordId}
                    cards={cards}
                  />
                </span>
              ))}
            </dd>
          </div>
        ))}
      </dl>
      {entity.allLinksReviewerApproved && (
        <p className="mt-3 text-[16px] text-ink-3">
          Every link in this prototype requires recorded human approval.
        </p>
      )}
    </section>
  );
}
