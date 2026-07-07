#!/usr/bin/env python3
"""Harness driver that fields the colleague AGENT as a seat — not its raw API.

Reads the seat/commander prompt on stdin and runs one `colleague work` item
(the agent's bounded tool-loop) in an isolated scratch repo, then prints the
work item's summary — which the seat prompt instructs to be the action JSON.
The harness extracts the first JSON object from whatever we print.

The distinction matters (playtest directive, season 0): a model reached
directly over chat/completions is just an API; colleague is the agent —
harness, loop, and finish contract included — the same way Sonnet seats run
through `claude -p` rather than the Anthropic API. stdlib only.

Usage (as a harness command driver):

    {"type": "command", "per_seat": true,
     "argv": ["python3", "scripts/colleague_driver.py",
              "--model", "sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP"]}

Environment: COLLEAGUE_BASE_URL overrides the default http://localhost:8001/v1.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess  # nosec B404
import sys

_FINISH_CONTRACT = (
    "\n\nIMPORTANT: you are one seat in a live arena match. Do not read or"
    " write files; decide from the briefing above. Call finish with a summary"
    " that is EXACTLY the single JSON object requested above — no prose, no"
    " code fences, nothing else."
)


def _scratch_repo(path: pathlib.Path) -> pathlib.Path:
    """An isolated repo for the work item — the seat never sees this repo."""
    if not (path / ".git").is_dir():
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        (path / "README.md").write_text("# league-of-agents seat sandbox\n", encoding="utf-8")
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "seat",
            "GIT_AUTHOR_EMAIL": "seat@league",
            "GIT_COMMITTER_NAME": "seat",
            "GIT_COMMITTER_EMAIL": "seat@league",
        }
        subprocess.run(  # nosec B603 B607
            ["git", "-C", str(path), "add", "-A"], check=True, env=env
        )
        subprocess.run(  # nosec B603 B607
            ["git", "-C", str(path), "commit", "-qm", "init"], check=True, env=env
        )
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("COLLEAGUE_BASE_URL", "http://localhost:8001/v1"),
    )
    parser.add_argument("--engine", default="vllm-openai")
    parser.add_argument("--max-steps", type=int, default=6)
    parser.add_argument("--mode", default="explore")
    parser.add_argument("--workdir", default=".league/colleague-seat")
    args = parser.parse_args()

    prompt = sys.stdin.read()
    repo = _scratch_repo(pathlib.Path(args.workdir))
    proc = subprocess.run(  # nosec B603 B607
        [
            "colleague",
            "work",
            prompt + _FINISH_CONTRACT,
            "--repo",
            str(repo),
            "--engine",
            args.engine,
            "--model",
            args.model,
            "--base-url",
            args.base_url,
            "--max-steps",
            str(args.max_steps),
            "--mode",
            args.mode,
            "--no-pr",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(proc.stderr.strip()[:500], file=sys.stderr)
        print("error: colleague emitted no result JSON", file=sys.stderr)
        return 1
    summary = (result.get("summary") or "").strip()
    if not summary:
        print(f"error: work item status={result.get('status')} with empty summary", file=sys.stderr)
        return 1
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
