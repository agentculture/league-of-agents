# Tempo conversion methodology

Tempo is the arena's third scored axis (plan task t5/t6, spec c4/h4): speed is
measured, benchmarked, and converted for fair comparison — published beside
outcome and cooperation, never merged into either
(`league/engine/scoring.py` stays untouched by this axis). This document is
the committed, contestable methodology the boundary claim (spec c13/h12)
requires: it explains the calibration and conversion **and** lists its own
limits, so a reader can judge how far to trust a tempo number rather than
take it on faith.

Everything below describes `league/engine/tempo.py` (`score_tempo`) and the
harness instrumentation that feeds it (`league/harness.py`) as merged —
not an aspiration for a future cycle.

## What is measured

Latency is captured **only** in `league/harness.py`, never in
`league/engine/` — the determinism import ban
(`tests/test_engine_state.py::test_engine_never_imports_time_or_random`)
forbids `time`/`random`/`datetime`/`secrets`/`uuid` imports package-wide over
the engine, and `seat_latency` events fold as a no-op there by construction:
`MatchState`, `state_hash`, and the determinism gate are exactly as if
latency metadata had never been written.

- **What is timed.** `run_match` threads a fresh, empty, per-team, per-turn
  list into `context["_latency_sink"]` before calling that team's driver each
  turn. Every driver factory wraps its **actual driver call** in
  `time.perf_counter()`: a subprocess run (`command` driver), a resident
  session's `session.send` (`resident` driver), or — for a driver that does
  not operate per seat (`bot`, `bot-file`, or a `command`/orchestrator driver
  that commands a whole team/master in one call) — that single call. A driver
  exercised directly with no sink threaded through `context` (every
  pre-existing harness test) records nothing; this is purely additive.
- **Team-level vs. per-seat entries.** `bot`, `bot-file`, and a non-per-seat
  `command` driver append one record per turn with `agent_id: null,
  unit_id: null` — a "seat of one" standing in for the whole team's roster,
  because one call commanded every unit at once. A per-seat `command` driver,
  a `resident` driver, and an orchestrator's master sub-driver append one
  record **per agent/unit** (the master gets its own declared identity, no
  unit). `score_tempo`'s `seats_measured` count reflects this directly: it is
  the number of distinct `agent_id` values seen (`null` counts as exactly one
  team-wide seat).
- **Failed and timed-out calls still count.** `_run_command` retries a
  subprocess call once internally before raising; the timer set before the
  call brackets the whole attempt, including that retry — not just a
  successful final one. If the call still fails (non-zero exit, a timeout, an
  unparsable reply) or a resident `session.send` raises, the harness prints an
  idle notice, the seat contributes no orders this turn, **and the harness
  still appends the elapsed time to the sink** before moving on — "a
  failed/timed-out call still burned wall-clock time — real tempo data, not
  something to drop on the idle path" (the code's own comment at the idle
  path). A chronically-timing-out driver therefore shows up as *slow* tempo
  (its large elapsed values pull the median up), not as missing data.
- **How it reaches the log.** After each turn, `run_match` tags every
  sink record with `team_id`/`turn` and appends them straight to the on-disk
  match log as `seat_latency` OBSERVATION events (`league.engine.events`)
  through `Store`, bypassing the CLI's `--orders-json` contract — harness
  instrumentation, not a driver's declared move, the same reasoning that
  already lets the resident driver append session transcripts directly.
  `seq` continues from the log's current length so it never collides with
  the tick's own event sequence for that turn.
- **Graceful degradation on logs without latency.** Every committed season-0
  log (and any match created but never played) carries zero `seat_latency`
  events. `score_tempo` never raises on this: a team with no latency data
  gets `{"raw": None, "version": "t0"}` and **no `converted` key at all** —
  distinct from the identity-conversion case below, where `raw` data exists
  but the substrate wasn't normalized. A match can also have partial
  instrumentation — one team measured, the other not — and `score_tempo`
  still returns one payload per team either way.

## The t0 formula

`TEMPO_VERSION = "t0"` is echoed in every payload; see
[Evolution contract](#evolution-contract-the-version-tag) for what "t0" means
and when it changes.

`score_tempo` reads a team's `seat_latency` events off the log and computes
two blocks:

- **`raw` (always present when any latency was recorded).**
  `median_ms` — the median of every recorded `elapsed_ms` for that team
  across the whole match, the number that drives the converted score.
  Median, not mean, is deliberate: it is robust to one pathological slow
  turn, so a single stall cannot dominate a team's tempo. `mean_ms` and
  `p95_ms` (the 95th percentile by nearest-rank) are published alongside for
  context — the tail `p95_ms` exposes what the median-only score cannot see
  (see [Limits](#limits)). `turns_measured` and `seats_measured` say how much
  of the match was actually instrumented.
- **`converted` (present only when `raw` is present).** For a team with a
  **known** declared substrate: `baseline_ms = calibration[substrate]`,
  `ratio = round(median_ms / baseline_ms, 4)` (below 1.0 is faster than
  baseline, above 1.0 is slower), and
  `tempo_score = round(TEMPO_SCALE * baseline_ms / max(median_ms,
  MIN_MEASURED_MS))`. `TEMPO_SCALE = 100` is the index's **par**: a team
  turning in exactly at its substrate's baseline scores exactly 100 — faster
  scores above it, slower below it. `MIN_MEASURED_MS = 1` is only a floor on
  the divisor (`median_ms`), so a near-instant median (a coded bot) can never
  divide by zero; it does not floor the baseline itself. The score is
  **deliberately uncapped** — a normalized speed index, not a bounded 0–100
  grade — so being unusually fast is rewarded rather than clipped; see
  [Limits](#limits) for what that design choice costs.
- For an **unknown or undeclared** substrate, see
  [Identity conversion](#identity-conversion-for-undeclared-or-unknown-substrates)
  below — the same `converted` shape, but pinned at par with a caveat.

## The calibration table

```python
DEFAULT_CALIBRATION: dict[str, int] = {
    "cloud": 20_000,   # hosted / frontier LLM: fast substrate
    "local": 200_000,  # local / on-device LLM: slow substrate (~10x cloud)
    "bot": 10,         # a coded strategy bot: effectively instantaneous
}
```

Substrate is **caller-declared**, never inferred from timing: the CLI's
`league match score <id> --substrate <team-id>=<name>` flag (repeatable) —
and `score_tempo`'s own `substrates={team_id: substrate_name}` parameter for
any caller reading the log directly — is the only way a team's tempo gets
normalized. `score_tempo` never looks at how fast a team actually was to
guess what substrate produced that speed.

**These three numbers are illustrative seed values, not measured baselines.**
The load-bearing property today is the *order* — cloud's baseline sits below
local's, because a hosted/frontier mind is inherently faster than a local
one — and that the table is plain data with a clear extension point
(`score_tempo(log, calibration={...})` overrides it entirely for any caller
that constructs its own table; the CLI itself always scores against
`DEFAULT_CALIBRATION` — there is no `--calibration-file` flag yet to swap the
whole table at the command line). The exact magnitudes may be replaced by a
real calibration run without changing anything else about the mechanism —
see [Limits](#limits).

## Identity conversion for undeclared or unknown substrates

A team with recorded latency but no declared substrate, or a declared
substrate not in the calibration table, still gets a full `converted` block —
never an absent one, and never a fabricated normalization:

- `baseline_ms` is set to the team's **own** `median_ms` (identity: the team
  is its own baseline).
- `ratio` is pinned at `1.0` and `tempo_score` at `TEMPO_SCALE` (100, par) — a
  neutral placeholder, not a claim of speed.
- `substrate_known` is `False`, and a `caveat` string names exactly why:
  `"no substrate declared for this team..."` when the flag was omitted, or
  `"unknown substrate '<name>' (not in the calibration table ...)"` when a
  name was declared but isn't recognized. A declared-but-unrecognized name is
  preserved in the payload's `substrate` field honestly — it is not silently
  dropped.

Every CLI surface that prints a converted tempo score prints the raw median
beside it unconditionally (the h4 honesty condition — see `_tempo_line` in
`league/cli/_commands/match.py`), and the text rendering explicitly marks an
identity-converted score `"unnormalized"` so a reader never mistakes par for
a real cross-substrate claim.

## Evolution contract (the version tag)

The formula lives in code, never in the log, so it can evolve without
touching a single recorded match. `TEMPO_VERSION` (currently `"t0"`) is
echoed in every payload; a formula change — a different central statistic, a
different ratio/score shape, a new calibration mechanism — bumps that version
string. It **never** rewrites, re-scores, or invalidates a previously
recorded log: `seat_latency` events are raw facts (elapsed milliseconds, per
seat, per turn), and the tempo *score* is a read-time projection of those
facts recomputed under whatever formula version is current when someone asks
for it. An old match scored under `"t0"` today can be re-scored under `"t1"`
tomorrow with no re-run, no migration, and no loss of the original facts.

## Limits

The spec requires this section to be blunt, and the boundary claim (spec
c13/h12) is explicit: **cross-substrate speed equivalence is not solved
here.** This methodology is published and contestable, not a proof of
fairness. Its concrete limits:

- **Median hides intra-match variance.** `tempo_score` is driven by one
  summary statistic across the whole match. A team that opens fast and stalls
  badly late (or the reverse) collapses to a single number; `p95_ms` is
  published beside it, but it is not folded into the score, so a reader who
  looks only at `tempo_score` misses the tail entirely.
- **Baselines are declared, not measured — until a real calibration run
  exists.** `DEFAULT_CALIBRATION`'s three numbers are illustrative seeds
  chosen to preserve the intuitive cloud-faster-than-local ordering. They
  have not been derived from an actual timed run of real cloud/local minds
  against this engine's scenarios. Treat any `tempo_score` computed today as
  provisional until a genuine calibration exercise (the plan's t8 benchmark,
  or a future one) replaces these numbers with measured baselines.
- **Wall-clock conflates model speed with network/tooling overhead.**
  `perf_counter()` brackets the *entire* driver call, not model "thinking
  time" in isolation — for a `command` driver that includes subprocess spawn
  cost and prompt/JSON round-trip work in the harness itself; for a
  `resident` driver it includes whatever the session transport (`claude-cli`
  or `colleague-direct`) costs to reach the model. Two identical minds behind
  different tooling are not directly comparable by this raw number alone.
- **A mis-declared substrate produces garbage indices.** Substrate is
  caller-declared and never verified — declaring `cloud` for a team that is
  actually a local model (or the reverse) silently computes `tempo_score`
  against the wrong baseline; the mechanism has no way to detect the lie.
  The only cross-check this methodology offers is that raw always sits
  beside converted (h4): a suspiciously extreme ratio next to a plausible
  raw median is a visible tell to a reviewer, but nothing in the code
  enforces or flags it automatically.
- **Single-substrate self-comparison is the only fully fair mode today.**
  Because the baselines are still provisional and substrate declaration is
  unverified, the one comparison this methodology can back with full
  confidence is the *same* mind, on the *same* declared substrate, across
  different matches or configs — there, `ratio` and `tempo_score` both track
  a real change in that mind's own pace. Comparing two *different* declared
  substrates' converted scores against each other rests entirely on
  `DEFAULT_CALIBRATION`'s still-illustrative numbers.
- **The uncapped score's failure mode.** `tempo_score` has no ceiling: as
  `median_ms` shrinks toward the `MIN_MEASURED_MS` floor, the score grows
  without bound. A driver that fails or returns near-instantly — a bug, a
  broken integration, a degenerate zero-latency measurement — can produce an
  implausibly large `tempo_score` that reads as "blazing fast" when it is
  actually a measurement artifact or an outright malfunction. The design's
  only guard against being misled by such a number is, again, that raw sits
  beside it always: a median of a few milliseconds next to a `tempo_score` in
  the thousands is visible to anyone who looks at both, but the score alone
  does not flag itself. The failure mode is also asymmetric: a badly stalled
  team's score only asymptotes toward zero (never negative or unbounded on
  the slow side), so the uncapped risk runs one direction — implausibly fast,
  never implausibly slow.

None of the above is a defect to quietly patch away; the honesty condition
this document exists to satisfy is that these limits are named, not solved,
and the next cycle that touches tempo inherits them explicitly.

## Where this is discoverable

This document is linked from the [README](../README.md)'s scoring
description and from `league match score`'s CLI help / `league explain match`
catalog entry (`league/cli/_commands/match.py`,
`league/explain/catalog.py`) — so a reader who lands on the CLI surface
first can find the methodology, and a reader who lands here can find the
surface it backs.
