# Clean-checkout demo + boundary review (cycle-4 t9, spec c7/h7 · c13/h12)

One session, from a fresh clone of the implementation branch, no prior state —
the after-state demonstrated end to end, not assembled from disjoint demos
(spec h7).

## The transcript

```bash
git clone --branch impl/cycles-4-5 <repo> clean-checkout && cd clean-checkout
uv sync
uv run league play list                 # 5 presets enumerate, one line each
uv run league play start team-vs-team --apply
#   -> match m-preset-team-vs-team | finished | 30 turns | draw
uv run league match score m-preset-team-vs-team \
    --substrate blue=bot --substrate red=bot
```

Observed, in order (spec h7's three artifacts, one session):

1. **Preset launch** — `play start team-vs-team --apply` resolved the bundled
   preset, registered both teams, created and ran the match to completion (30
   turns, a draw — two identical `bots/rusher.py` strategies mirror each other,
   deterministic given the seed). Fully offline: no live process on either
   side, so the demo runs anywhere the repo does.
2. **Latency-bearing log** — the match log carries `seat_latency` events for
   both teams (raw median 3 ms per side; even coded bots are measured).
3. **Tempo report** — `match score` printed all three axes; tempo showed raw
   median **3 ms** beside converted score **333** (bot baseline 10 ms). The
   uncapped, raw-beside-converted behavior is exactly the documented t0
   contract ([`docs/tempo-methodology.md`](../../tempo-methodology.md)).

The live-mind variant of the same flow is the committed
[solo-vs-bot playtest](solo-vs-bot.report.md) (one command, claude-sonnet-5 vs
the named silver house bot, 26–2).

## Boundary review checklist (spec c13/h12, cycle-5 c11)

Verified against `git diff main impl/cycles-4-5`:

- **Determinism gate byte-identical:** `tests/fixtures/determinism.hash` has a
  zero-line diff vs main; `league/engine/tick.py` and `state.py` are untouched.
- **`league/engine/events.py`** changed only by the `seat_latency` vocabulary
  addition — an OBSERVATION kind whose fold is a no-op; `time` is imported
  only in `league/harness.py` (the engine-wide import ban still enforced by
  `tests/test_engine_state.py`).
- **No server/daemon/matchmaking code:** every new module is data
  (`league/presets.py`), a CLI noun group (`league/cli/_commands/play.py`), or
  a read-time scorer (`league/engine/tempo.py`).
- **The conversion is published and contestable, not claimed solved:**
  [`docs/tempo-methodology.md`](../../tempo-methodology.md) lists six limits of
  its own formula, including that baselines are declared rather than measured.
- **Success artifacts committed together** (spec h13): the preset-enumeration
  tests (`tests/test_presets.py`, `tests/test_cli_play.py`), the recorded
  solo-vs-bot log + replay ([this directory](./)), and the tempo benchmark
  report land in the same PR as this checklist.
