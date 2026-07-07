"""Dual scoring — mission outcome and cooperation quality, from the log alone.

``score_match`` takes a :class:`~league.engine.events.MatchLog` and nothing
else (spec c10/h3): both scores are derived from the persisted record, never
from live state or side-channel judgment. Fold the log, count the facts.

**Outcome score** (per team): completed mission rewards, plus
``CP_POINTS`` per control point owned at the end, plus delivered resources —
the same tally the tick uses to pick a winner.

**Cooperation score** (per team, 0–100) is an honest v0 heuristic (spec c22 —
refined by a later dedicated cycle). Four log-derived signals, each in [0, 1]:

===================  ======  =====================================================
signal               weight  what it measures
===================  ======  =====================================================
delegation_spread    0.30    mean fraction of the roster acting per active turn —
                             one hero doing everything scores low
communication        0.20    fraction of turns with at least one team message,
                             doubled and capped at 1 (every-other-turn = full marks)
plan_coherence       0.20    fraction of acting turns covered by a standing
                             declared plan — action without a plan on record
                             scores low
discipline           0.30    1 − (rejected ÷ declared actions) — wasted/invalid
                             orders burn the score; silence scores zero
===================  ======  =====================================================

``cooperation = round(100 · Σ weight·signal)``. The per-signal breakdown is
returned so a human can see *why* a team scored what it scored (spec h15).
"""

from __future__ import annotations

from typing import Any

from league.engine.events import MatchLog
from league.engine.tick import CP_POINTS, outcome_points

WEIGHTS = {
    "delegation_spread": 0.30,
    "communication": 0.20,
    "plan_coherence": 0.20,
    "discipline": 0.30,
}


def score_match(log: MatchLog) -> dict[str, Any]:
    """Compute both scores for every team, from the log and nothing else."""
    final = log.final_state()
    turns_played = final.turn - log.initial_state.turn

    outcome: dict[str, dict[str, int]] = {}
    totals = outcome_points(final)
    for team in final.teams:
        missions = sum(
            m.reward
            for m in final.missions
            if m.status == "completed" and m.completed_by == team.id
        )
        control = CP_POINTS * sum(1 for c in final.control_points if c.owner == team.id)
        outcome[team.id] = {
            "total": totals[team.id],
            "missions": missions,
            "control": control,
            "resources": team.resources,
        }

    cooperation = {
        team.id: _cooperation_for(log, team.id, len(team.agents), turns_played)
        for team in final.teams
    }

    return {
        "match_id": final.match_id,
        "scenario_id": final.scenario_id,
        "mode": final.mode,
        "turns_played": turns_played,
        "winner": final.winner,
        "outcome": outcome,
        "cooperation": cooperation,
    }


def _cooperation_for(
    log: MatchLog, team_id: str, roster_size: int, turns_played: int
) -> dict[str, Any]:
    declared: dict[int, set[str]] = {}
    rejected_count = 0
    declared_count = 0
    message_turns: set[int] = set()
    plan_turns: set[int] = set()

    for event in log.events:
        if event.data.get("team_id") != team_id:
            continue
        if event.kind == "action_declared":
            declared_count += 1
            declared.setdefault(event.turn, set()).add(str(event.data.get("unit_id")))
        elif event.kind == "action_rejected":
            rejected_count += 1
        elif event.kind == "message_sent":
            message_turns.add(event.turn)
        elif event.kind == "plan_declared":
            plan_turns.add(event.turn)

    acting_turns = sorted(declared)
    if roster_size and acting_turns:
        delegation = sum(len(declared[t]) / roster_size for t in acting_turns) / len(acting_turns)
    else:
        delegation = 0.0

    communication = min(1.0, 2 * len(message_turns) / turns_played) if turns_played else 0.0

    if acting_turns:
        first_plan = min(plan_turns) if plan_turns else None
        covered = (
            [t for t in acting_turns if first_plan is not None and t >= first_plan]
            if first_plan is not None
            else []
        )
        plan_coherence = len(covered) / len(acting_turns)
    else:
        plan_coherence = 0.0

    discipline = (1 - rejected_count / declared_count) if declared_count else 0.0

    signals = {
        "delegation_spread": round(delegation, 4),
        "communication": round(communication, 4),
        "plan_coherence": round(plan_coherence, 4),
        "discipline": round(discipline, 4),
    }
    score = round(100 * sum(WEIGHTS[name] * value for name, value in signals.items()))
    return {"score": score, "signals": signals}
