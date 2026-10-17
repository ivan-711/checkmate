import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { API_BASE } from './playwright.config';

// The hero the engine exported (data/hero_select.py). The cards and the golden record must be the
// hero's, not any two records: a stub rendering two cards, REVIEW and BL-AMOX-01 must not pass.
const SCENARIO_PATH = process.env.CHECKMATE_SCENARIO ?? resolve(__dirname, '../../data/scenarios/hero/scenario.json');

interface HeroNormalized {
  givenName: string | null;
  familyName: string | null;
  birthDate: string | null;
}

interface HeroScenario {
  session: { sources: Array<{ record: { sourceSystem: string }; normalized: HeroNormalized }> };
  entityIfApproved: { golden: Array<{ field: string; value: unknown }> };
}

const HERO = JSON.parse(readFileSync(SCENARIO_PATH, 'utf8')) as HeroScenario;

function heroSource(system: string): HeroNormalized {
  const source = HERO.session.sources.find((s) => s.record.sourceSystem === system);
  if (!source) throw new Error(`scenario.json has no ${system} source`);
  return source.normalized;
}

function heroGolden(field: string): string {
  const value = HERO.entityIfApproved.golden.find((g) => g.field === field)?.value;
  if (typeof value !== 'string' || value.length === 0) throw new Error(`scenario.json golden ${field} missing`);
  return value;
}

/**
 * G16 demo path (CLAUDE.md wave 1, integration gate). Written before the UI exists: every locator
 * is a data-testid listed in README.md, which lane W4 adds. The script changes nothing it cannot
 * undo: it starts with Reset and leaves the hero approved, which the next Reset clears.
 *
 * Steps: reset; two source cards; Resolve shows the hero pair in REVIEW with the evidence rail;
 * Reject with a reason: no flag card, event row exists; second review Approve with reason and
 * note: cards collapse, timeline shows both sources, the neutral flag card carries BL-AMOX-01 and
 * the constructed-scenario chip; GET /events has one row per action; the human-review tile is
 * non-zero. Every API response seen by the page must be below 500.
 */

const T = {
  modeBadge: 'app-mode-badge',
  resetButton: 'reset-button',
  sourceCard: 'source-card',            // data-source-system="ER_FHIR" | "CLINIC_CSV"
  resolveButton: 'resolve-button',
  candidatePair: 'candidate-pair',
  pairBand: 'pair-band',                // text: REVIEW
  evidenceRail: 'evidence-rail',
  evidenceFeatureRow: 'evidence-feature-row',
  rejectButton: 'reject-button',
  approveButton: 'approve-button',
  reviewReasonSelect: 'review-reason-select',  // values DIFFERENT_PERSON | INSUFFICIENT_EVIDENCE
  reviewNoteInput: 'review-note-input',
  reviewSubmitButton: 'review-submit-button',
  goldenRecord: 'golden-record',
  crosswalkChip: 'crosswalk-chip',
  timeline: 'timeline',
  timelineEvent: 'timeline-event',      // data-source-system
  flagCard: 'flag-card',
  flagCardRuleId: 'flag-card-rule-id',  // text: BL-AMOX-01
  constructedScenarioChip: 'constructed-scenario-chip',
  eventRow: 'event-row',                // data-event-type
  tileHumanReview: 'tile-human-review',
  tileHumanReviewTotal: 'tile-human-review-total',
} as const;

const REJECT_REASON = 'INSUFFICIENT_EVIDENCE'; // no suppression, so the second review can approve
const RULE_ID = 'BL-AMOX-01';
const NEVER_SAY = ['prevented', 'would have died', 'the ai caught', 'contraindicated for this patient', 'fatal'];

function byId(page: Page, id: string) {
  return page.getByTestId(id);
}

async function submitReview(page: Page, kind: 'approve' | 'reject', note: string, reason?: string) {
  await byId(page, kind === 'approve' ? T.approveButton : T.rejectButton).click();
  const reasonSelect = byId(page, T.reviewReasonSelect);
  if (reason) {
    await reasonSelect.selectOption(reason);
  } else if (await reasonSelect.isVisible().catch(() => false)) {
    await reasonSelect.selectOption({ index: 0 });
  }
  await byId(page, T.reviewNoteInput).fill(note);
  await byId(page, T.reviewSubmitButton).click();
}

async function eventCounts(request: APIRequestContext): Promise<Record<string, number>> {
  // Event rows are append-only and the database is reused (CLAUDE.md rule 4), so counts are read in
  // full (cursor pagination, clamped limit) and the assertions below compare deltas against a snapshot.
  const counts: Record<string, number> = {};
  let cursor: string | null = null;
  for (let page = 0; page < 50; page++) {
    const url = `${API_BASE}/api/v1/events?limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`;
    const res = await request.get(url);
    expect(res.status(), 'GET /events must answer 200').toBe(200);
    const body = (await res.json()) as { items: Array<{ eventType: string }>; nextCursor: string | null };
    for (const row of body.items) {
      const key = row.eventType.toLowerCase();
      counts[key] = (counts[key] ?? 0) + 1;
    }
    cursor = body.nextCursor;
    if (!cursor) break;
  }
  return counts;
}

function delta(after: Record<string, number>, before: Record<string, number>, key: string): number {
  return (after[key] ?? 0) - (before[key] ?? 0);
}

test.describe('G16 demo path', () => {
  test('reset, resolve, reject, approve, flag card, events, tile', async ({ page, request }) => {
    const health = await request.get(`${API_BASE}/api/v1/health`);
    expect(health.status(), 'API health must answer').toBe(200);

    const serverErrors: string[] = [];
    page.on('response', (res) => {
      if (res.status() >= 500) serverErrors.push(`${res.status()} ${res.request().method()} ${res.url()}`);
    });

    const before = await eventCounts(request);
    await page.goto('/');
    await expect(byId(page, T.modeBadge)).toBeVisible();

    // 1. reset: the hero session is rebuilt and two source cards render
    await byId(page, T.resetButton).click();
    const cards = byId(page, T.sourceCard);
    await expect(cards).toHaveCount(2);
    for (const system of ['ER_FHIR', 'CLINIC_CSV']) {
      const card = page.locator(`[data-testid="${T.sourceCard}"][data-source-system="${system}"]`);
      await expect(card).toHaveCount(1);
      const hero = heroSource(system);
      for (const value of [hero.givenName, hero.familyName]) {
        if (value) await expect(card, `${system} card shows the hero's ${value}`).toContainText(value);
      }
    }

    // 2. resolve: the hero pair lands in REVIEW with the evidence rail
    await byId(page, T.resolveButton).click();
    await expect(byId(page, T.candidatePair)).toBeVisible();
    await expect(byId(page, T.pairBand)).toHaveText(/REVIEW/);
    await expect(byId(page, T.evidenceRail)).toBeVisible();
    expect(await byId(page, T.evidenceFeatureRow).count()).toBeGreaterThan(0);

    // 3. reject with a reason: no flag card, one event row for the rejection
    await submitReview(page, 'reject', 'acceptance: first review rejects for insufficient evidence', REJECT_REASON);
    await expect(byId(page, T.flagCard)).toHaveCount(0);
    await expect(page.locator(`[data-testid="${T.eventRow}"][data-event-type="link_rejected" i]`)).not.toHaveCount(0);

    // 4. second review: resolve again (INSUFFICIENT_EVIDENCE does not suppress), approve with reason and note
    await byId(page, T.resolveButton).click();
    await expect(byId(page, T.candidatePair)).toBeVisible();
    await expect(byId(page, T.pairBand)).toHaveText(/REVIEW/);
    await submitReview(page, 'approve', 'acceptance: second review approves the link');

    // 5. cards collapse into one golden record with crosswalk chips; the timeline shows both sources
    await expect(byId(page, T.goldenRecord)).toBeVisible();
    await expect(byId(page, T.goldenRecord)).toContainText(heroGolden('givenName'));
    await expect(byId(page, T.goldenRecord)).toContainText(heroGolden('familyName'));
    await expect(byId(page, T.sourceCard)).toHaveCount(0);
    expect(await byId(page, T.crosswalkChip).count()).toBeGreaterThan(0);
    await expect(byId(page, T.timeline)).toBeVisible();
    await expect(page.locator(`[data-testid="${T.timelineEvent}"][data-source-system="ER_FHIR"]`)).not.toHaveCount(0);
    await expect(page.locator(`[data-testid="${T.timelineEvent}"][data-source-system="CLINIC_CSV"]`)).not.toHaveCount(0);

    // 6. the neutral flag card: BL-AMOX-01, constructed-scenario chip, no role="alert", no banned words
    const flag = byId(page, T.flagCard);
    await expect(flag).toBeVisible();
    await expect(byId(page, T.flagCardRuleId)).toHaveText(RULE_ID);
    await expect(flag.getByTestId(T.constructedScenarioChip)).toBeVisible();
    await expect(flag).toHaveText(/flagged for clinician review/i);
    expect(await flag.getAttribute('role')).not.toBe('alert');
    const flagText = (await flag.innerText()).toLowerCase();
    for (const banned of NEVER_SAY) expect(flagText, `flag card must never say "${banned}"`).not.toContain(banned);

    // 7. GET /events has one row per action (deltas since the pre-run snapshot)
    const after = await eventCounts(request);
    expect(delta(after, before, 'demo_reset')).toBe(1);
    expect(delta(after, before, 'match_run_completed')).toBe(2);
    expect(delta(after, before, 'link_rejected')).toBe(1);
    expect(delta(after, before, 'link_approved')).toBe(1);
    expect(delta(after, before, 'alert_raised')).toBe(1);

    // 8. the human-review tile is non-zero, in the API and on screen
    const tiles = await request.get(`${API_BASE}/api/v1/metrics/tiles`);
    expect(tiles.status()).toBe(200);
    const tileBody = (await tiles.json()) as { tiles: Array<{ id: string; total: number }> };
    const humanReview = tileBody.tiles.find((t) => t.id === 'HUMAN_REVIEW');
    expect(humanReview?.total ?? 0).toBeGreaterThan(0);
    await expect(byId(page, T.tileHumanReview)).toBeVisible();
    await expect(byId(page, T.tileHumanReviewTotal)).not.toHaveText(/^0$/);

    expect(serverErrors, 'no 5xx seen by the page').toEqual([]);
  });
});
