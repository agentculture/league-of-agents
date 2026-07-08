"""``league-of-agents learn`` — the learnability affordance.

Prints a structured self-teaching prompt. Must satisfy the agent-first rubric:
>=200 chars and mention purpose, command map, exit codes, --json, and explain.
"""

from __future__ import annotations

import argparse

from league import __version__
from league.cli._output import emit_result

_TEXT = """\
league-of-agents — a strategy arena where agent teams compete under constraint.

Purpose
-------
A cooperative/competitive arena: agent teams complete missions, control
objectives, manage resources, and out-coordinate opposing teams. Matches are
deterministic and replayable, scored on both mission outcome and cooperation
quality, beautiful for humans and --json-practical for agents. The core question
it answers: can this group of agents become a coherent, strategic team under
constraint? Drive it through this agent-first CLI (cited from the teken
`python-cli` reference).

Introspection
-------------
  league-of-agents whoami             Identity from culture.yaml.
  league-of-agents learn              This self-teaching prompt.
  league-of-agents explain <path>...  Markdown docs for any noun/verb path.
  league-of-agents overview           Descriptive snapshot of the agent.
  league-of-agents doctor             Check the agent-identity invariants.
  league-of-agents cli overview       Describe the CLI surface itself.

The arena
---------
  league arena list|show              The scenario catalog (read-only).
  league team register|list|show      Rosters: agent seats as id:model:role.
  league match new|act|tick|show|list The play loop: stage orders, resolve.
  league match score|probe|brief      Read the log: dual scores + MVP/LVP,
                                      span-of-control, the agents' briefing.
  league match replay|record|tui      Watch it: HTML replay, GIF/MP4, terminal.
  league match rematch                Same scenario+seed, new roster.
  league standings|history            Cross-match trends, per team and agent.
  league harness run                  Play a configured match with live drivers.
  league play list|show|start         One-command launch of a bundled mode.

Write verbs (team register, match new/act/tick/rematch, harness run, play start)
are dry-run by default; add --apply to commit.

Machine-readable output
-----------------------
Every read verb supports --json. Errors in JSON mode emit
{"code", "message", "remediation"} to stderr. Stdout and stderr never mix.

Exit-code policy
----------------
  0 success
  1 user-input error (bad flag, bad path, missing arg)
  2 environment / setup error
  3+ reserved

More detail
-----------
  league-of-agents explain league-of-agents
  league-of-agents explain match
"""


def _as_json_payload() -> dict[str, object]:
    return {
        "tool": "league-of-agents",
        "version": __version__,
        "purpose": (
            "A cooperative/competitive strategy arena where agent teams complete "
            "missions, control objectives, and out-coordinate opposing teams — "
            "deterministic, replayable, scored on outcome and cooperation quality."
        ),
        "commands": [
            {"path": ["whoami"], "summary": "Identity probe from culture.yaml."},
            {"path": ["learn"], "summary": "Self-teaching prompt."},
            {"path": ["explain"], "summary": "Markdown docs by path."},
            {"path": ["overview"], "summary": "Descriptive snapshot of the agent."},
            {"path": ["doctor"], "summary": "Check the agent-identity invariants."},
            {"path": ["cli", "overview"], "summary": "Describe the CLI surface."},
            {"path": ["arena", "list"], "summary": "The scenario catalog."},
            {"path": ["team", "register"], "summary": "Register a team roster."},
            {"path": ["match", "new"], "summary": "Create a match (dry-run by default)."},
            {"path": ["match", "act"], "summary": "Stage a team's orders for the turn."},
            {"path": ["match", "score"], "summary": "Outcome + cooperation + tempo + MVP/LVP."},
            {"path": ["match", "probe"], "summary": "Span-of-control probe from the log."},
            {"path": ["match", "replay"], "summary": "Self-contained HTML replay."},
            {"path": ["match", "record"], "summary": "Offline GIF/MP4 video of the match."},
            {"path": ["standings"], "summary": "Cross-match trends, per team and agent."},
            {"path": ["harness", "run"], "summary": "Play a configured match with live drivers."},
            {"path": ["play", "start"], "summary": "One-command launch of a bundled mode."},
        ],
        "exit_codes": {
            "0": "success",
            "1": "user-input error",
            "2": "environment/setup error",
        },
        "json_support": True,
        "explain_pointer": "league-of-agents explain <path>",
    }


def cmd_learn(args: argparse.Namespace) -> int:
    if getattr(args, "json", False):
        emit_result(_as_json_payload(), json_mode=True)
    else:
        emit_result(_TEXT, json_mode=False)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "learn",
        help="Print a structured self-teaching prompt for agent consumers.",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_learn)
