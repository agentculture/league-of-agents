#!/usr/bin/env python3
"""Harness driver that fields a live Claude AGENT as a continuous-lane seat.

The continuous harness (``league/charness.py``) hands ``command`` drivers the
raw briefing JSON — deliberately: what a mind is TOLD about the contract is the
operator's call, not the engine's (the grid lane bakes prompts into the harness;
parity is a cycle-8 candidate, recorded in the cycle-7 report). This script is
that operator layer for a ``claude`` seat: it wraps the briefing in the
mind-facing contract from ``docs/continuous-contract.md`` on first contact,
then threads every later decision point into the SAME ``claude`` session
(``--session-id`` once, ``--resume`` after) — a resident seat, the same
field-the-agent-not-the-API doctrine ``scripts/colleague_driver.py`` set for
colleague seats in season 0. stdlib only.

Usage (as a continuous-harness command driver):

    {"type": "command", "residency": "resident",
     "argv": ["python3", "scripts/cseat_driver.py", "--model", "sonnet"],
     "timeout": 240}

Session state lives under ``.league/cseat-sessions/`` in the CWD (gitignored
with the rest of ``.league/``), keyed by match id + agent id, so a crashed
match resumes its seats instead of amnesia-ing them.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess  # nosec B404
import sys
import uuid

_CONTRACT = """You are {agent_id}, a live mind playing ONE unit ({unit_id}, role {role}) \
for team {team_id} in a continuous-time League of Agents arena match.

How this arena works — read carefully, it is NOT turn-based:
- Time is INTEGER GAME-TIME, never wall-clock: your thinking time does not advance the \
clock. Every action has an in-game duration; while your unit executes one, the rest of \
the world keeps moving on its own timeline. You are consulted again exactly when your \
unit becomes idle (action completed, failed, or interrupted).
- Positions are fixed-point ("mu" = milliunits; 1000 mu = 1 distance unit). Roles move \
at different speeds and act at different durations — the role table is lopsided on \
purpose.
- Actions RACE. Taking a control point takes real duration; several units (even from \
both teams) can be mid-take on the same post at once, and the FIRST to complete wins it \
— everyone else's attempt fails with "post taken by a faster agent". Starting first \
does not mean finishing first: a faster role that starts later can still beat you. \
Check "takers" on each control point and the menu's completion_time before committing.
- Scoring is outcome points: held control points plus mission rewards for delivered \
resources. No single unit can win the race AND run the economy inside the time limit — \
split the labor with your teammate and say what you are doing.

Each decision point you receive ONE JSON briefing:
- game_time — the integer clock right now.
- you — your unit: position, carrying, role, current action (null = idle).
- menu — the ONLY actions legal for you right now; each entry carries kind, duration, \
completion_time (absolute), and target/target_id.
- outlook — which units finish their current action soonest; plan your timing around \
who frees up when.
- board — full ground truth: teams, units, control_points (with live takers), \
missions, resource_nodes.
- messages — every broadcast so far; your teammates see yours at their next decision.

Reply with EXACTLY ONE JSON object and nothing else — no prose, no code fences:
{{"action": <ONE entry copied verbatim from menu>, "message": "<optional short \
broadcast to your team>", "plan": "<optional: declare your team's plan, once>"}}
An action not on the menu parks your unit for this decision (wasted time). Use \
{{"action": null}} only to deliberately wait.

Your first briefing follows.

{briefing}"""

_DELTA = """Decision point at game_time {game_time} — same match, same rules, same \
reply contract (exactly one JSON object, action copied verbatim from menu or null).

{briefing}"""


def _session_path(match_id: str, agent_id: str) -> pathlib.Path:
    root = pathlib.Path.cwd() / ".league" / "cseat-sessions"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{match_id}--{agent_id}.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="sonnet", help="claude CLI --model value")
    parser.add_argument("--command", default="claude", help="claude CLI executable")
    parser.add_argument(
        "--timeout", type=float, default=210.0, help="per-decision subprocess timeout (s)"
    )
    args = parser.parse_args()

    briefing_raw = sys.stdin.read()
    briefing = json.loads(briefing_raw)
    you = briefing["you"]
    agent_id = str(you["agent_id"])
    match_id = str(briefing.get("board", {}).get("match_id") or "match")

    spath = _session_path(match_id, agent_id)
    if spath.exists():
        session_id = json.loads(spath.read_text(encoding="utf-8"))["session_id"]
        argv = [args.command, "-p", "--resume", session_id, "--model", args.model]
        prompt = _DELTA.format(game_time=briefing["game_time"], briefing=briefing_raw)
    else:
        session_id = str(uuid.uuid4())
        argv = [args.command, "-p", "--session-id", session_id, "--model", args.model]
        prompt = _CONTRACT.format(
            agent_id=agent_id,
            unit_id=you["unit_id"],
            role=you["role"],
            team_id=you["team_id"],
            briefing=briefing_raw,
        )

    proc = subprocess.run(  # nosec B603 — operator-configured argv, shell=False
        argv, input=prompt, capture_output=True, text=True, timeout=args.timeout, check=False
    )
    if proc.returncode != 0:
        print(proc.stderr.strip()[:500], file=sys.stderr)
        return proc.returncode
    if not spath.exists():
        spath.write_text(json.dumps({"session_id": session_id}), encoding="utf-8")
    print(proc.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
