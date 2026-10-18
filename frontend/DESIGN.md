# CheckMate design rules: the living record

Christian Flores (L1 shell builder) · 2026-10-18 · for every frontend lane on `lane/redesign`
Source of truth: `src/app/globals.css` (tokens, the Desk geometry) and the redesign concept (`CONCEPT.md` §3–§5, `BUILD-SPEC.md`). Where they disagree, globals.css wins for what exists; BUILD-SPEC wins for what is missing. This file replaces the 2026-10-17 rules (calm clinical, teal accent, IBM Plex); the last section lists each rule it replaces.

## Principles

1. One screen tells the story. `/` is the Desk: the patient's kiosk on the left, the registrar's stage on the right, a top bar above. The window never scrolls; regions scroll inside themselves.
2. One colour means one thing. Mulberry is this person's record and the one action that commits to it. Ink is neutral action. Amber is "the gate said no". The clinician flag is paper and ink. Nothing is red.
3. Type carries the hierarchy: a display face for names, titles and the score; a text face for everything else; mono only for ids, times and evidence values.
4. Every meaning has words plus a shape (bands, gate outcomes, mode, flag, story step), never colour alone.
5. Motion marks a real state change. There is one orchestrated moment (the link); everything else is a 120–220 ms state change, and every animation has a reduced-motion fallback.
6. Show the machine's work honestly: plain words in headlines, raw codes only in expanded detail on the registrar side, never in the patient's kiosk.

## Colour tokens (use the Tailwind name, never a hex)

| Tailwind                                                  | CSS var           | Hex                               | Role                                                            |
| --------------------------------------------------------- | ----------------- | --------------------------------- | --------------------------------------------------------------- |
| `bg-porcelain`                                            | `--porcelain`     | `#F5F3F4`                         | Page                                                            |
| `bg-paper`                                                | `--paper`         | `#FFFFFF`                         | Kiosk device, sheets, the flag notice                           |
| `text-ink`, `bg-ink`                                      | `--ink`           | `#1B1419`                         | Text, neutral primary buttons, focus ring (16.4:1 on porcelain) |
| `text-ink-2`                                              | `--ink-2`         | `#5C5259`                         | Secondary text (6.8:1 on porcelain)                             |
| `text-ink-3`                                              | `--ink-3`         | `#73686F`                         | Tertiary text, placeholders; the floor (4.8:1 on porcelain)     |
| `border-hair` / `border-hair-strong`                      | `--hair*`         | `#E6E0E4` / `#8E8389`             | Dividers / input and control borders (3.6:1 on paper)           |
| `bg-mulberry`, `text-mulberry`                            | `--mulberry`      | `#8C1D7E`                         | The record; Send, Approve, Confirm link (white on it 8.1:1)     |
| `bg-mulberry-deep`                                        | `--mulberry-deep` | `#5E1254`                         | Hover and pressed; text on tint                                 |
| `bg-mulberry-tint`                                        | `--mulberry-tint` | `#F4E3F0`                         | A fragment: the record before it is whole                       |
| `bg-mulberry-cite`                                        | `--mulberry-cite` | `#EBC6E4`                         | Hover-to-cite wash                                              |
| `text-on-mulberry-2`                                      | `--on-mulberry-2` | white 80%                         | Secondary text on the record                                    |
| `bg-glow`                                                 | `--glow`          | `#B98BE0`                         | The kiosk's working glow, edge only, never text                 |
| `bg-amber-surface`, `border-amber-line`, `text-amber-ink` | `--amber-*`       | `#FFF3D6` / `#E0A526` / `#6B4300` | The gate card only, once per denial                             |
| `bg-scrim`                                                | `--scrim`         | ink 18%                           | Behind the command bar and sheets                               |

- **Projector fallback.** If the venue projector washes mulberry toward pink, change `--mulberry` to `#7A1A6E` (one value in `:root`; everything else follows) and re-run `contrast.test.ts`.
- Mulberry has hue 308°, so it is not red. Pairs that are not records (the band stamp, the evidence dots) are drawn in ink.
- `contrast.test.ts` reads the hex values in `:root` and checks every pair above at AA.
- Dark mode is not built; the venue runs light and `data-theme="light"` is pinned. Reserved values: page `#151014`, paper `#1F181D`, ink `#F3EEF1`, mulberry `#C45AB4`.

### Legacy aliases (until each lane removes its last user)

Components the kiosk, Organism and decision lanes have not replaced still use the old Tailwind names. `@theme` in globals.css maps each one onto a new token so they render in the new palette. New code uses the new names only; a lane deletes an alias once nothing uses it.

| Old name                                                | Now           | Old name                                                                | Now           |
| ------------------------------------------------------- | ------------- | ----------------------------------------------------------------------- | ------------- |
| `page`, `sunken`, `error-bg`                            | porcelain     | `surface`, `kiosk`                                                      | paper         |
| `border-subtle`                                         | hair          | `border-strong`                                                         | hair-strong   |
| `ink-1`, `focus`, `banner`, `evidence-for`, `band-auto` | ink           | `error-ink`, `info`                                                     | ink-2         |
| `evidence-against`, `band-keep`                         | ink-3         | `band-review`, `on-band-auto`, `on-band-keep`, `on-banner`, `on-accent` | paper         |
| `accent`, `allowed-border`                              | mulberry      | `accent-hover`, `allowed-ink`                                           | mulberry-deep |
| `accent-soft`, `allowed-bg`                             | mulberry-tint | `denied-bg`, `gate-bg`                                                  | amber-surface |
| `denied-border`, `gate-bar`                             | amber-line    | `denied-ink`                                                            | amber-ink     |
| `on-band-review`                                        | ink           |                                                                         |               |

## Type (self-hosted through `@fontsource`; no `next/font`, no runtime network call)

| Style                    | Font                                 | Size / line                    | Weight  | Tracking |
| ------------------------ | ------------------------------------ | ------------------------------ | ------- | -------- |
| Stage title              | `font-display` (Bricolage Grotesque) | 60/60, 44 in the compact layer | 720     | -0.035em |
| Score                    | display, `tabular-nums`              | 64/58                          | 700     | -0.04em  |
| Record name (joined)     | display                              | 46/46                          | 700     | -0.035em |
| Kiosk headline           | display                              | 44/45                          | 700     | -0.03em  |
| Fragment name            | display                              | 30/32                          | 650     | -0.025em |
| Pane title, wordmark     | display                              | 26/29; wordmark 22             | 650–680 | -0.02em  |
| Kiosk body               | `font-sans` (Instrument Sans)        | 18–20/1.4, never below 18      | 400–650 | 0        |
| Stage body               | sans                                 | 16–18/1.45                     | 400     | 0        |
| Labels, captions, header | sans                                 | 13–15                          | 500–600 | 0        |
| Ids, times, values       | `font-mono` (DM Mono)                | 13–14                          | 400–500 | 0        |

No all-caps labels in the top bar. The only uppercase is the band stamp `REVIEW` (the canonical enum; G16 matches it case-sensitively). Names wrap and never truncate.

## Shape and spacing

`rounded-record` 36 px (the record), `rounded-device` 32 px (the kiosk device), `rounded-control` 14 px (buttons, inputs), `rounded-small` 8 px. No pills. Buttons are rounded rectangles, 52 px tall on the stage and 56 px on the kiosk; hit targets at least 44 px. Crosswalk chips hang from the record's bottom edge. Resting surfaces have no shadow except the kiosk device; floating layers (command bar, sheets, tooltips) do.

## The Desk (`/`; `/frontdesk` redirects here)

Fixed geometry in `:root`, so nothing jumps between states:

| Region                      | 1440x900                 | Compact layer (`max-width: 1300px` or `max-height: 760px`; measured at 1280x720) |
| --------------------------- | ------------------------ | -------------------------------------------------------------------------------- |
| Top bar `--bar-h`           | 64                       | 64                                                                               |
| Kiosk device `--kiosk-w`    | 456 x 812                | 400 x 632                                                                        |
| Stage head `--stage-head-h` | 170                      | 118 (title 44)                                                                   |
| Organism slot               | 600 x 520                | 516 x 447 (`.organism-scale` keeps the 600x520 drawing at 0.86)                  |
| Decision column             | 268 wide, scrolls inside | 264 wide, scrolls inside                                                         |
| Activity strip `--strip-h`  | 60                       | 52                                                                               |
| Window scroll (y, x)        | 0, 0                     | 0, 0                                                                             |

- The Organism sits in `.organism-slot > .organism-scale`. The decision column and the kiosk scroll inside themselves; the gate card and the registrar's Approve are scrolled into view when they appear (`scrollIntoView({ block: "nearest" })` on an element without an entrance transform).
- The stage head is an eyebrow (state, live "held m:ss"), a 60 px title and one consequence line, from `stageHead()` in `lib/desk.ts`. Every name comes from the data.
- The Activity strip shows the three newest event groups; "All activity" opens a drawer that is always mounted (`hidden` when closed) and carries one `event-row` per event. The strip also holds the gate tile (`tile-agent-gate`) and the human-review meter (`tile-human-review`).
- `DeskState` (`idle`, `held`, `review`, `confirm`, `rejected`, `linked`) is derived once in `DeskContext` from the case and the kiosk. Lanes read it with `useDesk()`, set the kiosk with `setKiosk`, open the confirm with `setSheet`, and expose actions to the keycaps and ⌘K with `useDeskAction(name, fn)`.

## Top bar

Left to right: the mark and "CheckMate" with **"Synthetic data. Not for clinical use."** directly under the wordmark (always visible, never clipped, `whitespace-nowrap`); the story stepper; then the provisional badge (fixture only), the mode badge ("Replay"/"Local", testid `app-mode-badge`), Commands ⌘K and Reset demo ⇧R. **No tabs.** The work queue opens from ⌘K ("Open work queue", and "Open the Desk" on the way back), or the wordmark links home.

- **Story stepper**: Check-in, Rules gate, Compare, Link, Clinician flag. `currentStep(desk, kiosk, flagRaised)` picks the current step; earlier steps show a check, later ones an empty ring. The current step has `aria-current="step"` and a visually hidden ", current step". Labels stay on one line; the compact layer drops the label size to 13 px and shortens the rules.
- **Mark** (`components/ui/Mark.tsx`, from the assets lane): two half-discs in `currentColor`, `state="open"` with a 2 px gap, `state="closed"` once the Desk is `linked`. The 404 draws it with `className="mark-apart"`.
- **Keys**: ⌘K (command bar) and ⇧R (Reset demo) work on every route; on the Desk R resolves, A approves, X rejects, Enter confirms, Esc cancels. Single-letter keys never fire inside a text field.

## Gate card, flag notice, band stamp

- **Gate card** (kiosk and registrar): amber surface, amber line, amber ink; firm and calm, no shake, no glow. Headline in plain words; the reason code only in expanded detail on the registrar side.
- **Flag notice**: white paper on the record, ink text, an outline flag glyph, "flagged for clinician review". Never `role="alert"`, never red, never the never-say words; announced through the one polite live region. The constructed-scenario chip stays.
- **Band stamp**: ink, the canonical enum text (`REVIEW`), never colour alone.

## Motion

Tokens: `--ease-out` (arrivals, the rise), `--ease-fuse` (the morph), `--ease-spring` (nodes, the gate card); `--t-micro` 120 ms, `--t-state` 220 ms, `--t-rise` 520 ms, `--t-fuse` 720 ms. Use them as `duration-[var(--t-state)] ease-[var(--ease-out)]`. Under `prefers-reduced-motion: reduce` all four durations are 0 ms in `:root`, the morph becomes a crossfade and every timer is skipped. The link sequence (CONCEPT.md §4) animates only after the server confirms the approval. No pulsing, confetti or sparkle icons.

## Focus and accessibility

Global `:focus-visible` is a 2 px ink ring, 3 px off the control; on a mulberry surface (`.on-mulberry`) the ring is paper. Never `outline-none` without a visible replacement, except a programmatic `tabIndex={-1}` target. After Approve, focus moves to the flag notice's heading when the approval raised a flag, otherwise to the record's heading. One polite live region (`LiveRegion`). Every token pair passes AA.

## Do / don't

- Do use the Tailwind names above; don't add a hex to a component.
- Do keep every `data-testid` G16 reads (`app-mode-badge`, `reset-button`, `resolve-button`, `candidate-pair`, `pair-band`, `approve-button`, `review-submit-button`, `event-row`, the tiles); add new ones, never rename.
- Do label every state in words; do show "not given" for missing values.
- Don't use red, pink or an error colour anywhere, and don't use amber for anything but the gate.
- Don't say "Flagged" as a column name ("Needs registrar"), "thinking", "prevented", "diagnosed" or "calibrated" on screen. The product name is CheckMate.
- Don't change data flow, API calls or the generated client from a visual change; don't hand-write API types.
- Don't add a package without a line in the PR (allowed: `motion`, `cmdk`, the three `@fontsource` packages).

## Work queue (`/queue`, `/queue/[pairId]`)

The registrar's backlog, not a stop on the judge's path. It opens from ⌘K. Read-only (GETs only, no refetch on focus, never posts a match run); the funnel comes from the newest Resolve receipt this tab holds (`LATEST_MATCH_RUN_KEY`), otherwise LOCAL says "Press Resolve identity on the Desk to see the match-run funnel." and REPLAY says the scenario comes already scored. Server order ("most uncertain first"), 12 rows a page, Previous / Next over `nextCursor`. A row shows the two names, the band, `p` to two decimals under "Probability estimate" (captioned "fitted on our synthetic development distribution"), the status and the origin. A row opens `/queue/{pairId}`, where Approve and Reject each take a confirm step and record the registrar label. Testids are prefixed `work-queue-`.

## Rules this file replaces (2026-10-17 → 2026-10-18)

1. "Calm clinical: warm off-white page, white cards, one teal accent" → porcelain page, paper device and sheets, mulberry for the record and its committing action only.
2. Accent `bg-accent` (teal) for every primary button → ink for neutral primaries, mulberry only for Send, Approve and Confirm link.
3. "Amber is reserved for the gate and the REVIEW band" → amber is the gate card only; the REVIEW band stamp is ink.
4. Band chips in three colours with icons → one ink band stamp with the enum text.
5. Flag card with a 2 px ink border and a coloured left bar → the flag notice, white on the record, ink text, outline glyph.
6. Gate card with a 6 px left bar and a ShieldAlert icon → amber surface, amber line, amber ink, plain-words headline.
7. IBM Plex Sans and Mono through `next/font` → Bricolage Grotesque, Instrument Sans and DM Mono through `@fontsource` (no network fetch at build).
8. Type scale 14–56 px with uppercase section labels → the scale above; no uppercase except the band stamp.
9. Radii 4/6/8 px maximum → 36/32/14/8 px; buttons 52 px on the stage, 56 px on the kiosk.
10. Motion tokens `--dur-*` and `--ease-*-strong`, the `.enter` collapse → `--t-*` and `--ease-out|fuse|spring`, the orchestrated link moment.
11. Header tabs (FrontDesk, Case, Work queue; `TABS` in `Header.tsx`) and a full-width synthetic-data banner → no tabs, the synthetic-data sentence under the wordmark, the story stepper, the queue in ⌘K.
12. Case at `/` and FrontDesk at `/frontdesk` as two screens → one Desk at `/`; `/frontdesk` redirects.
13. Two-column `.pane-layout` with a 1100 px breakpoint and `.short-screen-*` helpers on the Desk → the fixed Desk geometry and its compact layer (the pane rules now apply to the queue's pair page only).
14. Light and dark token blocks kept in step → light only; dark values reserved above.
15. Focus ring in `--focus` (teal-ink), 2 px offset → ink ring, 3 px offset, paper on mulberry.
