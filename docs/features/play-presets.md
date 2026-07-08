# Play presets

`league play` is one-command launch of a bundled game mode
([`league/presets.py`](../../league/presets.py)). Every documented mode runs end
to end from a single call — no hand-authored `team register` / `match new` /
`harness run` dance required.

```bash
league play list                       # every bundled preset, one line each
league play show team-vs-team          # the resolved harness config (check before running)
league play start team-vs-team --apply # play it
league play start solo-vs-bot --seed 99 --id my-solo-run --apply
```

`start` is a write verb — **dry-run by default, `--apply` actually plays the
match** — the same safe contract `match new` / `team register` / `harness run`
follow. `--seed` / `--id` override the preset's declared defaults (handy for
running the same mode twice without a match-id collision) without ever editing
the bundled registry.

## The bundled modes

| Preset | What it pits against what |
|--------|---------------------------|
| `solo-vs-bot` | One agent commands the whole roster alone, handicapped to a single action per turn (the coordination-necessity handicap), vs the silver house bot. |
| `team-vs-bot` | One mind per seat, stateless (fresh subprocess each turn), vs the greedy bot baseline. |
| `team-vs-team` | Two `bot-file` strategies play each other — **fully offline**, deterministic given the seed, no live process on either side. |
| `orchestrator-vs-bot` | A master mind guides per-seat ground agents by message only, on the fogbound scenario, vs the bot baseline. |
| `resident-vs-bot` | One long-lived session per seat for the whole match, on the fogbound scenario, vs the bot baseline. |

`solo-vs-bot`, `team-vs-bot`, `orchestrator-vs-bot`, and `resident-vs-bot` drive
a live agent process, so `--apply` on those spawns whatever `argv` the preset
declares (inspect it with `play show <preset>`). `team-vs-team` is the one mode
that never spawns anything.

## See also

- [Harness & drivers](harness-and-drivers.md) — the driver kinds these presets
  wire up.
- [Coded-strategy bots](coded-strategy-bots.md) — the strategies `team-vs-team`
  and the house bots use.
