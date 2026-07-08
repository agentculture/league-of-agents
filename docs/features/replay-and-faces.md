# Replay & faces

A match log is the single source of truth, and the arena renders it into several
**faces** — one declaration, many projections — each derived from the same fold,
so they can never disagree about what happened. Design rationale and the shared
geometry live in [`docs/replay-design.md`](../replay-design.md).

## Self-contained HTML replay

```bash
league match replay <id> > match.html    # open in any browser
```

One file, both light and dark themes, **no external requests** — nothing to
serve, nothing to install. `match replay` detects the engine lane from the log
itself:

- **Grid face** (`league/replay/html.py`) — the turn-based board.
- **Continuous face** (`league/replay/chtml.py`) — the real-time race made
  visible. Its frame-v5 "full replay" is a playable board with transport
  (play/pause, a whole-match scrubber, step-to-moment buttons, 0.5×–4× speed),
  movement interpolated from each action's own start/completion times, mission
  markers, and a seekable event feed.

## Markdown briefing (the agents' face)

```bash
league match brief <id>              # markdown the agents read
league match brief <id> --json       # the SAME facts, structured
league match brief <id> --team blue  # fogged to one team
```

`brief` is served from the faces registry (`league/faces/`); its `--json` returns
the exact facts the markdown renders — proven fact-for-fact by the
face-agreement tests. See [Fog of war](fog-of-war.md) for `--team`.

## Terminal view

```bash
league match tui <id> --frame N [--team blue] [--no-color]
```

A replay-stepping terminal view (`league/replay/tui.py`) — ground truth, or one
team's fog.

## Shareable video (offline)

```bash
league match record <id> --out match.gif                  # pure-stdlib animated GIF
league match record <id> --out match.mp4 --format mp4     # + seeded soundtrack (needs ffmpeg)
league match record <id> --out m.gif --scale 32 --fps 3 --tween 4
```

`record` (`league/replay/video.py`) renders the log to a video file **entirely
offline** — no screen capture, no live session, no network. GIF uses a hand-rolled
LZW encoder so it always works with zero dependencies; MP4 pipes the same frames
through `ffmpeg` if present (and fails with a remediated error naming the GIF
fallback if not). Output is reproducible by construction — the same log at the
same settings renders byte-identical, and the exact command is embedded in the
file's metadata so provenance travels with the artifact.

## Generative audio

The HTML replay carries a **seeded ambient WebAudio score** (a lydian pad bed
plus event motifs, teams in different registers, denials audibly landing), OFF by
default behind an accessible transport toggle. The MP4 export muxes the *same*
seeded piece, synthesized offline to a pure-stdlib WAV (`league/replay/audio.py`).
The GIF stays silent because GIF has no audio channel — format truth, not a
missing feature.

## See also

- [Continuous lane](continuous-lane.md) — the engine behind the continuous face.
- [Deterministic engine](deterministic-engine.md) — why every face agrees.
