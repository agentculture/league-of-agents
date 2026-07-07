# House-bot roster — tier ordering, recorded (t4, spec c12/h11)

- **Roster:** `bots/shambler.py` (bronze) < `bots/rusher.py` (silver) <
  `bots/vanguard.py` (gold) — see [`bots/README.md`](../../../bots/README.md)
  for the full contract and one-line strategy descriptions.
- **Matches:** skirmish-1, competitive, all bot-file vs bot-file, run through
  `league harness run` exactly the way any other match runs (never a
  test-only shortcut). Two seeds per pairing — **101** and **202**.
- **Regenerate:** `uv run python docs/playtests/house-tiers/generate_matches.py`
  from the repo root. Matches carry no RNG (the engine imports no
  `random`/wall clock package-wide, and `seed` is stored but never consumed
  by resolution — spec c9), so re-running reproduces byte-identical logs;
  both seeds below score identically for exactly that reason.

## Result

| Pairing                              | Seed | Winner        | Blue total | Red total |
| ------------------------------------- | ---- | ------------- | ---------- | --------- |
| gold (vanguard) vs silver (rusher)     | 101  | blue (gold)   | 23         | 0         |
| gold (vanguard) vs silver (rusher)     | 202  | blue (gold)   | 23         | 0         |
| silver (rusher) vs bronze (shambler)   | 101  | blue (silver) | 2          | 0         |
| silver (rusher) vs bronze (shambler)   | 202  | blue (silver) | 2          | 0         |

Artifacts per match: `<slug>.config.json`, `<slug>.log.jsonl`,
`<slug>.replay.html`, `<slug>.score.json` — `<slug>` is the pairing name in
the table above with `-seed101`/`-seed202` appended (e.g.
[`gold-vs-silver-seed101.replay.html`](gold-vs-silver-seed101.replay.html)).

## What happened (from the logs)

**Gold vs silver.** Vanguard's harvester ran the `ms-supply` deliver relay to
completion (10 reward points, 9 resources banked) while its scout and
defender split the two outer control points, `cp-west` and `cp-east` — final
state has `cp-west`/`cp-east` both `owner: blue`. Rusher's three units, with
no economy at all, all independently picked the **same** nearest point
(`cp-center`, tied-closest from every one of its spawn positions) — the
match ends with all three rusher units and vanguard's scout stacked on
`cp-center`, contested and unowned for the whole match, since occupancy by
both sides resets the hold streak every turn. Rusher never captures anything
and never delivers anything: **23–0**.

**Silver vs bronze.** Rusher's three units converge on `cp-center` the same
way (contested only by nobody, this time), so nothing resets the streak and
it flips to `owner: blue` at turn `capture_hold_turns` (2) and stays there —
**2 points, the whole game's outcome**. Shambler's three units hold at their
spawn tiles for all 30 turns, exactly as designed: legal every turn (`hold`
is always legal), never once threatening a point, a mission, or a resource
node. `cp-west`/`cp-east` end the match `owner: None` — nobody outside
`cp-center` even entered the race. **2–0**.

## Reading the tier claim

The two pairings are adjacent by design (gold vs silver, silver vs bronze) —
each result isolates exactly one strength delta: **gold over silver** is the
economy (a completed deliver mission, 10+9 points silver never touches) plus
coordinated point-splitting (2 owned points vs rusher's single contested
one); **silver over bronze** is simply *doing anything at all* — one
captured point against a team that never leaves its spawn. Both deltas hold
identically across both committed seeds, which is expected (spec c9): the
scenario has no source of run-to-run variance for the engine to fold in, so
the same roster on the same scenario produces the same log every time — the
two seeds are two independent regenerations of the same proof, not two
different outcomes to reconcile.

`tests/test_bots.py::test_vanguard_gold_beats_rusher_silver` and
`::test_rusher_silver_beats_shambler_bronze` re-run both pairings directly
(parametrized over the same two seeds) as a fast (well under a second per
match) regression check — if a future change to any of the three strategies
flips the ordering, the test suite catches it before a human has to reread
a replay.
