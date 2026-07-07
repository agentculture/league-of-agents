"""``league standings`` / ``league history`` — read-only trend verbs.

Both are computed on read from the match logs (the queryable store), so they
can never disagree with the record. ``standings`` aggregates per-team and
per-agent records; ``history`` lists finished matches in id order with both
scores per team.
"""

from __future__ import annotations

import argparse

from league.cli._output import emit_result
from league.track import history, standings


def cmd_standings(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    data = standings()
    if json_mode:
        emit_result(data, json_mode=True)
        return 0
    if not data["matches_played"]:
        emit_result("no finished matches yet (see 'league match new')", json_mode=False)
        return 0
    lines = [f"standings — {data['matches_played']} finished match(es)", "", "teams:"]
    for team_id, row in data["teams"].items():
        lines.append(
            f"  {team_id}: {row['wins']}W-{row['losses']}L-{row['draws']}D "
            f"over {row['played']}, outcome {row['outcome_total']}, "
            f"cooperation avg {row['cooperation_avg']}"
        )
    lines.append("agents:")
    for agent_id, row in data["agents"].items():
        lines.append(
            f"  {agent_id} ({row['role']}, {row['model']}): {row['wins']}W/"
            f"{row['matches']}, coop avg {row['cooperation_avg']}, "
            f"orders {row['declared']} ({row['rejected']} rejected)"
        )
    emit_result("\n".join(lines), json_mode=False)
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    rows = history()
    if json_mode:
        emit_result({"matches": rows}, json_mode=True)
        return 0
    if not rows:
        emit_result("no finished matches yet", json_mode=False)
        return 0
    lines = []
    for row in rows:
        teams = ", ".join(
            f"{tid} o{cell['outcome']}/c{cell['cooperation']}" for tid, cell in row["teams"].items()
        )
        lines.append(
            f"{row['match_id']} ({row['scenario_id']}, {row['mode']}, "
            f"{row['turns_played']}t): winner {row['winner'] or '—'} — {teams}"
        )
    emit_result("\n".join(lines), json_mode=False)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    st = sub.add_parser("standings", help="Per-team and per-agent records across matches.")
    st.add_argument("--json", action="store_true", help="Emit structured JSON.")
    st.set_defaults(func=cmd_standings)

    hi = sub.add_parser("history", help="Finished matches in order, with both scores.")
    hi.add_argument("--json", action="store_true", help="Emit structured JSON.")
    hi.set_defaults(func=cmd_history)
