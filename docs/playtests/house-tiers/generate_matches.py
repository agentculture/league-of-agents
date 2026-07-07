#!/usr/bin/env python3
"""Regenerate the house-tier roster's recorded proof matches (plan task t4,
spec c12/h11): gold (bots/vanguard.py) vs silver (bots/rusher.py), and silver
vs bronze (bots/shambler.py), two seeds each, run through the public harness
exactly the way any other bot-file match would be (``league.harness.
run_match``).

Matches are fully deterministic (the engine imports no ``random``/wall
clock and the ``seed`` field carries no RNG — spec c9): re-running this
script reproduces byte-identical logs, so the artifacts it writes under
``docs/playtests/house-tiers/`` are safe to regenerate any time the bots
change and re-commit.

Usage (from the repo root, matching the season-0 playtest convention):

    uv run python docs/playtests/house-tiers/generate_matches.py
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404 - fixed argv, no shell, dev-only tooling script
import sys
import tempfile
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

# (output slug, blue strategy, red strategy, seed)
MATCHES = [
    ("gold-vs-silver-seed101", "vanguard", "rusher", 101),
    ("gold-vs-silver-seed202", "vanguard", "rusher", 202),
    ("silver-vs-bronze-seed101", "rusher", "shambler", 101),
    ("silver-vs-bronze-seed202", "rusher", "shambler", 202),
]


def _config(match_id: str, blue: str, red: str, seed: int) -> dict:
    return {
        "match": {"scenario": "skirmish-1", "mode": "competitive", "seed": seed, "id": match_id},
        "teams": [
            {
                "id": "blue",
                "name": f"Blue {blue.capitalize()}",
                "driver": {"type": "bot-file", "strategy": blue},
                "agents": [
                    {"id": "blue-1", "model": f"bot-file:{blue}", "role": "scout"},
                    {"id": "blue-2", "model": f"bot-file:{blue}", "role": "harvester"},
                    {"id": "blue-3", "model": f"bot-file:{blue}", "role": "defender"},
                ],
            },
            {
                "id": "red",
                "name": f"Red {red.capitalize()}",
                "driver": {"type": "bot-file", "strategy": red},
                "agents": [
                    {"id": "red-1", "model": f"bot-file:{red}", "role": "scout"},
                    {"id": "red-2", "model": f"bot-file:{red}", "role": "harvester"},
                    {"id": "red-3", "model": f"bot-file:{red}", "role": "defender"},
                ],
            },
        ],
        "max_rounds": 32,
    }


def _run_cli(cwd: Path, argv: list[str]) -> str:
    proc = subprocess.run(  # nosec B603
        [sys.executable, "-m", "league", *argv],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


def main() -> None:
    for slug, blue, red, seed in MATCHES:
        match_id = f"m-house-{slug}"
        config = _config(match_id, blue, red, seed)
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            (cwd / "config.json").write_text(json.dumps(config, indent=2) + "\n")
            _run_cli(cwd, ["harness", "run", "--config", "config.json", "--apply"])

            score_out = _run_cli(cwd, ["match", "score", match_id, "--json"])
            replay_out = _run_cli(cwd, ["match", "replay", match_id])
            log_path = cwd / ".league" / "matches" / match_id / "log.jsonl"

            (OUT_DIR / f"{slug}.config.json").write_text(json.dumps(config, indent=2) + "\n")
            shutil.copyfile(log_path, OUT_DIR / f"{slug}.log.jsonl")
            (OUT_DIR / f"{slug}.replay.html").write_text(replay_out)
            (OUT_DIR / f"{slug}.score.json").write_text(score_out)

            score = json.loads(score_out)
            print(
                f"{slug}: winner={score['winner']} "
                f"blue={score['outcome']['blue']['total']} "
                f"red={score['outcome']['red']['total']}"
            )


if __name__ == "__main__":
    main()
