#!/usr/bin/env python3
"""Re-score the committed season-0 logs under cooperation v1 and print/write the
v0-vs-v1 side-by-side comparison (plan task t2, spec c7/h2/h3/c4/h11).

This script does not run any matches — the three ``*.log.jsonl`` files
committed under ``docs/playtests/season-0/`` are the single source of truth
(honesty h1: every report must be reconstructible from the committed log
alone). For each match it:

1. Loads the committed log with ``league.engine.events.MatchLog.from_jsonl``.
2. Re-folds it and scores it twice — ``score_match(log, version="v0")`` and
   ``score_match(log, version="v1")`` (``league/engine/scoring.py``) — pure
   functions of the log, so this is 100% reproducible from what is already on
   disk.
3. Cross-checks the v0 result against the committed ``*.score.json`` (the same
   regression the test suite pins in
   ``tests/test_engine_scoring_v1.py::test_v0_reproduces_committed_season0_scores``)
   so a silent scoring drift would fail loudly here too.
4. Prints a comparison table to stdout and writes the full raw numbers to
   ``cooperation-v1.scores.json`` next to this script, which
   ``cooperation-v1.report.md`` cites as its evidence.

Usage (from the repo root, matching the house-tiers playtest convention):

    uv run python docs/playtests/season-0/rescore_v1.py
"""

from __future__ import annotations

import json
import pathlib
import sys

from league.engine.events import MatchLog
from league.engine.scoring import score_match

OUT_DIR = pathlib.Path(__file__).resolve().parent

# (slug, human label) — the three committed season-0 matches, in playtest order.
MATCHES = [
    ("opener", "Playtest 1 — season opener"),
    ("coordination", "Playtest 2 — coordination necessity"),
    ("orchestrator", "Playtest 3 — orchestrator subagent mode"),
]


def _load(slug: str) -> MatchLog:
    return MatchLog.from_jsonl((OUT_DIR / f"{slug}.log.jsonl").read_text())


def main() -> None:
    results: dict[str, dict] = {}
    mismatches: list[str] = []

    for slug, _label in MATCHES:
        log = _load(slug)
        v0 = score_match(log, version="v0")
        v1 = score_match(log, version="v1")

        committed = json.loads((OUT_DIR / f"{slug}.score.json").read_text())
        if v0 != committed:
            mismatches.append(slug)

        results[slug] = {"v0": v0, "v1": v1}

        print(f"\n=== {slug} (winner: {v0['winner']}) ===")
        header = f"{'team':<10} {'v0':>4} {'v1':>4} {'delta':>6}   v1 components"
        print(header)
        for team_id in v0["cooperation"]:
            s0 = v0["cooperation"][team_id]["score"]
            s1 = v1["cooperation"][team_id]["score"]
            comps = v1["cooperation"][team_id]["signals"]
            comp_str = ", ".join(f"{k}={val}" for k, val in comps.items())
            print(f"{team_id:<10} {s0:>4} {s1:>4} {s1 - s0:>+6}   {comp_str}")

    (OUT_DIR / "cooperation-v1.scores.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n"
    )

    if mismatches:
        print(
            f"\nWARNING: v0 recomputation diverged from committed score.json for: "
            f"{', '.join(mismatches)}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print(f"\nWrote {OUT_DIR / 'cooperation-v1.scores.json'}")


if __name__ == "__main__":
    main()
