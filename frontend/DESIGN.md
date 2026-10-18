# CheckMate design rules

Christian Flores (design squad, visual designer) · 2026-10-17 · for every frontend lane, including `lane/ui-queue`
Source of truth: `src/app/globals.css` (tokens) and ux-spec §6, §10. Where they disagree, globals.css wins for what exists; the spec wins for what is missing.

## Principles

1. Calm clinical. Warm off-white page, white cards, one teal accent for action. Amber is reserved for the identity gate and the REVIEW band. Nothing is red, ever.
2. Type carries hierarchy. Size and weight steps do the work: no coloured headings, gradients or decorative icons.
3. Every meaning has words plus an icon or shape, never colour alone (bands, allowed/denied, mode, flag).
4. Motion marks a real state change and nothing else.
5. Show the machine's work honestly: mono for codes and ids, plain words for people, "not given" for missing values. Names wrap and never truncate.

## Colour tokens (use the Tailwind name, never a hex)

| Tailwind                                                  | CSS var           | Role                                                         |
| --------------------------------------------------------- | ----------------- | ------------------------------------------------------------ |
| `bg-page`                                                 | `--page`          | App background                                               |
| `bg-surface`                                              | `--surface`       | Cards, panes, inputs                                         |
| `bg-sunken`                                               | `--sunken`        | Inset areas, disabled fills, "differs" tag, quiet states     |
| `bg-kiosk`                                                | `--kiosk-bg`      | Patient kiosk pane only                                      |
| `border-border-subtle`                                    | `--border-subtle` | Resting card and pane borders (decorative)                   |
| `border-border-strong`                                    | `--border-strong` | Inputs, secondary buttons, chips (3:1 UI)                    |
| `text-ink-1` / `-2` / `-3`                                | `--ink-*`         | Primary / secondary / muted text (ink-3 is the floor, 5.9:1) |
| `bg-accent`, `hover:bg-accent-hover`, `text-on-accent`    | `--accent*`       | Primary buttons, current tab underline                       |
| `bg-accent-soft`                                          | `--accent-soft`   | Selected row, ghost hover                                    |
| `outline-focus`                                           | `--focus`         | Focus ring                                                   |
| `bg-denied-bg`, `text-denied-ink`, `border-denied-border` | `--denied-*`      | Gate denial: chips, "Waiting" badge, gate card border        |
| `text-error-ink`, `bg-error-bg`                           | `--error-*`       | System errors (burnt orange, always with words)              |
| `bg-banner`, `text-on-banner`                             | `--banner-bg`     | Synthetic-data banner only                                   |
| `bg-evidence-for` / `bg-evidence-against`                 |                   | Evidence bars right / left of zero; never text colour        |
| `bg-band-auto` / `-review` / `-keep` + `text-on-band-*`   |                   | Band chips only                                              |

Gate, allowed, info and scrim tokens (ux-spec §10.2, light / dark), used as `bg-gate-bg`, `border-l-gate-bar`, `bg-allowed-bg`, `text-allowed-ink`, `border-allowed-border`, `text-info`, `bg-scrim`: `--gate-bg` #FFFBEB / #211C0E, `--gate-bar` #B7791F / #E3B341, `--allowed-bg` #E4F0EE / #12302C, `--allowed-ink` #0B5D57 / #7FD6CA, `--allowed-border` #0B5D57 / #3E9C90, `--info` #1D4E89 / #8EC1F2, `--scrim` rgba(17,24,39,.4) / rgba(0,0,0,.6).

Every colour that differs in dark mode is set in both dark blocks of `globals.css` (`prefers-color-scheme` and `[data-theme="dark"]`); a token not set there keeps its light value on purpose. Motion and easing tokens are theme-independent and are not in `@theme`: use them as `duration-[var(--dur-base)]`, `ease-[var(--ease-out-strong)]`. The venue runs light.

## Type (IBM Plex Sans; Plex Mono only for codes, ids, event types, tool names)

| Role                                                                                         | Classes                                                                        |
| -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Hero number                                                                                  | `text-[56px] leading-[60px] font-bold tracking-[-0.02em] tabular-nums`         |
| Number                                                                                       | `text-[32px] leading-[36px] font-semibold tabular-nums`                        |
| Title / wordmark                                                                             | `text-[24px] leading-[32px] font-semibold`                                     |
| Section label (SOURCES, QUEUE)                                                               | `text-[18px] leading-[24px] font-semibold uppercase tracking-wider`            |
| Body / values / buttons                                                                      | `text-[18px]` (body default, line-height 1.4), strong = `font-semibold`        |
| Pane label / tile heading                                                                    | `text-[16px] leading-[20px] font-semibold uppercase tracking-wider text-ink-3` |
| Caption / helper                                                                             | `text-[16px] text-ink-3`                                                       |
| Micro (chips, badges, footers, source lines only)                                            | `text-[14px] font-medium`                                                      |
| Mono / mono-sm                                                                               | `font-mono text-[16px]` / `font-mono text-[14px] text-ink-3`                   |
| Nothing a judge must read goes below 16 px. Numbers that change or align use `tabular-nums`. |

## Spacing, radii, elevation

4 px base on an 8 px rhythm: 4, 8, 12, 16, 24, 32, 48, 64 (`1 2 3 4 6 8 12 16` in Tailwind). Card padding `p-4`; between cards `gap-4`/`space-y-4`; between page sections 24; list rows `space-y-1` minimum.
Radii: `rounded` 4 chips/badges, `rounded-md` 6 buttons/inputs/inner cards, `rounded-lg` 8 cards/panes/toasts (maximum). Resting surfaces: border, no shadow. Shadows only on floating layers (tooltip, menu, dialog, toast).
Hit targets ≥ 44 px (`h-11`). Approve and Reject are 48 px (`h-12`) today, below the spec's 56 px, so the 1366x650 fold keeps both decision steps visible; new primary actions use `h-12`. Keep 8 px between targets.

## Band chips (`components/ui/BandChip.tsx`; reuse it, never restyle)

`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[14px] font-semibold` with a 16 px icon.
AUTO-LINK `bg-band-auto text-on-band-auto` + Check · REVIEW `bg-band-review text-on-band-review` + Eye · KEEP SEPARATE `bg-band-keep text-on-band-keep` + Split. Label text is always shown. In a queue row the chip comes first, before the score.

## Gate card ("Blocked by identity gate") — amber, firm, calm

Target (Q1.3, not built yet): `rounded-lg border border-denied-border border-l-[6px] border-l-gate-bar bg-gate-bg px-5 py-4` . Heading 24/32 600 `text-ink-1` with a ShieldAlert icon in `text-denied-ink`. Reason sentence in body. Inner masked-candidate card `rounded-md border border-border-subtle bg-surface`. No red, no shake, no glow. Amber says "REVIEW caused this".

## Flag card ("Flagged for clinician review") — neutral

`rounded-lg border-2 border-ink-1 border-l-[6px] border-l-band-keep bg-surface p-4`, Flag icon, heading as section label. Constructed-scenario chip in the header when the API says so. No `role="alert"`; announce through the polite live region. Quiet states (no flag yet, no link, not available, rule silent) are an outlined neutral card in `FlagCard.tsx`. Target for the polish pass (audit #3, in review): body `max-w-[68ch]`, the rule id once in the header, quiet states `border-border-subtle bg-sunken text-[16px]` with a 16 px Flag icon. Allergy cards have no special colour: today the timeline gives them a diamond marker (`Timeline.tsx`); the 4 px `ink-1` left bar and the provenance chip are a target, not built yet.

## Buttons

Primary `h-11|h-12 rounded-md bg-accent px-4|px-6 font-semibold text-on-accent hover:bg-accent-hover disabled:bg-sunken disabled:text-ink-3`.
Secondary `… border border-border-strong bg-surface text-ink-1 hover:bg-sunken disabled:text-ink-3`.
Ghost/link `font-semibold text-accent underline underline-offset-2`. Busy label replaces text ("Linking..."); both decision buttons disable. One primary per region.

## Focus

Global `:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px }`. Never `outline-none` without a visible replacement, except on a programmatic focus target (`tabIndex={-1}` heading or main), which is never reached by Tab. After Approve, focus moves to the new record's heading (`tabIndex={-1}`).

## Motion (tokens in globals.css)

`--dur-fast` 150 ms (colour/fill crossfades, every reduced-motion fade) · `--dur-base` 200 ms (small changes) · `--dur-enter` 250 ms (rows and cards entering) · `--dur-move` 300 ms (on-screen moves, the collapse) · `--stagger` 40 ms between list items. Easing `--ease-out-strong` for entrances; `--ease-in-out-strong: cubic-bezier(0.77,0,0.175,1)` for on-screen moves. Never ease-in, never `scale(0)` (start at 0.95–0.98).

- Collapse after Approve: use the `.enter` class (opacity + translateY(-8px) scale(.95) → rest, 300 ms) for the golden record, `.enter enter-late` (400 ms delay) for the timeline, `.enter enter-last` (700 ms) for the flag card. No optimistic reveal: animate only after the server confirms.
- Band change: chip text and colour swap with no transition; bars ease width 150 ms after the number swaps; changed bar gets a static 2 px `ink-1` outline until the next action.
- New queue row: opacity + translateX(16px) → 0 over `--dur-enter`, `--ease-out-strong`; counts swap with no transition; stagger `--stagger` for at most the first 5 rows.
- CSS transitions only (they retarget on Reset); keyframes only for indeterminate progress.
- `prefers-reduced-motion: reduce`: opacity only at 150 ms, no translate/scale/stagger, keep static outlines.

## Layout

Max content 1440 px, `p-4` gutter. Case: `grid-cols-[1fr_28rem]`, one column at `max-[1100px]`. FrontDesk: `grid-cols-[600px_1fr]`, one column at `max-[1100px]`. Phone (`max-[640px]`): the target is no horizontal scroll at 390 px. Today the header does not wrap and Case keeps two source cards side by side (audit #11, pending), so a new screen must not add width: let its own rows wrap and give grid children `min-w-0`. Short laptop (`max-height:700px`): `.short-screen-hidden` / `.short-screen-only` keep decision buttons above the fold.

Side by side (1100 px and wider), Case and FrontDesk do not scroll the page: each column scrolls on its own (`.pane-layout` on the grid, `.pane` on each column, in `globals.css`), so Approve, the flag card after Approve and the kiosk's newest message stay in view. Scroll a moment into view with `scrollIntoView({ block: "nearest" })` on an element without an entrance transform. FrontDesk stacked and portrait is the patient-facing kiosk: the staff pane is not displayed (`max-[1100px]:portrait:hidden`); stacked and landscape keeps both panes.

## Do / don't

- Do use tokens via Tailwind names; do add a NEW token to both dark blocks at once.
- Do label every state in words; do show "not given" for missing values; do wrap names.
- Do keep every `data-testid` exactly as it is; add new ones, never rename.
- Don't use red, pink or any error colour for a clinical flag; don't add `role="alert"` to the flag card.
- Don't use amber for anything but the gate and REVIEW ("Needs registrar" is ink on surface, not amber; never "Flagged").
- Don't change data flow, API calls or the generated client from a visual change; don't hand-write API types.
- Don't put shadows on resting cards, gradients, pulsing, confetti or "AI sparkle" icons.
- Don't say "thinking", "prevented", "diagnosed", "calibrated" on screen; the product name is CheckMate.

## Work queue (`lane/ui-queue`)

Placement decided by the UX lead (Christian Flores, design squad, UX lead). The queue is the registrar's backlog, not a stop on the judge's path: Case stays at `/` with every data-testid unchanged, FrontDesk stays first, and the queue goes third.

**Lead decision (2026-10-17, replaces the earlier "the queue never decides" rule):** Case opens for any stored pair, and a judge may decide any pair. Approve and Reject each take a confirm step and record the registrar label, Reject requires a reason (the note is optional on both), and every decision is logged, so opening a non-hero pair adds no unlogged path. A row opens `/queue/{pairId}`, which renders `CaseScreen` for that pair; `/` keeps binding the session's hero pair and reads no `?pair=` parameter.

1. Route `/queue` (`app/queue/page.tsx`) and `/queue/[pairId]` (`app/queue/[pairId]/page.tsx`). `TABS` in `components/ui/Header.tsx`: FrontDesk, Case, Work queue. Do not touch `/` or `/frontdesk`. The header wraps below 640 px; 1366 px fits on one row.
2. Data path. One `DataSource` for the whole build (`useState(createDataSource)` in `DataSourceProvider`); the queue never builds its own, so REPLAY stays REPLAY on every tab and Case keeps its state when you come back. Two reads on `DataSource`, implemented in each adapter:
   - `getCandidatePairs(query)`: one keyset page. `ApiSource`: `GET /api/v1/candidate-pairs?band=&status=&limit=12&cursor=…` through the generated client, re-sending the filters with every cursor because the cursor does not carry them. `FixtureSource`: the fixture pair with the session's current decision once Resolve has run (none before, as on Case), filtered by band and status the same way, `nextCursor: null`.
   - `getCandidatePair(id)`: `GET /api/v1/candidate-pairs/{pair_id}`; `FixtureSource` returns the fixture pair's detail with the session's decision and history, `DataError("NOT_FOUND")` for any other id.
   - Types are aliases of the generated ones (`CandidatePair`, `CandidatePairPage`, `MatchRunResponse`, `PairOrigin`). Both endpoints are in the frozen contract: no contract change.
3. Read-only. The queue sends GETs only and never refetches on window focus (`refetchOnWindowFocus: false`); it never posts a match run. The funnel comes from the newest Resolve response this tab already holds: `resolve()` returns the match-run receipt, Case's resolve mutation stores it under `LATEST_MATCH_RUN_KEY`, and the queue reads that key without a fetcher (`skipToken`). Reset and Undo drop it. With no receipt, LOCAL shows "Press Resolve identity on Case to see the match-run funnel."; REPLAY, which has no receipt, says the recorded scenario comes already scored. The funnel shows the oversized-block skip count when it is above zero.
4. Order: the server's ("most uncertain first", `|p − 0.5|`), said in the header line; no client re-sort. Paging is Previous / Next over `nextCursor`, 12 rows a page, filters reset to page 1.
5. Row, 56 px minimum, one link, no `aria-label` (its text is what a screen reader reads): the two names (from the row's detail read; "Name unavailable" if it fails), the band chip, `p` as a two-decimal tabular number, the status and the origin ("Match run" or "FrontDesk hand-off"). The column header says "Probability estimate" with the caption "fitted on our synthetic development distribution", once; never a bare percentage, never "calibrated" or "confidence". Band names use `BAND_LABELS` from `BandChip` everywhere on the screen.
6. States: empty "No candidate pairs yet. Resolve identity on Case scores the loaded records." (`ink-3`; with a filter set, "No candidate pairs match these filters."); loading with `aria-busy`; error "Work queue unavailable: {reason}. Nothing was changed." with **Try again**. No red, no `role="alert"`. Testids are new only, prefixed `work-queue-`.
7. Done when: the build is green, the G16 acceptance script passes unchanged, `e2e/work-queue.spec.ts` passes in REPLAY with no `/api/v1` request (Case → queue → Case keeps the golden record; a row opens Case for that pair), and `e2e/work-queue.api.spec.ts` shows no POST on open, focus or reload.
