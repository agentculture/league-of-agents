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
column is now a **tabbed side deck** (Guide / Events / Teams / Score /
Scorecard — the fifth tab is cycle-8 t8's per-unit scorecard, below) that uses
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

## Ambient score — generative, seeded, off by default (cycle 8)

> **Provenance — the user's directive, verbatim (cycle-8 spec c17):** "add
> audio that will make experience superb. Both for the reply (html) and the
> videos we export. I want a pleasent music that will complement the
> experience and make me feel content and relaxed, but also curious and
> intrigued."

The HTML replay's transport gains a note toggle (`#btn-audio`, wearing the
play button's own accent on-state) that plays a generative ambient score in
the Eno vein, synthesized entirely at play time with WebAudio primitives —
`OscillatorNode`, `GainNode`, `BiquadFilterNode`, and a `ConvolverNode` whose
impulse response is itself synthesized from the seeded stream, never a
fetched asset. Nothing about the feature touches the document: the page stays
byte-deterministic and self-contained, the toggle is **off by default**
(browser autoplay policy, and the reviewer's choice), and enabling it only
creates an `AudioContext` lazily on the enabling gesture.

**Musical design.** Two layers map the two halves of the mood brief:

- *Content and relaxed* — a warm pad bed: open major **lydian** voicings
  (1-5-9-3, an add-6, the lydian II, a 1-5-maj7 suspension — no minor-third
  low intervals, so no minor-key tension), two ±2.5-cent-detuned sines per
  chord tone plus a quiet sub-octave triangle, 6-second attacks and 7-second
  releases crossfading 18–26-second chords into one continuous bed, low-pass
  filtered around 950 Hz with a slow (0.045 Hz) LFO breathing the cutoff. The
  root is one of four warm choices (F2/G2/A2/C3), picked by the seed.
- *Curious and intrigued* — sparse bell tones every 3.5–9 seconds: three
  near-harmonic sine partials (1 / 2.01 / 3.02) with a 12 ms attack and a
  long exponential decay, drawn from a pentatonic-plus-maj7 set two octaves
  above the root, with the lydian sharp-4 reserved as a rare (~11%) color and
  an occasional (~22%) soft answering bell a third or fifth above. Bells ride
  mostly through the synthesized reverb.

Master gain stays conservative (about a −18 dBFS feel, behind a gentle safety
compressor): the score plays *under* someone watching a replay, never over it.

**Determinism.** Every musical decision consumes a seeded `mulberry32`
stream whose seed is FNV-1a over `match_id | seed` — data already embedded in
the page — with one independent stream per voice (pads, bells, impulse) so
the look-ahead scheduler's wall-clock tick cadence can never reorder draws.
Same match → identical note choices and timings, on every enable. No
unseeded entropy: the byte-determinism test bans `Math.random`/`Date.now` in
the rendered document, and the no-external-request sweep covers the audio
path like everything else.

**The reviewer rates the mood on the record (spec h11/h12).** The assessor
guide's "Ambient score" section quotes the target verbatim — "content and
relaxed, but also curious and intrigued" — and the next human review rates
whether the score lands it; a miss is a finding for the next cycle, not a
silent pass. The exported-video soundtrack (below) sits under the same
obligation. The **continuous face deliberately stays silent this wave**:
frame v4 is pinned minimal — no transport, no client JS — so there is no
idiomatic home for a toggle there yet; it inherits audio when the continuous
lane earns its own visual cycle.

### The exported soundtrack — the same piece, offline (cycle-8 t9)

`league match record --format mp4` muxes the match's ambient score into the
video: `league/replay/audio.py` (pure stdlib — `wave`, `math`, `array`; the
runtime dependency list stays empty) synthesizes a WAV offline and the
existing optional-ffmpeg path adds it as a second input (`-i soundtrack.wav
-c:a aac -shortest` — every pre-existing video argument is untouched, and the
no-ffmpeg error contract is exactly what it was).

**Same match, same music.** The offline render is a port of the HTML score's
decision engine, not a second composition: the seed is FNV-1a over
`match_id|seed` (the page's own `audioSeed()`), every musical decision
consumes a bit-exact `mulberry32` port, and each voice draws from the same
independent stream (`seed ^ 0x51AB3C02` pads, `seed ^ 0x9E3779B9` bells) —
so the chord root, the lydian pad progression, and the bell cadence are
note-for-note the piece the HTML toggle plays for that match. The port is
pinned against the JavaScript itself: `tests/test_replay_audio.py` carries
uint32 PRNG streams and full 60-second decision tables extracted from
`html.py`'s embedded code running under node, and fails if the two engines
ever drift.

**Documented differences, all sample-level, none decision-level.** WebAudio's
convolver reverb has no cheap pure-Python equivalent, so the offline render
drops the synthesized reverb tail (its seed stream is independent — skipping
it changes no other draw) and substitutes a one-pole low-pass (with the same
950 Hz ± 240 Hz × 0.045 Hz LFO breath) for the biquad; and it adds a short
closing fade-out, because an MP4 ends and the page never does. Output is
**mono 16-bit PCM at 44100 Hz** — mono because the HTML graph's stereo width
comes only from the reverb this render omits. The WAV covers the MP4's exact
duration (its sample count derives from the same held-frame total the raw
video pipe carries), and the same log + same record settings produce a
**byte-identical WAV** (unit-tested).

**The GIF stays silent by format truth.** GIF89a simply has no audio channel
— there is nothing to mux into, so silence there is a property of the format,
not a missing feature. `--format gif` output is byte-unchanged by the
soundtrack work, pinned by a committed-log GIF hash in
`tests/test_replay_video.py`.

**The reviewer verdict obligation extends to the MP4 (spec h11).** The mood
target for the exported soundtrack is the same verbatim directive quoted at
the top of this section — "a pleasent music that will complement the
experience and make me feel content and relaxed, but also curious and
intrigued" — and the next human review rates whether the MP4 soundtrack
lands it **on the record**, exactly as for the HTML score: a recorded
reviewer verdict, not a developer assertion; a miss is a finding for the
next cycle, not a silent pass.

### Event sounds — the score reacts to the match (cycle-8 amendment)

> **Provenance — the user's directive, verbatim (cycle-8 audio-events
> amendment):** "I like the soundtrack - but it should react or describe
> what's going on in the game. (Or events have a sound, so soundtrack +
> events sounds = this recording sounds)"

The chosen interpretation: the ambient bed above stays exactly as it was; a
**deterministic event-sound layer** plays on top. Every notable match event
gets a short motif, fired at the moment playback reaches that event's turn —
the recording's sound *is* bed + event motifs. Where the bed is a pure
function of the seed, this layer is a pure function of **(log, playback
position)** — no seeded randomness at all: any per-event pitch variety hashes
the event's own canonical fields (FNV-1a), never wall-clock, never entropy.

**The motif table.** All pitches are scale steps over the **same seeded root
the bed draws** (`octave × 12 + step + register` semitones above `root_hz`),
so the layer can never clash with the bed's key:

| Event | Motif | Pitch source |
| --- | --- | --- |
| `control_point_captured` (post taken) | bright rising-fourth chime | steps 0→5, octave 3, chime voice |
| `mission_completed` (incl. hold reward) | gentle three-note ascending arpeggio | steps 0→4→7, octave 2, chime voice |
| `resource_gathered` | single soft mallet pluck, low velocity | one of steps {0, 2, 4} by `fnv1a(unit_id\|node_id) % 3`, octave 1, pluck voice |
| `resource_delivered` | warm two-note rising resolution | steps 4→7, octave 2, pluck voice |
| `action_rejected` (failed order, delivery denied, capture rejected) | low muted thud with a soft minor-second decay — clearly "denied", never harsh (the delivery-contention rule becoming audible is a feature) | steps 0 + 1, octave 0, thud voice |
| `message_sent` | tiny high blip, very quiet (coordination made audible) | step 0, octave 4, blip voice |
| `match_finished` | short cadence | steps 7→11→12, octave 2, chime voice, neutral register |

**Silence is a design choice.** `unit_moved`, `control_point_held`,
`turn_advanced`, `turn_resolved`, `action_declared`, `plan_declared`,
`seat_latency`, `match_started`, and `unit_defeated` play **no sound**: they
are high-frequency bookkeeping or declaration-stage noise, and sounding them
would bury the moments that matter. The *resolution* events carry the sound
(a declared order that fails still sounds — as the denial thud).

**Team legibility by ear.** The team listed first in the roster plays in the
lower octave; the second plays `register_semitones` (12) up — blue vs red
actions are tellable apart without looking. The rule is `(team index % 2) ×
12`, so it extends past two teams unchanged. Events that only name a unit
(gathers) resolve their team through the roster; the final whistle is
register-neutral.

**One table, two renderers.** The motif table is defined once —
`league.replay.audio.EVENT_SOUND` — and `render_html` injects it verbatim
(as JSON) into the page's JS as the `EVENT_SOUND` const, so the live page
and the offline WAV render the identical design and cannot drift by
construction (the same discipline t9 used to mirror t4's engine, one step
stronger). The note plans (`motifPlan` in the page, `motif_notes` offline)
are pinned against each other in `tests/test_replay_audio.py` via values
extracted from the rendered document's own JS under node.

**Intra-turn offsets.** The k-th of a turn's n *sounding* events fires
`interval × k / n` into the turn interval — a pure function of the event's
position among the turn's sounding events (silent kinds occupy no slot), so
simultaneous events spread instead of stacking into a click, and identical
logs always sound identical. In the page the interval is the current
playback speed's turn hold; in the MP4 it is the turn's exact held-frame
span on the video timeline.

**Scrubbing never replays history.** Motifs fire **only on a normal forward
advance** (a playback tick or a single next-step) — the same rule as the
board's celebration fx. Jumping, scrubbing, deep links, and reverse steps
are navigation, not time passing, so skipped events are never machine-gunned
into the ear. The existing note toggle governs bed + events together — one
control, still **off by default**, and the document stays byte-deterministic
and self-contained (the injected table is a constant).

**The MP4 carries the same layer.** `synthesize_wav` accepts the motif
schedule (`motif_schedule`), and `league match record --format mp4` renders
each motif at its event's video time — the turn→frame→sample mapping the mux
already knows, with the same k/n intra-turn offsets. Same log + same
settings → byte-identical WAV, as before; an empty schedule reproduces the
t9 bed bytes exactly (unit-tested). **The GIF stays byte-unchanged and
silent** (format truth; the byte-pin in `tests/test_replay_video.py` still
guards it). **The continuous face stays silent** this amendment too: frame
v4 is pinned minimal — no client JS — so there is nothing for event audio to
ride on; it inherits the event layer when the continuous lane earns its own
interactive cycle (the same decision t4 recorded for the bed).

## Scorecard — the per-unit axis in both faces (cycle 8)

> **Provenance — the human review's ask, verbatim (cycle-8 spec c10):** *"We
> need 'Best unit (MVP)' and 'Worst unit (LVP)' — grades per unit per role (a
> unit should get more points for the designated purpose of its role — a
> scout not scouting should still get points, but less if it's not a scouting
> task, etc.)"* The reviewer was judging one level deeper than the guide
> explained; cycle-8 t8 closes that gap in the replay itself.

The grid deck gains a fifth tab, **Scorecard**, matching the deck's existing
tab idiom exactly (a real `role="tab"` button, a `hidden`-toggling panel, the
theme tokens in both modes). Its facts are
`league.engine.grades.grade_units(log)` computed at render time — a pure
function of the log, so the document stays byte-deterministic — reshaped into
a ranked list (`build_scorecard`): units ordered by grade descending with the
canonical `(team_id, unit_id)` tie-break, so the top row *is* the MVP. Each
row shows a team dot (identity rides a mark, never the text), the unit id and
role, MVP/LVP chips where earned — the **winner-chip vocabulary**: a `.chip`
wearing the fixed status hues (`--good`/`--critical`) with a text label,
never a team color — the grade, and the full four-purpose breakdown
(economy / control / recon / coordination). The unit's **home purpose is
typographically marked** — bold ink plus a small `×2 home` tag naming the
on-role multiplier — a text-weight job, deliberately *not* a new color job
(the accent stays chrome-only, the status hues stay verdict labels).

The assessor guide gains a matching **"Scorecard — best and worst seat"**
section that explains exactly what the grade weighs, every number
interpolated from `league.engine.grades`' own pinned constants so the prose
can never drift from the formula: the four buckets and the event kinds that
feed them (`resource_gathered`/`resource_delivered` by amount;
`control_point_captured` 3 pts / `control_point_held` 1 pt to the team's
units standing on the point; `unit_moved` 1 pt; `message_sent` 1 pt), the
on-role ×2 / off-role ×1 multiplier sentence, the MVP/LVP tie-break, and a
verdict naming *this* match's MVP and LVP with their top bucket — the
reviewer test (spec h6): guide + deck alone answer who carried, who sank,
and why, without watching the match twice.

The **continuous face lists the same facts in its minimal idiom** (frame v4
stays pinned: no tabs, no client JS, no ported deck chrome): one static
server-rendered table from
`league.engine.continuous.grades.cgrade_units(clog)` — units ranked by grade,
MVP/LVP marked in their rows and named in a verdict line, the on-role cell
bolded — plus one plain-text paragraph explaining the continuous weights
(`take_post` 300; gathered/delivered amounts and banked mission rewards
×`GRADE_UNIT`; 100 per board-unit moved; off-role work earns 1/2 credit —
more than zero, never full) and the same tie-break. Grades are a *new axis
beside* the team score in both faces — they never feed it, and no ranking
surface exists (spec boundary).

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
