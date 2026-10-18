"use client";

import type { SourceCard } from "@/api/types";
import { useCite } from "@/components/desk/CiteProvider";
import { ConstructedChip } from "@/components/ui/ConstructedChip";
import { CARD_FIELDS, CITE_CARD_FIELDS, type CardField } from "@/lib/display";
import type { CiteField } from "@/lib/desk";

/** The cite a card field answers to (hover-to-cite); sex and phone answer to none. */
function citeKeyFor(field: CardField): CiteField | undefined {
  return (Object.keys(CITE_CARD_FIELDS) as CiteField[]).find((k) =>
    (CITE_CARD_FIELDS[k] as readonly string[]).includes(field),
  );
}

const FORMAT_TAGS: Record<string, string> = { FHIR_PATIENT: "FHIR R4", CSV_ROW: "CSV" };

export function SourceCardView({ card, differs }: { card: SourceCard; differs: Set<CardField> }) {
  const { record, normalized, displayLabel } = card;
  const { cite } = useCite();
  return (
    <article
      data-testid="source-card"
      data-source-system={record.sourceSystem}
      aria-label={`${displayLabel} record`}
      className="rounded-lg border border-border-subtle bg-surface p-4"
    >
      <header className="mb-3 flex flex-wrap items-center gap-2">
        <h3 className="text-[20px] font-semibold">{displayLabel}</h3>
        <span className="rounded border border-border-strong px-2 text-[14px] text-ink-2">
          {FORMAT_TAGS[record.kind] ?? record.kind}
        </span>
        {record.isConstructed && <ConstructedChip />}
        <span className="w-full font-mono text-[14px] text-ink-3">{record.sourceLocalId}</span>
      </header>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        {CARD_FIELDS.map(([field, label]) => {
          const value = normalized[field];
          const citeKey = citeKeyFor(field);
          const cited = citeKey !== undefined && cite === citeKey;
          return (
            <div key={field} className="contents">
              <dt className="text-[16px] text-ink-3">{label}</dt>
              <dd
                data-field={citeKey}
                data-cited={citeKey ? String(cited) : undefined}
                className={`-mx-1 break-words rounded-[4px] px-1 transition-colors duration-[var(--t-micro)] ${
                  cited ? "bg-mulberry-cite" : ""
                }`}
              >
                {value == null ? (
                  <span className="text-ink-3">not given</span>
                ) : differs.has(field) ? (
                  <>
                    <span className="underline decoration-2 underline-offset-4">{value}</span>{" "}
                    <span className="rounded bg-sunken px-1 text-[14px] text-ink-2">differs</span>
                  </>
                ) : (
                  value
                )}
              </dd>
            </div>
          );
        })}
      </dl>
    </article>
  );
}
