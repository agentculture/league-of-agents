# Replay design rationale

The self-contained HTML replay (`league/replay/html.py`) and the offline GIF
(`league/replay/video.py`) are designed with the `dataviz` method: color is
assigned by job, both themes are deliberately stepped, and motion is purposeful
and reduced-motion-safe. This page records the decisions, the validated palette,
and the anti-pattern audit so the design is contestable rather than taken on
faith. It describes the renderers as merged — not an aspiration for a future
cycle.

> **Provenance — changed after the first human review of cycle 6.** The
> reviewer watched a live match and asked for three things, all recorded here:
> (1) retheme the surfaces and retire the blue/red team pair — light becomes
> **Anthropic cream**, dark becomes **Culture black-green**, teams become
> **clay vs violet**, and the GIF inherits the same vision (with a
> `--theme light|dark` flag); (2) make playback **feel 100% smooth** — the
> reviewer saw a per-turn accelerate–decelerate lurch instead of continuous
> movement; (3) move the assessor guide out of the bottom of the page into a
> **tabbed side panel** that uses the screen width and keeps the board in view
> (no scrolling between board and guide). Each is implemented below.

The HTML renderer stays a single self-contained file: all CSS/JS is inline,
there are no external requests (`url(`, `@import`, `fetch`, CDN, or remote
fonts), and the same log renders **byte-identical** HTML — animation is runtime
behavior (CSS timing flipped by play state at runtime), never baked into
generation, so no `Date.now`/`Math.random` leaks into the document. The GIF is
likewise a pure fold of the log at fixed parameters — byte-identical per
`--theme`/`--scale`/`--fps`/`--tween`.

## Color by job

Every color does exactly one job (`dataviz` color-formula). Nothing is
eyeballed.

| Job | Encodes | Colors |
|-----|---------|--------|
| Categorical | team identity | slot 0 clay, slot 1 violet (validated pair) |
| Ownership tint | who holds a control point | the owner's team hue at ~24% |
| Element hue | resources (a fixed game element) | aqua, on a distinct diamond mark |
| Status | event moments (good / bad) | good `#0ca30c`, critical `#d03b3b` |
| Chrome accent | interactive chrome (play, slider, links) | green — light `#1e7a4d` / dark `#46c79e` |
| Text tokens | all labels and values | primary / secondary / muted ink |

Rules held: **text never wears a team color** — identity rides a colored swatch,
dot, or mark *beside* the text (team names, score headers, and mission labels
all use ink tokens with a swatch). **Status never impersonates a team** — the
status reds/greens are distinct hexes from the team hues and are only used on
event glyphs, always paired with an icon and a label. **The chrome accent is not
a team** — the restrained green `--accent` dresses the play button, the slider,
the speed toggle, and the guide's deep-link affordances; it is a separate token
from every team hue and from the status green (a different hue family, and it
only ever appears on controls, never on a board mark).

### Team categorical palette (validated)

| Slot | Light | Dark |
|------|-------|------|
| Team 0 (clay) | `#b65b38` | `#cb6e44` |
| Team 1 (violet) | `#4b3ba6` | `#877ae0` |

Extra team slots (only used at 3+ teams) come from the same validated
categorical order — derived by enumerating orderings and keeping the one that
maximizes the minimum adjacent CVD ΔE (`color-formula.md` § Themes): teal
`#0e8f76`/`#1fa083`, blue `#2a78d6`/`#3987e5`, amber `#eda100`/`#c98500`,
magenta `#e87ba4`/`#d55181`. The full six-slot order is
`clay, violet, teal, blue, amber, magenta`.

Resource element hue: aqua `#1baf7a` (light) / `#199e70` (dark). Status scale
(fixed, never themed): good `#0ca30c`, warning `#fab219`, serious `#ec835a`,
critical `#d03b3b`. Chrome accent: green `#1e7a4d` (light) / `#46c79e` (dark),
with `--accent-ink` `#ffffff` (light) / `#06100c` (dark) for text on the accent.

Surfaces and ink, per theme (light = Anthropic cream, dark = Culture
black-green):

| Token | Light (cream) | Dark (black-green) |
|-------|---------------|--------------------|
| Page plane | `#f0eee5` | `#0c1210` |
| Card surface | `#faf8f1` | `#111a16` |
| Elevated surface | `#fffef9` | `#17231d` |
| Board plane (GIF + gradient) | `#ebe7dc` | `#0e1613` |
| Primary ink | `#242019` | `#eaf1ec` |
| Secondary ink | `#5a5546` | `#aebcb2` |
| Muted | `#8c8674` | `#788a7f` |
| Grid | `#ded9c9` | `#1e2a24` |
| Line | `#c3bba4` | `#2c3b33` |

### Validation result (`validate_palette.js`)

Team pair, run once per mode against the actual board surface the unit discs
render on:

```text
node validate_palette.js "#b65b38,#4b3ba6" --mode light --surface "#ebe7dc"
  [PASS] Lightness band · [PASS] Chroma floor
  [PASS] CVD separation  worst adjacent ΔE 86.7 (protan)
  [PASS] Contrast vs surface (all >= 3:1)   → ALL CHECKS PASS

node validate_palette.js "#cb6e44,#877ae0" --mode dark --surface "#0e1613"
  [PASS] Lightness band · [PASS] Chroma floor
  [PASS] CVD separation  worst adjacent ΔE 85.7 (protan)
  [PASS] Contrast vs surface (all >= 3:1)   → ALL CHECKS PASS
```

The team pair passes all six checks cleanly in both modes with a large margin
(worst adjacent CVD ΔE 86.7 light / 85.7 dark — well past the ≥ 12 target). The
full six-slot categorical order also passes all six in both modes (worst
adjacent ΔE 60.4 light / 53.9 dark); on the light surface two *extra* slots used
only at 5+ teams (amber, magenta) sit below 3:1 contrast and lean on the same
relief the reference palette does (visible labels / the score table):

```text
node validate_palette.js "#b65b38,#4b3ba6,#0e8f76,#2a78d6,#eda100,#e87ba4" \
    --mode light --surface "#ebe7dc"
  worst adjacent ΔE 60.4 (deutan) · [WARN] contrast amber 1.75, magenta 2.18 → PASS

node validate_palette.js "#cb6e44,#877ae0,#1fa083,#3987e5,#c98500,#d55181" \
    --mode dark --surface "#0e1613"
  worst adjacent ΔE 53.9 (deutan) · [PASS] all contrast → ALL CHECKS PASS
```

Because a unit can stand on a resource node, the team pair is also validated
*with* resource-aqua as a third board mark (`--pairs all`):

```text
node validate_palette.js "#b65b38,#4b3ba6,#1baf7a" \
    --mode light --surface "#ebe7dc" --pairs all
  worst all-pairs ΔE 23.3 (protan) · [WARN] aqua contrast 2.28 → PASS

node validate_palette.js "#cb6e44,#877ae0,#199e70" \
    --mode dark --surface "#0e1613" --pairs all
  worst all-pairs ΔE 15.9 (protan) · [PASS] all contrast → ALL CHECKS PASS
```

Both are above the ≥ 12 target. The single light-mode WARN is aqua at 2.28:1
contrast; the relief is the sanctioned one — resource nodes carry a white
numeric count label and a **diamond** mark (never a round unit), so shape +
label carry identity where the pale aqua fill is quiet. (This is a strict
improvement on the previous blue/red design, whose dark aqua↔red pair sat in the
8–12 floor band; the new team hues put the tightest 3-way pair at ΔE 15.9 dark.)

The chrome accent green is a *chrome* token, not a categorical series, so it is
validated by WCAG contrast rather than the categorical six (its brightness is an
accent choice, not a band constraint). `contrast()` from the same script:
`#1e7a4d` as link/border on cream reads 4.6:1 (card 5.0:1) and carries white
play-button text at 5.3:1; `#46c79e` as link/border on black-green reads 8.4:1
(plane 8.9:1) and carries `#06100c` play-button text at 9.1:1. It is a distinct
hue family from status-good (`#0ca30c`) and never appears on a board mark, so it
cannot be read as a status.

## Theme decisions

Both themes are **selected steps, not an auto-flip**. Each ships its own
surface, ink, elevation, grid, chrome accent, and stepped team hues — the dark
hues are the palette's dark column (chosen for the dark band), not a filter over
the light ones.

- **Light is Anthropic cream:** a warm paper page plane (`#f0eee5`), warmer
  elevated cards, warm near-black ink (`#242019`).
- **Dark is Culture black-green:** a deep green-tinged black plane (`#0c1210`),
  green-tinged elevation (`#111a16`), green-tinged near-white ink, and a
  restrained green accent for chrome only.
- `prefers-color-scheme` picks the default theme.
- A manual toggle stamps `data-theme="dark"` / `data-theme="light"` on the root,
  and those blocks re-declare the full token set so the toggle **wins in both
  directions** regardless of the OS preference.
- Depth is a designed, per-theme token: light mode uses soft cast shadows; dark
  mode uses a faint inset top highlight plus a deeper shadow, so elevation reads
  correctly on each surface. The board is the hero — it carries the strongest
  elevation (`--shadow-hero`).

The GIF inherits the same vision — and, after a direct side-by-side human
comparison of the two faces ("the menu on HTML is FAR better — I want the play
from THAT as the GIF"), its play frames mirror the HTML page's **board card**
itself rather than a parallel composition. `league.replay.video` imports the
per-theme tokens from `league.replay.html` (`THEMES`) and adds the HTML face's
own neutral/chrome steps lifted verbatim from its CSS custom properties (page
matte `--plane`, card surface `--surface`, hairline `--grid`, secondary
`--ink-2`, chrome `--accent`, chip `--chip`) plus two derived steps that
rasterize its alpha effects (`--ring` = ink at 10% over the surface; the
depleted-node tint = the resource hue at 28% over the plane) — a 28-slot
palette per theme, selected by `league match record --theme light|dark`
(default light). No new hues: every added slot is a token or an alpha-blend of
two tokens, so the validated categorical/status system is untouched. Every
frame kind is composed like the HTML face:

- The **title card** is a centered lockup — the title over a thin accent
  rule, the match id, a scenario · mode · seed metadata line, then one
  swatch-chipped row per team with its roster — framed by hairline corner
  marks on the page matte.
- **Turn frames are the HTML board card, raster-exact.** Every geometry value
  is one of `html.py`'s own CSS/SVG pixel numbers scaled by `cell_px / 46`
  (46 = the HTML board's SVG cell): the rounded card surface (18px corners,
  1px `--ring` border, 14px padding) floats on the page matte; inside it a
  header row — the brand mark (the 135° clay→violet gradient as a two-tone
  raster) and title, the turn readout right-aligned (the HTML's
  `turn N / limit`), then one pill chip per team (swatch · name · live
  RES/MSN numerals in fixed columns) with the match id · scenario line
  right-aligned; then the board frame (12px corners, 1px border, the
  `--board-top`→`--board-bot` gradient rendered flat at its midpoint — the
  `THEMES` plane token is that midpoint by design) stretched to the card's
  width with the grid letterboxed centered, exactly as the HTML SVG behaves.
  Marks are the HTML board's own: unit discs r 12/46 of a cell with the 2.4px
  surface stroke and bold white role glyph (r 9/46 + `STACK_OFFSETS`' exact
  fan-out when stacked), control-point discs r 15/46 (surface fill + line
  ring unowned; owner tint at `fill-opacity` .24 + team ring owned, hold
  counter in secondary ink), deliver-mission rings r 18/46 (muted pending,
  completer-hued done, secondary ink shared), resource diamonds (11√2/46
  half-diagonal) with the white remaining count (resource tint when
  exhausted), and the carry badge at the unit's shoulder. Interactive-only
  chrome (transport, slider, tab deck) is deliberately absent — the GIF is
  the board card, not the page — and the board's fine-print id labels
  (`cp-id`/`m-label`) are the one omission: they sit below the 5×7 bitmap
  font's legibility floor. Tween frames share this chrome pixel-for-pixel and
  interpolate only the units.
- The **closing card** leads with big score numerals over swatch-labelled
  team rows and names the winner beneath its team chip (or `DRAW` /
  `NO WINNER`), centered like the title card.

Typography is the 5×7 glyph grid at integer scales (3× title, 2× section,
1× tracked captions, 5× score numerals); secondary text wears the muted /
secondary-ink steps, never pure black or white, and identity always rides a
swatch beside the text. The frame *indices* are theme-independent — only the
GIF's global color table changes — so both themes stay byte-deterministic and
the interpolation is identical.

## Motion inventory

All motion lives behind `@media (prefers-reduced-motion: no-preference)` in
effect: a single `prefers-reduced-motion: reduce` block collapses every
transition and animation, and the JS skips spawning celebration effects when
reduced motion is requested.

### Continuous, gapless playback (the smoothness fix)

The old glide used **one eased transition** (`cubic-bezier`) whose duration was
`0.72 ×` the turn-advance interval. Each turn the unit therefore eased *in* from
rest, eased *out* to rest, then **paused** for the remaining ~0.28 × the
interval before the next turn — the "step accelerate–decelerate" the reviewer
saw, even for a unit travelling in a straight line across several turns.

The fix: during **playback** the glide uses **linear** timing whose duration is
**exactly** the turn-advance interval. JS drives this by flipping two tokens by
play state — `#unit-layer g { transition: transform var(--move-dur)
var(--move-ease) }`:

- **Playing:** `--move-ease: linear`, `--move-dur = SPEEDS[speed]` (the exact
  interval). Back-to-back same-direction turns run at constant velocity with no
  pause between waypoints, so a multi-turn journey reads as one continuous
  glide.
- **Paused** (scrub, prev/next, deep link): a short (`320ms`) eased snap —
  crisp, as the reviewer's own note allows.
- **Reduced motion:** the global block collapses both to instant snaps.

Determinism is unchanged: this is runtime behavior toggled by CSS custom
properties, so the generated HTML bytes are identical render-to-render.

### The rest of the motion inventory

| Moment | Motion | Restraint |
|--------|--------|-----------|
| Unit movement between turns | the node glides via a `transform` transition — linear + gapless while playing, an eased snap when paused | position interpolation only; first paint lands at rest before transitions arm |
| Fresh capture | the control disc floods in and a soft ring pulses in the new owner's hue | one ring, ~0.9s, forward step only |
| Delivery | a `good`-green flash at the delivering unit | ~1s, fades out |
| Mission completion | a larger `good` ring plus a flash at the target | ~1.15s |
| Unit defeat | a `critical`-red ring at the unit's cell | ~0.9s |
| Playback | play/pause with 0.5× / 1× / 2× speed | the glide duration tracks the chosen speed |

Effects only fire on a **forward** step (play or next), never on a scrub or a
reverse, and their placement is fully determined by the log — timing is the only
time-based element, which is permitted.

### Smooth GIF too — interpolated tweens

The GIF adds the same smoothness with **interpolated tween frames** between
turns: `--tween N` (default 4, bounded 0–12) inserts `N` linearly interpolated
frames between each adjacent pair of turns, so a unit glides from exactly where
it stood to exactly where it lands instead of teleporting. A tween frame holds
the *starting* turn's card chrome (grid, nodes, missions, control points, the
card header — all discrete state) and moves only the units; captures, resource
counts, and the turn readout land crisply on the turn frames. Frame
count follows `turns + (turns - 1) * tween + 2` (title + turns + interpolated
frames + closing). Interpolation rounds to whole pixels, so the byte-determinism
gate holds; a turn's total screen time is preserved by splitting it across its
`tween + 1` sub-frames.

## Side panel — a tabbed deck (the layout fix)

The reviewer had to scroll up and down between the board and the assessor guide,
which lived in a full-width `<details>` at the bottom of the page. The right
column is now a **tabbed side deck** (Guide / Events / Teams / Score) that uses
the available width (`clamp(380px, 34vw, 560px)`); the board stays the hero on
the left. The Guide is the default-active tab when present. On a wide viewport
(≥ 1101px) the board and the side deck are sticky and the active tab panel
scrolls **inside its own bounded height**, so the guide never pushes the board
off-screen — no vertical scrolling between the two. On a narrow viewport the
layout stacks (board over the deck) with the same tab bar.

Tabs are plain inline CSS/JS with no dependency: real `<button role="tab">`
elements with `aria-selected`, a roving `tabindex`, and Arrow/Home/End
navigation (isolated from the turn-transport keys). Panels toggle via `hidden`.
Deep links (`#tN`) and the guide's scrub links keep working from inside the
Guide panel — they only drive the board on the left, so the guide stays put and
the board updates in view. The tab chrome is styled with the theme tokens in
both modes (the active tab wears `--accent`). Rendered HTML stays
byte-deterministic.

## Anti-pattern checklist

Checked against every entry in `references/anti-patterns.md`; result: **zero
hits**.

- Color & encoding: no dual-axis, no recolor-on-filter (color follows the team,
  not its row), no hue cycling past 8, no eyeballed CVD (validator run), no
  value-ramp on nominal categories, no hue at a diverging midpoint, no status
  color on a non-status series, and the chrome accent is a separate token that
  never doubles as a team or a status.
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
  table, direct feed text, and unit `title`s), the transport buttons and the
  side-deck tabs meet the hit-target minimum and are keyboard-operable, and all
  motion is reduced-motion-safe.
