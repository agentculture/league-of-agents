#!/usr/bin/env python3
"""Harness driver that fields a live Claude AGENT as a continuous-lane seat.

Transport only (plan C8-t7). The mind-facing seat contract — reply shape,
time model, race semantics, menu discipline, delivery contention, and
(conditionally) fog wording — used to live in a pair of module-level prompt
templates owned by this very script; only a seat fielded through this exact
script ever heard the rules, a lane-parity gap the cycle-7 live report
flagged. The contract now lives in ``league.charness``, baked into the first
decision-point message for every ``command``/``resident`` driver by the
harness itself — see ``docs/continuous-contract.md`` for the text a mind
actually receives.

This script now does exactly one job: thread every decision point for a
``claude`` seat into the SAME resident session (``--session-id`` once,
``--resume`` after) and hand back whatever the model said, verbatim — the
field-the-agent-not-the-API doctrine ``scripts/colleague_driver.py`` set for
colleague seats in season 0. It never composes a prompt of its own; the text
on stdin (contract on first contact, a short delta after) IS the prompt,
forwarded to the ``claude`` CLI unchanged. stdlib only.

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
from typing import Any


def _first_json_object(text: str) -> dict[str, Any]:
    """Find the first parseable JSON object embedded in ``text``.

    The incoming stdin payload is the harness's own baked prompt: contract
    prose wrapped around the briefing on first contact, a short delta note
    wrapped around it on every later decision point (``league.charness``'s
    ``seat_prompt_text``). This script needs only the briefing's own
    ``agent_id``/``match_id`` for session bookkeeping — never the prose
    around it, and it composes none of its own.
    """
    decoder = json.JSONDecoder()
    for start in range(len(text)):
        if text[start] != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError("no JSON object found in harness input")


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

    # Whatever the harness sent — contract-wrapped on first contact, a delta
    # note later — is forwarded to the model exactly as received.
    incoming = sys.stdin.read()
    briefing = _first_json_object(incoming)
    you = briefing["you"]
    agent_id = str(you["agent_id"])
    match_id = str(briefing.get("board", {}).get("match_id") or "match")

    spath = _session_path(match_id, agent_id)
    if spath.exists():
        session_id = json.loads(spath.read_text(encoding="utf-8"))["session_id"]
        argv = [args.command, "-p", "--resume", session_id, "--model", args.model]
    else:
        session_id = str(uuid.uuid4())
        argv = [args.command, "-p", "--session-id", session_id, "--model", args.model]

    proc = subprocess.run(  # nosec B603 — operator-configured argv, shell=False
        argv, input=incoming, capture_output=True, text=True, timeout=args.timeout, check=False
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
