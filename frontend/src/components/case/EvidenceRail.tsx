import type { CandidatePairDetail } from "@/api/types";
import { BandChip } from "@/components/ui/BandChip";
import { rankContributions } from "@/lib/display";

const TOP_CONTRIBUTIONS = 5;
// UX 3.1: on a short laptop screen (1366x650) the rail shows the top 4, so the review step's
// submit button stays above the fold.
const SHORT_SCREEN_ROWS = 4;

function signed(logit: number): string {
  return `${logit >= 0 ? "+" : "-"}${Math.abs(logit).toFixed(2)}`;
}

export function EvidenceRail({ detail }: { detail: CandidatePairDetail }) {
  const { decision } = detail.pair;
  const ranked = rankContributions(detail.contributions).slice(0, TOP_CONTRIBUTIONS);
  const scale = Math.max(...ranked.map((c) => Math.abs(c.logit)), Number.EPSILON);

  return (
    <section data-testid="evidence-rail" aria-labelledby="evidence-heading" className="space-y-2">
      <h2 id="evidence-heading" className="text-[18px] font-semibold uppercase tracking-wider">
        Evidence{" "}
        <span className="font-normal normal-case tracking-normal text-ink-2">
          {detail.recordA.displayLabel} and {detail.recordB.displayLabel}
        </span>
      </h2>
      <div>
        <div className="flex items-center gap-3">
          <span className="text-[40px] font-bold leading-[44px] tabular-nums">{decision.p.toFixed(2)}</span>
          <span data-testid="pair-band" className="inline-flex">
            <BandChip band={decision.band} />
          </span>
        </div>
        <p className="text-[14px] text-ink-2">
          Probability estimate fitted on our synthetic development distribution
        </p>
      </div>
      <div>
        <p className="mb-1 text-[14px] text-ink-3">Evidence weight (log-odds): against ← 0 → for</p>
        <ul aria-label="Top evidence" className="space-y-0.5">
          {ranked.map((c, i) => (
            <li
              key={c.feature}
              data-testid="evidence-feature-row"
              className={`grid grid-cols-[10rem_1fr_4rem] items-center gap-2 text-[16px] ${
                i >= SHORT_SCREEN_ROWS ? "[@media(max-height:700px)]:hidden" : ""
              }`}
            >
              <span>{c.label}</span>
              {c.missing ? (
                <span className="col-span-2 text-ink-3">no evidence</span>
              ) : (
                <>
                  <span aria-hidden className="grid h-3 grid-cols-2">
                    <span className="flex justify-end border-r border-ink-3">
                      {c.logit < 0 && (
                        <span
                          className="bg-evidence-against"
                          style={{ width: `${(-c.logit / scale) * 100}%` }}
                        />
                      )}
                    </span>
                    <span className="flex">
                      {c.logit > 0 && (
                        <span className="bg-evidence-for" style={{ width: `${(c.logit / scale) * 100}%` }} />
                      )}
                    </span>
                  </span>
                  <span className="text-right tabular-nums">{signed(c.logit)}</span>
                </>
              )}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
