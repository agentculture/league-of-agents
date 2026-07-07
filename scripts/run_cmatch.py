#!/usr/bin/env python3
"""Run a live continuous-lane match from a config file and persist its log.

The continuous lane ships as a library this cycle (``league.charness.run_cmatch``
— plan C7-t7); its CLI noun group is deliberately deferred, so this script is
the thin operator entry the playtests use until that cycle lands: read a config
JSON (same shape the grid harness configs use — ``match`` + ``teams`` with
``driver`` specs), run the match, write the log where the store convention puts
every match (``.league/matches/<id>/log.jsonl`` in the CWD — engine-agnostic,
as ``league match replay`` already reads continuous logs from it), and print a
one-line JSON summary to stdout. stdlib only.

Usage:  python3 scripts/run_cmatch.py <config.json>
"""

from __future__ import annotations

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from league.charness import run_cmatch  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: run_cmatch.py <config.json>", file=sys.stderr)
        return 1
    config = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    result = run_cmatch(config)
    log = result["log"]
    match_dir = pathlib.Path.cwd() / ".league" / "matches" / result["match_id"]
    match_dir.mkdir(parents=True, exist_ok=True)
    (match_dir / "log.jsonl").write_text(log.to_jsonl(), encoding="utf-8")
    print(
        json.dumps(
            {
                "match_id": result["match_id"],
                "status": result["status"],
                "game_time": result["game_time"],
                "winner": result["winner"],
                "outcome_points": result["outcome_points"],
                "events": len(log.events),
                "log": str(match_dir / "log.jsonl"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
