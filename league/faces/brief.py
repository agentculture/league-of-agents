"""The match-brief projection: one fact fold, two renderings (JSON + markdown).

``brief_facts`` is the ONE declaration both faces derive from — a pure
projection of the match log (via the same folds every other face uses:
``MatchLog.final_state`` / ``score_match`` for ground truth,
``league.engine.knowledge.latest_knowledge`` for the fogged per-team variant).
``render_brief_markdown`` renders those facts — and only those facts — as
markdown, in a deliberately parseable shape (title + ``- key: value`` bullets +
one table per section) so the face-agreement test in ``tests/test_faces.py``
can parse the markdown back into facts and assert *exact* equality with the
JSON face. Anything the markdown shows is in the facts; anything in the facts
is shown.

This module is deliberately stdlib+engine only: the agentfront registry that
serves the projection lives in ``league/faces/__init__.py`` (the package's one
agentfront importer — see ``tests/test_faces.py``).

Fog note: the fogged variant (``team=...``) renders the per-team knowledge
fold — last-seen and told facts, never live ground truth — plus the team's own
resources. It never includes scores or the opponent's resource count: those
are computed from the full log and would leak information fog exists to hide.
"""

from __future__ import annotations

from typing import Any

from league.engine.events import MatchLog
from league.engine.knowledge import latest_knowledge
from league.engine.scenario import get_scenario
from league.engine.scoring import score_match


def brief_facts(log: MatchLog, *, team: str | None = None) -> dict[str, Any]:
    """Project a match log to briefing facts — the JSON face.

    With ``team`` the projection is fogged: the named team's knowledge fold
    (seen/told facts) plus its own resources. Unknown teams raise a loud
    ``ValueError`` (the CLI maps it to a user error).
    """
    state = log.final_state()
    facts: dict[str, Any] = {
        "match_id": state.match_id,
        "scenario": state.scenario_id,
        "mode": state.mode,
        "seed": state.seed,
        "turn": state.turn,
        "turn_limit": state.turn_limit,
        "status": state.status,
        "winner": state.winner,
    }
    if team is None:
        scores = score_match(log)
        facts["teams"] = [
            {
                "team": t.id,
                "resources": t.resources,
                "outcome": scores["outcome"][t.id]["total"],
                "cooperation": scores["cooperation"][t.id]["score"],
            }
            for t in state.teams
        ]
        facts["units"] = [
            {
                "unit": u.id,
                "team": u.team_id,
                "role": u.role,
                "pos": list(u.pos),
                "carrying": u.carrying,
                "alive": u.alive,
            }
            for u in state.units
        ]
        facts["control_points"] = [
            {"id": c.id, "pos": list(c.pos), "owner": c.owner} for c in state.control_points
        ]
        facts["missions"] = [
            {
                "id": m.id,
                "kind": m.kind,
                "pos": list(m.pos),
                "amount": m.amount,
                "reward": m.reward,
                "status": m.status,
                "completed_by": list(m.completed_by),
            }
            for m in state.missions
        ]
        facts["resource_nodes"] = [
            {"id": r.id, "pos": list(r.pos), "remaining": r.remaining} for r in state.resource_nodes
        ]
        return facts

    team_ids = sorted(t.id for t in state.teams)
    if team not in team_ids:
        raise ValueError(
            f"team {team!r} is not in match {state.match_id!r}; teams: {', '.join(team_ids)}"
        )
    frame = latest_knowledge(log, get_scenario(state.scenario_id))[team]
    own = next(t for t in state.teams if t.id == team)
    facts["team"] = team
    facts["resources"] = own.resources
    facts["cells_seen"] = len(frame.cells_seen)
    facts["known_units"] = [
        {
            "unit": k.id,
            "team": k.team_id,
            "role": k.role,
            "pos": list(k.pos) if k.pos is not None else None,
            "alive": k.alive,
            "turn": k.turn,
            "source": k.source,
        }
        for k in frame.units
    ]
    facts["known_resource_nodes"] = [
        {
            "id": k.id,
            "pos": list(k.pos),
            "remaining": k.remaining,
            "turn": k.turn,
            "source": k.source,
        }
        for k in frame.resource_nodes
    ]
    facts["known_control_points"] = [
        {"id": k.id, "pos": list(k.pos), "owner": k.owner, "turn": k.turn, "source": k.source}
        for k in frame.control_points
    ]
    return facts


def _cell(value: Any) -> str:
    """One table cell, losslessly: the test parser inverts every branch here."""
    if value is None:
        return "none"
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if isinstance(value, list):
        if not value:
            return "none"
        if len(value) == 2 and all(isinstance(v, int) for v in value):
            return f"{value[0]},{value[1]}"  # a position
        return ", ".join(str(v) for v in value)  # an id list (ids never hold commas)
    return str(value)


def _table(columns: tuple[str, ...], fields: tuple[str, ...], rows: list[dict[str, Any]]) -> str:
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    lines += ["| " + " | ".join(_cell(row[f]) for f in fields) + " |" for row in rows]
    return "\n".join(lines)


# (section title, facts key, columns, row fields) — full face, then fogged face.
_FULL_SECTIONS: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "Teams",
        "teams",
        ("team", "resources", "outcome", "cooperation"),
        ("team", "resources", "outcome", "cooperation"),
    ),
    (
        "Units",
        "units",
        ("unit", "team", "role", "pos", "carrying", "alive"),
        ("unit", "team", "role", "pos", "carrying", "alive"),
    ),
    ("Control points", "control_points", ("id", "pos", "owner"), ("id", "pos", "owner")),
    (
        "Missions",
        "missions",
        ("id", "kind", "pos", "amount", "reward", "status", "completed-by"),
        ("id", "kind", "pos", "amount", "reward", "status", "completed_by"),
    ),
    ("Resource nodes", "resource_nodes", ("id", "pos", "remaining"), ("id", "pos", "remaining")),
)

_FOGGED_SECTIONS: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "Known units",
        "known_units",
        ("unit", "team", "role", "pos", "alive", "turn", "source"),
        ("unit", "team", "role", "pos", "alive", "turn", "source"),
    ),
    (
        "Known resource nodes",
        "known_resource_nodes",
        ("id", "pos", "remaining", "turn", "source"),
        ("id", "pos", "remaining", "turn", "source"),
    ),
    (
        "Known control points",
        "known_control_points",
        ("id", "pos", "owner", "turn", "source"),
        ("id", "pos", "owner", "turn", "source"),
    ),
)


def render_brief_markdown(facts: dict[str, Any]) -> str:
    """The markdown face: the same facts ``brief_facts`` returned, as markdown."""
    fogged = "team" in facts
    title = f"# league match brief — {facts['match_id']}"
    if fogged:
        title += f" (team {facts['team']})"
    bullets = [
        f"- scenario: {facts['scenario']}",
        f"- mode: {facts['mode']}",
        f"- seed: {facts['seed']}",
        f"- turn: {facts['turn']}/{facts['turn_limit']}",
        f"- status: {facts['status']}",
        f"- winner: {_cell(facts['winner'])}",
    ]
    if fogged:
        bullets += [
            f"- team: {facts['team']}",
            f"- resources: {facts['resources']}",
            f"- cells-seen: {facts['cells_seen']}",
        ]
    parts = [title, "", "\n".join(bullets)]
    for section, key, columns, fields in _FOGGED_SECTIONS if fogged else _FULL_SECTIONS:
        parts += ["", f"## {section}", "", _table(columns, fields, facts[key])]
    return "\n".join(parts)
