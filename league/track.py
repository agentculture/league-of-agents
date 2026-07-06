"""Tracking — per-team and per-agent trends across every match on record.

The queryable store is the match-log directory itself (spec c13/h6): every
finished match's log is scored on read, so standings can never disagree with
the record. Matches are ordered by match id — the store carries no wall-clock
timestamps by design (determinism), so id order *is* history order.

Per-agent rows attribute the team's cooperation score to each seat and add
seat-level discipline (declared vs rejected orders for the units that seat
controls) — enough to watch an individual agent improve across matches.
"""

from __future__ import annotations

from typing import Any

from league.engine.events import MatchLog
from league.engine.scoring import score_match
from league.store import Store


def _agent_discipline(log: MatchLog) -> dict[str, dict[str, int]]:
    unit_to_agent = {u.id: u.agent_id for u in log.initial_state.units}
    stats: dict[str, dict[str, int]] = {}
    for event in log.events:
        if event.kind not in ("action_declared", "action_rejected"):
            continue
        agent_id = unit_to_agent.get(str(event.data.get("unit_id")))
        if agent_id is None:
            continue
        row = stats.setdefault(agent_id, {"declared": 0, "rejected": 0})
        row["declared" if event.kind == "action_declared" else "rejected"] += 1
    return stats


def history(store: Store | None = None) -> list[dict[str, Any]]:
    """Chronological (id-ordered) rows, one per finished match."""
    store = store or Store()
    rows: list[dict[str, Any]] = []
    for match_id in store.list_matches():
        log = store.load_match(match_id)
        if log.final_state().status != "finished":
            continue
        report = score_match(log)
        rows.append(
            {
                "match_id": match_id,
                "scenario_id": report["scenario_id"],
                "mode": report["mode"],
                "turns_played": report["turns_played"],
                "winner": report["winner"],
                "teams": {
                    team_id: {
                        "outcome": report["outcome"][team_id]["total"],
                        "cooperation": report["cooperation"][team_id]["score"],
                    }
                    for team_id in report["outcome"]
                },
            }
        )
    return rows


def standings(store: Store | None = None) -> dict[str, Any]:
    """Aggregate per-team and per-agent records across all finished matches."""
    store = store or Store()
    teams: dict[str, dict[str, Any]] = {}
    agents: dict[str, dict[str, Any]] = {}
    played = 0
    for match_id in store.list_matches():
        log = store.load_match(match_id)
        final = log.final_state()
        if final.status != "finished":
            continue
        played += 1
        report = score_match(log)
        discipline = _agent_discipline(log)
        for team in final.teams:
            row = teams.setdefault(
                team.id,
                {"played": 0, "wins": 0, "draws": 0, "losses": 0, "outcome": 0, "coop": []},
            )
            row["played"] += 1
            row["outcome"] += report["outcome"][team.id]["total"]
            row["coop"].append(report["cooperation"][team.id]["score"])
            if final.winner == team.id:
                row["wins"] += 1
            elif final.winner == "draw":
                row["draws"] += 1
            else:
                row["losses"] += 1
            for slot in team.agents:
                arow = agents.setdefault(
                    slot.id,
                    {
                        "model": slot.model,
                        "role": slot.role,
                        "matches": 0,
                        "wins": 0,
                        "coop": [],
                        "declared": 0,
                        "rejected": 0,
                    },
                )
                arow["matches"] += 1
                arow["coop"].append(report["cooperation"][team.id]["score"])
                if final.winner == team.id:
                    arow["wins"] += 1
                seat = discipline.get(slot.id, {})
                arow["declared"] += seat.get("declared", 0)
                arow["rejected"] += seat.get("rejected", 0)

    def _avg(values: list[int]) -> float:
        return round(sum(values) / len(values), 1) if values else 0.0

    return {
        "matches_played": played,
        "teams": {
            team_id: {
                "played": row["played"],
                "wins": row["wins"],
                "draws": row["draws"],
                "losses": row["losses"],
                "outcome_total": row["outcome"],
                "cooperation_avg": _avg(row["coop"]),
                "cooperation_trend": row["coop"],
            }
            for team_id, row in sorted(teams.items())
        },
        "agents": {
            agent_id: {
                "model": row["model"],
                "role": row["role"],
                "matches": row["matches"],
                "wins": row["wins"],
                "cooperation_avg": _avg(row["coop"]),
                "declared": row["declared"],
                "rejected": row["rejected"],
            }
            for agent_id, row in sorted(agents.items())
        },
    }
