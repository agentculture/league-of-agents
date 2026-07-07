# Replay design rationale

The self-contained HTML replay (`league/replay/html.py`) is designed with the
`dataviz` method: color is assigned by job, both themes are deliberately
stepped, and motion is purposeful and reduced-motion-safe. This page records the
decisions, the validated palette, and the anti-pattern audit so the design is
contestable rather than taken on faith. It describes the renderer as merged —
not an aspiration for a future cycle.

The renderer stays a single self-contained file: all CSS/JS is inline, there are
no external requests (`url(`, `@import`, `fetch`, CDN, or remote fonts), and the
same log renders **byte-identical** HTML — animation is CSS-timed, never baked
into generation, so no `Date.now`/`Math.random` leaks into the document.

## Color by job

Every color does exactly one job (`dataviz` color-formula). Nothing is
eyeballed.

| Job | Encodes | Colors |
|-----|---------|--------|
| Categorical | team identity | slot 1 blue, slot 6 red (validated pair) |
| Ownership tint | who holds a control point | the owner's team hue at ~24% |
| Element hue | resources (a fixed game element) | aqua, on a distinct diamond mark |
| Status | event moments (good / bad) | good `#0ca30c`, critical `#d03b3b` |
| Text tokens | all labels and values | primary / secondary / muted ink |

Rules held: **text never wears a team color** — identity rides a colored swatch,
dot, or mark *beside* the text (team names, score headers, and mission labels
all use ink tokens with a swatch). **Status never impersonates a team** — the
status reds/greens are distinct hexes from the team hues and are only used on
event glyphs, always paired with an icon and a label.

### Team categorical palette (validated)

| Slot | Light | Dark |
|------|-------|------|
| Team 0 (blue) | `#2a78d6` | `#3987e5` |
| Team 1 (red) | `#e34948` | `#e66767` |

Extra team slots (only used at 3+ teams) come from the same validated
categorical order: orange `#eb6834`/`#d95926`, violet `#4a3aa7`/`#9085e9`,
magenta `#e87ba4`/`#d55181`, yellow `#eda100`/`#c98500`.

Resource element hue: aqua `#1baf7a` (light) / `#199e70` (dark). Status scale
(fixed, never themed): good `#0ca30c`, warning `#fab219`, serious `#ec835a`,
critical `#d03b3b`.

### Validation result (`validate_palette.js`)

Team pair, run once per mode against the actual surfaces:

```text
node validate_palette.js "#2a78d6,#e34948" --mode light
  [PASS] Lightness band · [PASS] Chroma floor
  [PASS] CVD separation  worst adjacent ΔE 74.6 (protan)
  [PASS] Contrast vs surface (all >= 3:1)   → ALL CHECKS PASS

node validate_palette.js "#3987e5,#e66767" --mode dark --surface "#1a1a19"
  [PASS] Lightness band · [PASS] Chroma floor
  [PASS] CVD separation  worst adjacent ΔE 66.4 (protan)
  [PASS] Contrast vs surface (all >= 3:1)   → ALL CHECKS PASS
```

The team pair passes all six checks cleanly in both modes. When resource-aqua is
added as a third board mark (`--pairs all`, since a unit can stand on a node),
two WARN bands appear and are mitigated by secondary encoding that is already
present:

- Light: aqua contrast is 2.74:1 (< 3:1). Relief required — resource nodes carry
  a white numeric count label, the sanctioned relief channel.
- Dark: aqua↔red CVD ΔE 9.7 (the 8–12 floor band). Legal only with secondary
  encoding — resources are a **diamond** mark, never a round unit, and are always
  numerically labeled, so shape + label carry identity where hue is tight.

These are the reference palette's own pre-validated values, used verbatim from
`references/palette.md`; the runnable validator confirmed the team pair above.

## Theme decisions

Both themes are **selected steps, not an auto-flip**. Each ships its own surface,
ink, elevation, grid, and stepped team hues — the dark hues are the palette's
dark column (chosen for the dark band), not a filter over the light ones.

- `prefers-color-scheme` picks the default theme.
- A manual toggle stamps `data-theme="dark"` / `data-theme="light"` on the root,
  and those blocks re-declare the full token set so the toggle **wins in both
  directions** regardless of the OS preference.
- Depth is a designed, per-theme token: light mode uses soft cast shadows; dark
  mode uses a faint inset top highlight plus a deeper shadow, so elevation reads
  correctly on each surface. The board is the hero — it carries the strongest
  elevation (`--shadow-hero`).

## Motion inventory

All motion lives behind `@media (prefers-reduced-motion: no-preference)` in
effect: a single `prefers-reduced-motion: reduce` block collapses every
transition and animation, and the JS skips spawning celebration effects when
reduced motion is requested.

| Moment | Motion | Restraint |
|--------|--------|-----------|
| Unit movement between turns | the same node glides via a `transform` transition (`--move`, speed-scaled) | position interpolation only; first paint lands at rest before transitions arm |
| Fresh capture | the control disc floods in and a soft ring pulses in the new owner's hue | one ring, ~0.9s, forward step only |
| Delivery | a `good`-green flash at the delivering unit | ~1s, fades out |
| Mission completion | a larger `good` ring plus a flash at the target | ~1.15s |
| Unit defeat | a `critical`-red ring at the unit's cell | ~0.9s |
| Playback | play/pause with 0.5× / 1× / 2× speed | glide duration tracks the chosen speed |

Effects only fire on a **forward** step (play or next), never on a scrub or a
reverse, and their placement is fully determined by the log — timing is the only
time-based element, which is permitted.

## Anti-pattern checklist

Checked against every entry in `references/anti-patterns.md`; result: **zero
hits**.

- Color & encoding: no dual-axis, no recolor-on-filter (color follows the team,
  not its row), no hue cycling past 8, no eyeballed CVD (validator run), no
  value-ramp on nominal categories, no hue at a diverging midpoint, no status
  color on a non-status series.
- Form: the board is the hero (no "eight hues for one number"), no one-bar chart,
  no donut, no more than ~7 meaningful color classes.
- Marks & chrome: thin marks with a hairline **solid** grid (no dashed
  gridlines), a 2px surface ring on unit markers, generous padding; the team
  panel is the legend (a swatch per team, always present for two series);
  labels are selective, never one-per-point; no borders drawn to separate marks;
  the system sans is used everywhere including the winner chip; `tabular-nums`
  is reserved for aligned columns (scores, the turn counter), not display
  numbers.
- Interaction & accessibility: every value is reachable without hover (the score
  table, direct feed text, and unit `title`s), the transport buttons meet the
  hit-target minimum, and all motion is reduced-motion-safe.

## Continuous face (minimal, cycle 7)

Cycle 7 (`league/engine/continuous/`) added a second engine lane with its own
event vocabulary and fixed-point (milliunit) positions. `league/replay/chtml.py`
is its replay face — plan task C7-t9, spec c12/c2 — read beside `html.py`
above, never over it: the grid face and this file are both untouched by the
other (spec c11/h11, two lanes, both honest).

**Frame v4 is pinned here as minimal-but-real.** The mesmerizing/video
generalization this repo's replay conventions otherwise favor — tweened unit
motion, a play/pause transport, the dual light/dark token system with a manual
toggle, GIF/video export — is deliberately parked for a later cycle. `chtml.py`
imports only the grid face's already-validated color constants
(`TEAM_COLORS`, `STATUS_GOOD`, `STATUS_CRITICAL`, `RESOURCE_COLOR`); it does not
port or reimplement any of `html.py`'s tween/GIF/theme machinery, so the two
faces stay genuinely independent.

What ships instead is the honest minimum the acceptance criteria name:

- A **header** with match id, scenario, seed, mode, time limit, and the final
  status/winner/outcome points.
- An **event timeline** listing every event in canonical `(game_time, seq)`
  order, each row timestamped with its integer game time. This is where a race
  — a faster agent snatching a contested control point mid-capture — must read
  clearly: a `post_taken` row always carries the `race-win` CSS class (and the
  fixed status-good color), an `action_failed` row always carries the
  `race-fail` class (and the fixed status-critical color) — two unmistakably
  distinct, differently-styled moments, never merged into one ambiguous line.
- A **static sequence of board snapshots**, one per distinct game-time step,
  server-rendered as plain inline SVG (positions scaled down from the engine's
  exact milliunits — never interpolated or tweened). A contested control point
  draws one dashed ring per concurrent taker in that taker's own team color, so
  the instant both racers are mid-take is visible on the board too, not only in
  the feed — the engine already represents a race that way in state
  (`CControlPoint.takers`; see `league/engine/continuous/state.py`), and the
  face only has to draw what is already there. The spec explicitly allows a
  static sequence in place of a scrubber, so no client-side stepping JS ships.

**Determinism and self-containedness** hold the same way as the grid face:
every fact is derived once via `fold_events`/`apply_event` (the log is the
single source of truth; the renderer never recomputes game logic), there is no
`Date.now`/`Math.random` and no external request of any kind, and the whole
page is one self-contained file — the same log renders byte-identical HTML
every time (`tests/test_replay_chtml.py`).

**CLI wiring.** `league match replay` detects a continuous log two ways —
a match id starting with `CONTINUOUS_ID_PREFIX` (`"c-"`, the same discipline
continuous scenario ids use), or, regardless of naming, the log's own header
shape (`clock`/`width` for `CMatchState` vs `turn`/`grid_width` for the grid's
`MatchState`) — and routes to this face. No new verb was added; a grid log
that matches neither signal falls through to the untouched grid path,
byte-identical to before this task (`tests/test_cli_match_replay_continuous.py`
pins this both ways).
