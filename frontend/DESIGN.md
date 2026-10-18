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
AUTO-LINK `bg-band-auto text-on-band-auto` + Check · REVIEW `bg-band-review text-on-band-review` + Eye · KEEP SEPARATE `bg-band-keep text-on-band-keep` + Split. Label text is always shown. In a queue row the chip sits right of the score.

## Gate card ("Blocked by identity gate") — amber, firm, calm

`rounded-lg border border-denied-border border-l-[6px] border-l-gate-bar bg-gate-bg px-5 py-4` . Heading 24/32 600 `text-ink-1` with a ShieldAlert icon in `text-denied-ink`. Reason sentence in body. Inner masked-candidate card `rounded-md border border-border-subtle bg-surface`. No red, no shake, no glow. Amber says "REVIEW caused this".

## Flag card ("Flagged for clinician review") — neutral

`rounded-lg border-2 border-ink-1 border-l-[6px] border-l-band-keep bg-surface p-4`, Flag icon, heading as section label. Constructed-scenario chip in the header when the API says so. No `role="alert"`; announce through the polite live region. Quiet states (no flag yet, no link, not available, rule silent) are an outlined neutral card in `FlagCard.tsx`. Target for the polish pass (audit #3, in review): body `max-w-[68ch]`, the rule id once in the header, quiet states `border-border-subtle bg-sunken text-[16px]` with a 16 px Flag icon. Allergy cards have no special colour: diamond marker, 4 px `ink-1` left bar, provenance chip.

## Buttons

Primary `h-11|h-12 rounded-md bg-accent px-4|px-6 font-semibold text-on-accent hover:bg-accent-hover disabled:bg-sunken disabled:text-ink-3`.
Secondary `… border border-border-strong bg-surface text-ink-1 hover:bg-sunken disabled:text-ink-3`.
Ghost/link `font-semibold text-accent underline underline-offset-2`. Busy label replaces text ("Linking..."); both decision buttons disable. One primary per region.

## Focus

Global `:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px }`. Never `outline-none` without a visible replacement. After Approve, focus moves to the new record's heading (`tabIndex={-1}`).

## Motion (tokens in globals.css)

`--dur-fast` 150 ms (colour/fill crossfades, every reduced-motion fade) · `--dur-base` 200 ms (small changes) · `--dur-enter` 250 ms (rows and cards entering) · `--dur-move` 300 ms (on-screen moves, the collapse) · `--stagger` 40 ms between list items. Easing `--ease-out-strong` for entrances; `--ease-in-out-strong: cubic-bezier(0.77,0,0.175,1)` for on-screen moves. Never ease-in, never `scale(0)` (start at 0.95–0.98).

- Collapse after Approve: use the `.enter` class (opacity + translateY(-8px) scale(.95) → rest, 300 ms) for the golden record, `.enter enter-late` (400 ms delay) for the timeline, `.enter enter-last` (700 ms) for the flag card. No optimistic reveal: animate only after the server confirms.
- Band change: chip text and colour swap with no transition; bars ease width 150 ms after the number swaps; changed bar gets a static 2 px `ink-1` outline until the next action.
- New queue row: opacity + translateX(16px) → 0 over `--dur-enter`, `--ease-out-strong`; counts swap with no transition; stagger `--stagger` for at most the first 5 rows.
- CSS transitions only (they retarget on Reset); keyframes only for indeterminate progress.
- `prefers-reduced-motion: reduce`: opacity only at 150 ms, no translate/scale/stagger, keep static outlines.

## Layout

Max content 1440 px, `p-4` gutter. Case: `grid-cols-[1fr_28rem]`, one column at `max-[1100px]`. FrontDesk: `grid-cols-[600px_1fr]`, one column at `max-[1100px]`. Phone (`max-[640px]`): the target is no horizontal scroll at 390 px. Today the header does not wrap and Case keeps two source cards side by side (audit #11, pending), so a new screen must not add width: let its own rows wrap and give grid children `min-w-0`. Short laptop (`max-height:700px`): `.short-screen-hidden` / `.short-screen-only` keep decision buttons above the fold.

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

Placement decided by the UX lead (Christian Flores, design squad, UX lead). The queue is the registrar's backlog, not a stop on the judge's path: Case stays at `/` with every data-testid unchanged, FrontDesk stays first, and the queue goes third. It never decides anything; Approve and Reject stay on Case (the FrontDesk registrar handoff gets its own, later).

1. Route `/queue`, new file `app/queue/page.tsx`. Add `{ href: "/queue", label: "Work queue" }` to `TABS` in `components/ui/Header.tsx` after Case. Final order: FrontDesk, Case, Work queue. Do not touch `/` or `/frontdesk`. The third tab widens a header that does not wrap yet (audit #11); keep the label "Work queue" and check 1366 px still fits on one row.
2. Data path. Add two reads to `DataSource` (`src/data/source.ts`) and implement both in each adapter:
   - `getReviewQueue(cursor?: string): Promise<{ items: CandidatePair[]; nextCursor: string | null }>`. `ApiSource`: `GET /api/v1/candidate-pairs?band=REVIEW&status=PROPOSED&limit=50&cursor=…` through the generated client; send `band` and `status` again with every cursor, because the cursor does not carry them. `FixtureSource`: one item, the fixture pair, once Resolve has run and while its decision is `PROPOSED`; none before Resolve or after a decision, matching Case. Add `export type CandidatePair = Schemas["CandidatePair"]` to `src/api/types.ts` (an alias of the generated type, never hand-written).
   - `getCandidatePair(id: string): Promise<CandidatePairDetail>`. `ApiSource`: `GET /api/v1/candidate-pairs/{pair_id}`. `FixtureSource`: the fixture's pair detail for its pair id, `DataError("NOT_FOUND")` otherwise.
   - Both endpoints are in the frozen contract, so no contract change. Existing methods, their calls and the Case screen's reads stay exactly as they are.
3. Order: keep the server's order ("most uncertain first", `|p − 0.5|`) and say so in the header line. Don't re-sort on the client: "Load more" appends the next page: use `useInfiniteQuery` with `nextCursor` as the page param.
4. Collapsed row, 56 px minimum, built only from the list item:
   - the band chip (`BandChip`, text and icon);
   - `p` as a two-decimal number (tabular), labelled "Probability estimate" with the Case caption "fitted on our synthetic development distribution" (never a bare "Probability"), display only;
   - the origin as "Match run" or "FrontDesk hand-off";
   - the age from `decision.decidedAt` ("waiting 3 m"); in REPLAY the fixture time is fixed, so show the CT time ("scored 13:00 CT") instead of an age;
   - a short pair id (mono, first 8 characters).
5. Expanded row: call `getCandidatePair(id)` for that row only, on expand. Show the two source names (`recordA` and `recordB` `displayLabel` and names), then the top 3 rows from `rankContributions(detail.contributions)`. It returns plain labels once PR #23 (evidence-rail labels for every scorer id) merges; until then live ids such as `given_jw_folded` show raw, as on Case.
6. The Case pair: a row with `origin === "MATCH_RUN"` whose `recordAId` and `recordBId` are the session's two `sources[].record.id` (from `getSession()`, in either order) gets a secondary **Open in Case** link to `/`. Other rows have no decision buttons. Case doesn't read a `?pair=` parameter. Adding one changes Case data flow and is a fork for the lead.
7. States:
   - empty: "No pairs need a registrar. Resolve identity on Case scores the loaded records." (`ink-3`);
   - loading: row skeletons with `aria-busy`;
   - error: "Work queue unavailable: {reason}. Nothing was changed." with a **Try again** button that refetches.

   No red, no `role="alert"`. Testids are new only, prefixed `work-queue-`.

8. Refresh: TanStack Query refetches on mount and on window focus; there's no `refetchInterval`. Reset demo needs no special handling.
9. Done when: the build is green, the G16 acceptance script passes unchanged, and a Playwright check shows the tab, at least one REVIEW row after Resolve, and **Open in Case** landing on `/` with `resolve-button` visible.
