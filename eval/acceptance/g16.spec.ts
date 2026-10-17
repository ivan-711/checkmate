import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import { API_BASE } from './playwright.config';

// The hero the engine exported (data/hero_select.py, data/scenarios/hero/hero.json). The cards and the
// golden record must be the hero's, not any two records: a stub rendering two cards, REVIEW and
// BL-AMOX-01 must not pass.
const HERO_PATH = process.env.CHECKMATE_HERO ?? resolve(__dirname, '../../data/scenarios/hero/hero.json');

interface HeroRecord {
  given_name: string | null;
  family_name: string | null;
}

interface HeroExport {
  records: { ER_FHIR: HeroRecord; CLINIC_CSV: HeroRecord };
}

const HERO = JSON.parse(readFileSync(HERO_PATH, 'utf8')) as HeroExport;

function heroRecord(system: 'ER_FHIR' | 'CLINIC_CSV'): HeroRecord {
  const record = HERO.records[system];
  if (!record) throw new Error(`hero.json has no ${system} record`);
  return record;
}

// Names compare case-, accent-, space- and punctuation-insensitively: the UI may show the source
// spelling, W2's normalized form or the golden value ("Mesa-López", "mesa lopez", "MesaLopez").
function nameKey(text: string): string {
  return text.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
}

async function expectShowsName(locator: Locator, name: string | null, what: string): Promise<void> {
  if (!name) return;
  await expect.poll(async () => nameKey(await locator.innerText()), { message: `${what} shows ${name}` })
    .toContain(nameKey(name));
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

// The events feed holds every earlier run on a reused database, and one match run writes about 7,000
// PAIR_SCORED rows, so counts are read from the API's own clock onwards (GET /events?since=) and in
// full: the cap covers two match runs with room to spare, and a feed longer than the cap fails loudly
// instead of being truncated. The same `since` goes on every page (a cursor is bound to it).
const EVENT_PAGE_LIMIT = 200;
const MAX_EVENT_PAGES = 250;

async function apiClock(request: APIRequestContext): Promise<string> {
  const res = await request.get(`${API_BASE}/api/v1/health`);
  const header = res.headers()['date'];
  if (!header) throw new Error('GET /health returned no Date header; cannot take the API clock');
  // second precision, explicit UTC offset (a naive timestamp would be read as UTC anyway)
  return new Date(header).toISOString().replace('Z', '+00:00');
}

async function eventCounts(request: APIRequestContext, since: string): Promise<Record<string, number>> {
  const counts: Record<string, number> = {};
  let cursor: string | null = null;
  for (let page = 0; page < MAX_EVENT_PAGES; page++) {
    const query = `since=${encodeURIComponent(since)}&limit=${EVENT_PAGE_LIMIT}` +
      (cursor ? `&cursor=${encodeURIComponent(cursor)}` : '');
    const res = await request.get(`${API_BASE}/api/v1/events?${query}`);
    expect(res.status(), 'GET /events must answer 200').toBe(200);
    const body = (await res.json()) as { items: Array<{ eventType: string }>; nextCursor: string | null };
    for (const row of body.items) {
      const key = row.eventType.toLowerCase();
      counts[key] = (counts[key] ?? 0) + 1;
    }
    cursor = body.nextCursor;
    if (!cursor) return counts;
  }
  throw new Error(`GET /events since ${since} has more than ${MAX_EVENT_PAGES * EVENT_PAGE_LIMIT} rows`);
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

    const since = await apiClock(request);
    const before = await eventCounts(request, since);
    await page.goto('/');
    await expect(byId(page, T.modeBadge)).toBeVisible();

    // 1. reset: the hero session is rebuilt and two source cards render
    await byId(page, T.resetButton).click();
    const cards = byId(page, T.sourceCard);
    await expect(cards).toHaveCount(2);
    for (const system of ['ER_FHIR', 'CLINIC_CSV']) {
      const card = page.locator(`[data-testid="${T.sourceCard}"][data-source-system="${system}"]`);
      await expect(card).toHaveCount(1);
      const hero = heroRecord(system as 'ER_FHIR' | 'CLINIC_CSV');
      await expectShowsName(card, hero.given_name, `${system} card`);
      await expectShowsName(card, hero.family_name, `${system} card`);
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
    // the golden record is the hero's: its given name, and the family name from either source
    // (survivorship picks one; W3b owns that rule)
    const golden = byId(page, T.goldenRecord);
    await expectShowsName(golden, heroRecord('CLINIC_CSV').given_name ?? heroRecord('ER_FHIR').given_name, 'golden record');
    await expect.poll(async () => {
      const text = nameKey(await golden.innerText());
      return [heroRecord('ER_FHIR').family_name, heroRecord('CLINIC_CSV').family_name]
        .some((n) => n !== null && text.includes(nameKey(n)));
    }, { message: "golden record shows one of the hero's family names" }).toBe(true);
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
    const after = await eventCounts(request, since);
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
