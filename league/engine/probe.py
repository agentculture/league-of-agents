"""Span-of-control probe — delegation measured from the committed log alone
(plan task t7, cycle 6 "the watchable, vast arena"). The plan's parked risk
r2, "the span-of-control formula", is resolved BY the unit tests in
``tests/test_engine_probe.py`` on synthetic logs, not by prose (the same
discipline ``league.engine.scoring``'s v1 used for its own risk r1).

``probe_match`` answers, per team, exactly what a delegating mind must prove
and nothing it merely claims:

* **How many subagents did it actually field?** (``span``) — a seat counts
  only when the log itself shows real harness-recorded evidence of that seat
  acting, never because a message NAMES it. A team whose only "delegation" is
  a sentence like "I've assigned unit-2 the west flank", with no
  ``seat_latency``, no ``action_declared``/``action_rejected`` tied to that
  seat's unit, and no message actually spoken in that seat's own voice,
  fields ZERO subagents for the claim
  (``test_claimed_delegation_without_any_evidence_scores_zero`` pins this).
* **How well did each subagent's orders land?** (``realization_rate``) — per
  seat, ``1 - rejected/declared`` (silence scores zero, the same convention
  ``league.engine.scoring``'s ``discipline`` already uses). Only a genuine
  declared-order rejection counts here (issue #31): a ``passive`` ``action_
  rejected`` — a capture-incapable unit merely standing on a point, fired
  from occupancy every turn regardless of what the unit itself declared —
  is excluded from both the numerator and (via ``match show``'s
  ``last_turn_rejections``) the harness's rejection-feedback loop, so a
  scout parked on a contested point no longer drags its own clean orders'
  realization_rate toward zero.
* **Did guidance actually steer behavior?** (``guidance_linkage``) — reusing
  the referent-matching machinery from cooperation v1's ``message_utility``
  (:func:`league.engine.scoring._build_action_index`,
  :func:`league.engine.scoring._utterance_useful`): a commanding message
  counts only if some team action, in-window, realizes something it named.
* **How does command quality degrade as span grows?** (``degradation_curve``)
  — turns are bucketed by how many active seats declared an action
  CONCURRENTLY that turn, each bucket averaging that turn's realization; a
  single match can show "commands 2 well, 1 badly" without needing a second
  match to compare against (see ``test_per_seat_realization_and_
  degradation_curve_show_command_quality``). Comparing this across matches of
  different span (plan task t9) is how the curve extends beyond one match.

Evidence hierarchy (spec c10/h10; the honesty condition is "real spawned
subagents through the harness, not simulated fan-out"):

1. ``seat_latency`` OBSERVATION events (``league.engine.events``) are
   AUTHORITATIVE whenever the team has any at all: a per-seat driver call
   (``agent_id`` AND ``unit_id`` both set) is direct harness-recorded proof of
   a real per-seat mind; an orchestrator-mode-for-real master's own call
   (``agent_id`` set, ``unit_id`` ``None``) identifies a COMMANDER, never a
   seat; a whole-team call (``agent_id`` ``None``) proves the opposite — one
   mind, not per-seat delegation, however many personas its messages narrate
   (``docs/playtests/cycle-4/solo-vs-bot.log.jsonl``: the solo team's three
   seats each speak in the first person, but every ``seat_latency`` entry is
   ``agent_id=None`` — span 0/1, never 3).
2. Only when a team has NO ``seat_latency`` events anywhere in the log (every
   log recorded before plan C4-t1, e.g.
   ``docs/playtests/season-0/orchestrator.log.jsonl``) does the probe fall
   back to a stricter, DUAL-evidence heuristic: an agent_id is an active seat
   only if it OWNS a unit (the roster mapping off ``initial_state.units``,
   fixed for the whole match — no event ever changes a unit's owner) AND that
   unit has a real ``action_declared``/``action_rejected`` event AND the
   agent_id itself appears as a message's ``from`` (its own voice, never
   someone else narrating on its behalf). Both conditions must hold.

Like the rest of ``league.engine`` this module reads the log and nothing
else: no ``time``/``random``/``datetime``/``secrets``/``uuid`` import (the
determinism ban, package-wide), and it never touches
``MatchState``/``state_hash`` — a pure, read-only, log-derived report,
mirroring ``league.engine.scoring``'s and ``league.engine.tempo``'s payload
style: ``{score, signals, components, version}`` per team.
"""

from __future__ import annotations

from typing import Any

from league.engine.events import MatchLog
from league.engine.scoring import CORRELATION_WINDOW, _build_action_index, _utterance_useful

# The read-time formula's version tag, echoed in every payload (mirrors
# league.engine.scoring/tempo's own VERSION constants). Bump it when the
# formula changes; recorded logs stay valid, only the derived report moves.
PROBE_VERSION = "p0"

# Named, tested weights (risk r2 resolved by tests/test_engine_probe.py, not
# by prose) — sum to 1.0; every divergence from a season's prior probe run
# traces to exactly one of these three axes.
PROBE_WEIGHTS = {
    "span_coverage": 0.25,  # active (evidenced) seats / registered roster seats
    "realization_rate": 0.45,  # mean per-seat (1 - rejected/declared)
    "guidance_linkage": 0.30,  # commander/peer messages whose referents realize
}

# The referent-matching window a commanding message's realization is checked
# within — reused verbatim from cooperation v1's tactical-callout window
# (league.engine.scoring.CORRELATION_WINDOW), so "guidance that works" means
# the same thing in both scores.
GUIDANCE_WINDOW = CORRELATION_WINDOW


def _roster(log: MatchLog) -> dict[str, dict[str, str]]:
    """``{team_id: {unit_id: agent_id}}`` off the fixed initial roster.

    A unit's ``agent_id`` never changes mid-match — no event mutates it (see
    ``league.engine.events.apply_event``) — so the initial state alone is the
    whole answer, exactly like ``league.engine.scoring``'s own unit->team map.
    """
    roster: dict[str, dict[str, str]] = {}
    for unit in log.initial_state.units:
        roster.setdefault(unit.team_id, {})[unit.id] = unit.agent_id
    return roster


def _units_of(roster_team: dict[str, str], agent_id: str) -> set[str]:
    return {unit_id for unit_id, owner in roster_team.items() if owner == agent_id}


def _evidence(
    log: MatchLog, team_ids: list[str], roster: dict[str, dict[str, str]]
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, str]]:
    """Active seats + commanders + the evidence mode used, per team.

    See the module docstring's "Evidence hierarchy" for the two modes.
    """
    has_latency: dict[str, bool] = {tid: False for tid in team_ids}
    latency_seats: dict[str, set[str]] = {tid: set() for tid in team_ids}
    latency_commanders: dict[str, set[str]] = {tid: set() for tid in team_ids}
    for event in log.events:
        if event.kind != "seat_latency":
            continue
        team_id = event.data.get("team_id")
        if team_id not in has_latency:
            continue
        has_latency[team_id] = True
        agent_id = event.data.get("agent_id")
        if agent_id is None:
            continue  # a whole-team call: proves the OPPOSITE of per-seat delegation
        if event.data.get("unit_id") is not None:
            latency_seats[team_id].add(agent_id)
        else:
            latency_commanders[team_id].add(agent_id)

    message_from: dict[str, set[str]] = {tid: set() for tid in team_ids}
    declared_units: dict[str, set[str]] = {tid: set() for tid in team_ids}
    for event in log.events:
        team_id = event.data.get("team_id")
        if team_id not in message_from:
            continue
        if event.kind == "message_sent":
            frm = event.data.get("from")
            if frm is not None:
                message_from[team_id].add(str(frm))
        elif event.kind in ("action_declared", "action_rejected"):
            unit_id = event.data.get("unit_id")
            if unit_id is not None:
                declared_units[team_id].add(str(unit_id))

    active: dict[str, set[str]] = {}
    commanders: dict[str, set[str]] = {}
    mode: dict[str, str] = {}
    for team_id in team_ids:
        roster_team = roster.get(team_id, {})
        if has_latency[team_id]:
            mode[team_id] = "latency"
            active[team_id] = set(latency_seats[team_id])
            commanders[team_id] = set(latency_commanders[team_id])
            continue
        mode[team_id] = "fallback"
        seats: set[str] = set()
        for agent_id in message_from[team_id]:
            owned = _units_of(roster_team, agent_id)
            if owned and owned & declared_units[team_id]:
                seats.add(agent_id)
        active[team_id] = seats
        commanders[team_id] = {
            agent_id for agent_id in message_from[team_id] if not _units_of(roster_team, agent_id)
        }
    return active, commanders, mode


def _seat_orders(
    log: MatchLog, team_id: str, roster_team: dict[str, str], active_seats: set[str]
) -> tuple[dict[str, dict[str, int]], dict[int, dict[str, Any]]]:
    """Per-seat declared/rejected counts, plus per-turn concurrency data the
    degradation curve buckets on — both read off the same unit->agent roster
    lookup applied to ``action_declared``/``action_rejected`` events.

    A ``passive`` ``action_rejected`` (issue #31: a capture-incapable unit
    merely standing on a contested/owned point, fired from occupancy every
    turn it recurs — ``league.engine.tick``'s section 7 — regardless of
    whether the unit's own declared order that turn succeeded) is excluded
    here entirely: it never counted as a real declared-order mistake, so it
    must not inflate ``rejected`` in either the per-seat realization_rate or
    the degradation curve's per-turn bucket. A genuine declared-order
    rejection never carries this marker and still counts in full.
    """
    seat_counts: dict[str, dict[str, int]] = {
        a: {"declared": 0, "rejected": 0} for a in active_seats
    }
    turns: dict[int, dict[str, Any]] = {}
    for event in log.events:
        if event.data.get("team_id") != team_id:
            continue
        if event.kind not in ("action_declared", "action_rejected"):
            continue
        if event.kind == "action_rejected" and event.data.get("passive"):
            continue
        unit_id = event.data.get("unit_id")
        agent_id = roster_team.get(str(unit_id))
        bucket = turns.setdefault(event.turn, {"agents": set(), "declared": 0, "rejected": 0})
        if event.kind == "action_declared":
            bucket["declared"] += 1
            if agent_id in active_seats:
                seat_counts[agent_id]["declared"] += 1
                bucket["agents"].add(agent_id)
        else:
            bucket["rejected"] += 1
            if agent_id in active_seats:
                seat_counts[agent_id]["rejected"] += 1
    return seat_counts, turns


def _degradation_curve(turns: dict[int, dict[str, Any]]) -> dict[str, float]:
    """Mean per-turn realization, bucketed by how many active seats declared
    an action CONCURRENTLY that turn — the within-match answer to "how does
    command quality degrade as N grows" (plan risk r2): a bucket value that
    drops as the span key grows shows a mind whose orders bounce more once it
    is juggling more seats at once; a flat table shows one that holds up.
    """
    buckets: dict[int, list[float]] = {}
    for data in turns.values():
        concurrent_span = len(data["agents"])
        declared = data["declared"]
        if concurrent_span == 0 or declared == 0:
            continue
        realization = 1.0 - data["rejected"] / declared
        buckets.setdefault(concurrent_span, []).append(realization)
    return {str(span): round(sum(vals) / len(vals), 4) for span, vals in sorted(buckets.items())}


def _guidance_linkage(
    log: MatchLog, team_id: str, speakers: set[str], index: Any
) -> dict[str, Any]:
    """Fraction of ``speakers``' messages whose named referents are realized
    by a subsequent team action within :data:`GUIDANCE_WINDOW` turns — the
    "master/commander → seat message flow" acceptance criterion. When no
    commander is distinguishable (peer-only coordination, e.g. the real
    season-0 orchestrator log), ``speakers`` falls back to the active seats
    themselves: peer guidance that steers a teammate's action is still real
    command quality, not narration.
    """
    messages = [
        (event.turn, str(event.data.get("text", "")))
        for event in log.events
        if event.kind == "message_sent"
        and event.data.get("team_id") == team_id
        and event.data.get("from") in speakers
    ]
    useful = sum(
        1
        for turn, text in messages
        if _utterance_useful(index, team_id, turn, text, GUIDANCE_WINDOW)
    )
    value = useful / len(messages) if messages else 0.0
    return {"messages": len(messages), "useful": useful, "value": round(value, 4)}


def probe_match(log: MatchLog) -> dict[str, Any]:
    """Span-of-control per team, from the log alone.

    Returns ``{"match_id", "version", "teams": {team_id: {"span",
    "roster_size", "evidence", "commanders", "score", "signals",
    "components", "version"}}}``. See the module docstring for the evidence
    hierarchy and :data:`PROBE_WEIGHTS` for the scoring formula.
    """
    final = log.final_state()
    team_ids = [team.id for team in final.teams]
    roster = _roster(log)
    active, commanders, mode = _evidence(log, team_ids, roster)
    index = _build_action_index(log)

    teams: dict[str, Any] = {}
    for team in final.teams:
        team_id = team.id
        roster_team = roster.get(team_id, {})
        active_seats = active.get(team_id, set())
        roster_size = len(team.agents)
        seat_counts, turns = _seat_orders(log, team_id, roster_team, active_seats)

        per_seat: dict[str, dict[str, Any]] = {}
        realizations: list[float] = []
        for agent_id in sorted(active_seats):
            counts = seat_counts[agent_id]
            declared, rejected = counts["declared"], counts["rejected"]
            realization = (1.0 - rejected / declared) if declared else 0.0
            per_seat[agent_id] = {
                "declared": declared,
                "rejected": rejected,
                "realization_rate": round(realization, 4),
            }
            realizations.append(realization)

        span = len(active_seats)
        span_coverage = span / roster_size if roster_size else 0.0
        mean_realization = sum(realizations) / len(realizations) if realizations else 0.0

        team_commanders = commanders.get(team_id, set())
        speakers = team_commanders or active_seats
        guidance = _guidance_linkage(log, team_id, speakers, index)

        signals = {
            "span_coverage": round(span_coverage, 4),
            "realization_rate": round(mean_realization, 4),
            "guidance_linkage": guidance["value"],
        }
        score = round(100 * sum(PROBE_WEIGHTS[name] * value for name, value in signals.items()))
        teams[team_id] = {
            "span": span,
            "roster_size": roster_size,
            "evidence": mode.get(team_id, "fallback"),
            "commanders": sorted(team_commanders),
            "score": score,
            "signals": signals,
            "components": {
                "span_coverage": {
                    "active": span,
                    "roster": roster_size,
                    "value": signals["span_coverage"],
                },
                "realization_rate": {"per_seat": per_seat, "value": signals["realization_rate"]},
                "guidance_linkage": guidance,
                "degradation_curve": _degradation_curve(turns),
            },
            "version": PROBE_VERSION,
        }

    return {"match_id": final.match_id, "version": PROBE_VERSION, "teams": teams}
