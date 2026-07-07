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

**Cooperation v1** (``version="v1"``, task t1) keeps the same four axes but
scores *quality*, not cadence — see the ``_cooperation_v1`` block below and
``tests/test_engine_scoring_v1.py`` for the pinned weights. v0 stays the default
and its output for existing logs is bit-identical; the two are selected by the
``version`` argument to :func:`score_match`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, NamedTuple

from league.engine.events import MatchLog
from league.engine.tick import CP_POINTS, outcome_points

WEIGHTS = {
    "delegation_spread": 0.30,
    "communication": 0.20,
    "plan_coherence": 0.20,
    "discipline": 0.30,
}


def score_match(log: MatchLog, version: str = "v0") -> dict[str, Any]:
    """Compute both scores for every team, from the log and nothing else.

    ``version`` selects the cooperation metric: ``"v0"`` (default) is the
    original cadence heuristic, kept bit-identical for existing logs; ``"v1"``
    (task t1) scores coordination *quality*. Outcome scoring is version-free.
    """
    if version not in _COOPERATION_VERSIONS:
        raise ValueError(
            f"unknown cooperation version {version!r}; expected one of {_COOPERATION_VERSIONS}"
        )
    final = log.final_state()
    turns_played = final.turn - log.initial_state.turn

    outcome: dict[str, dict[str, int]] = {}
    totals = outcome_points(final)
    for team in final.teams:
        missions = sum(
            m.reward
            for m in final.missions
            # Membership, not equality: a dead-heat dual award (spec decision
            # c15) pays the full reward into every winning team's row.
            if m.status == "completed" and team.id in m.completed_by
        )
        control = CP_POINTS * sum(1 for c in final.control_points if c.owner == team.id)
        outcome[team.id] = {
            "total": totals[team.id],
            "missions": missions,
            "control": control,
            "resources": team.resources,
        }

    if version == "v1":
        index = _build_action_index(log)
        cooperation = {
            team.id: _cooperation_v1(log, team.id, len(team.agents), index) for team in final.teams
        }
    else:
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


# --------------------------------------------------------------------------- #
# Cooperation v1 — content-aware, still log-derived (plan task t1, spec c7/h2).
#
# v0 rewarded cadence: messaging every turn and declaring any plan banked a
# perfect score, so all three season-0 losers out-cooperated the winner. v1
# keeps the four axes but prices *quality* — a rejected order taxes delegation,
# a message or plan counts only when its content correlates with a subsequent
# observable team action, and referent-free or uncorrelated chatter never
# scores. Every weight and constant is pinned by tests/test_engine_scoring_v1.py
# and none is tuned to season-0 outcomes (honesty h2). No new event kinds, no
# engine changes: v1 reads the same log v0 does.
# --------------------------------------------------------------------------- #

_COOPERATION_VERSIONS = ("v0", "v1")

# Fraction of delegation_spread erased at a 100% rejection rate.
REJECTION_PENALTY = 0.5
# Turns after a message in which a consistent team action still counts as its
# realization; plans get a longer strategic horizon than tactical callouts.
CORRELATION_WINDOW = 2
PLAN_WINDOW = 4

V1_WEIGHTS = {
    "delegation_spread": 0.30,  # roster evenness, minus the rejection tax
    "message_utility": 0.30,  # fraction of messages whose content is realized
    "plan_fidelity": 0.15,  # fraction of plans whose content is realized
    "discipline": 0.25,  # 1 - rejection rate, clamped at zero
}

# The things a callout can name; each maps to an observable team action. Cells
# require both coordinates so a bare number (e.g. a "(10)" reward) is not a cell;
# a short unit ref (``u2``) is not matched inside a full one (``blue-u2``).
_CP_RE = re.compile(r"cp-[a-z0-9]+")
_RN_RE = re.compile(r"rn-[a-z0-9]+")
_MS_RE = re.compile(r"ms-[a-z0-9]+")
_CELL_RE = re.compile(r"\(\s*(\d+)\s*,\s*(\d+)\s*\)")
_UNIT_FULL_RE = re.compile(r"\b([a-z][a-z0-9]*)-u([0-9]+)\b")
_UNIT_SHORT_RE = re.compile(r"(?<![a-z0-9-])u([0-9]+)\b")


class _Act(NamedTuple):
    """One observable team action, folded from the transition log.

    ``kind`` is ``move|gather|deliver|capture|hold|mission``; ``ref`` carries the
    node/cp/mission id where relevant; ``before``/``after`` are set for moves so
    "moves toward a named cell" is decidable from the log alone.
    """

    turn: int
    team_id: str
    kind: str
    unit_id: str | None
    ref: str | None
    before: tuple[int, int] | None
    after: tuple[int, int] | None


@dataclass(frozen=True)
class _ActionIndex:
    """The team-attributed action record a correlation query reads."""

    acts: tuple[_Act, ...]
    cp_pos: dict[str, tuple[int, int]]
    node_pos: dict[str, tuple[int, int]]
    mission_pos: dict[str, tuple[int, int]]
    mission_kind: dict[str, str]


def _build_action_index(log: MatchLog) -> _ActionIndex:
    """Fold the transition log into team-attributed observable actions.

    Unit-only events (move, gather) are attributed via the initial roster;
    delivers/captures/holds/completions already carry ``team_id``. Unit
    positions are tracked in log order so each move knows where it came from.
    """
    unit_team = {u.id: u.team_id for u in log.initial_state.units}
    pos = {u.id: u.pos for u in log.initial_state.units}
    cp_pos = {c.id: c.pos for c in log.initial_state.control_points}
    node_pos = {n.id: n.pos for n in log.initial_state.resource_nodes}
    mission_pos = {m.id: m.pos for m in log.initial_state.missions}
    mission_kind = {m.id: m.kind for m in log.initial_state.missions}

    acts: list[_Act] = []
    for event in log.events:
        data = event.data
        if event.kind == "unit_moved":
            uid = data["unit_id"]
            before = pos.get(uid)
            after = (data["to"][0], data["to"][1])
            acts.append(_Act(event.turn, unit_team.get(uid, ""), "move", uid, None, before, after))
            pos[uid] = after
        elif event.kind == "resource_gathered":
            uid = data["unit_id"]
            team = unit_team.get(uid, "")
            acts.append(_Act(event.turn, team, "gather", uid, data["node_id"], None, None))
        elif event.kind == "resource_delivered":
            acts.append(
                _Act(event.turn, data["team_id"], "deliver", data["unit_id"], None, None, None)
            )
        elif event.kind == "control_point_captured":
            acts.append(
                _Act(event.turn, data["team_id"], "capture", None, data["cp_id"], None, None)
            )
        elif (
            event.kind == "control_point_held" and data.get("team_id") and data.get("turns", 0) > 0
        ):
            acts.append(_Act(event.turn, data["team_id"], "hold", None, data["cp_id"], None, None))
        elif event.kind == "mission_completed":
            acts.append(
                _Act(event.turn, data["team_id"], "mission", None, data["mission_id"], None, None)
            )
    return _ActionIndex(tuple(acts), cp_pos, node_pos, mission_pos, mission_kind)


def _cheb(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _toward(
    target: tuple[int, int], before: tuple[int, int] | None, after: tuple[int, int]
) -> bool:
    """A move is *toward* a cell if it lands on it or shrinks the distance."""
    if after == target:
        return True
    if before is None:
        return False
    return _cheb(after, target) < _cheb(before, target)


def _extract_referents(text: str, team_id: str) -> set[tuple[str, Any]]:
    """Parse ONLY the utterance text into the things it names.

    A short unit ref (``u2``) resolves to the *speaker's* own unit; a full ref
    (``blue-u2``) keeps its team, so a message naming an enemy unit can never be
    "realized" by the speaker's own action.
    """
    lowered = text.lower()
    refs: set[tuple[str, Any]] = set()
    for cp in _CP_RE.findall(lowered):
        refs.add(("cp", cp))
    for rn in _RN_RE.findall(lowered):
        refs.add(("rn", rn))
    for ms in _MS_RE.findall(lowered):
        refs.add(("ms", ms))
    for x, y in _CELL_RE.findall(lowered):
        refs.add(("cell", (int(x), int(y))))
    for who, num in _UNIT_FULL_RE.findall(lowered):
        refs.add(("unit", f"{who}-u{num}"))
    for num in _UNIT_SHORT_RE.findall(lowered):
        refs.add(("unit", f"{team_id}-u{num}"))
    return refs


def _referent_realized(
    index: _ActionIndex, team_id: str, turn: int, window: int, referent: tuple[str, Any]
) -> bool:
    """Did the team take an action consistent with this referent, in-window?"""
    lo, hi = turn, turn + window
    acts = [a for a in index.acts if a.team_id == team_id and lo <= a.turn <= hi]
    kind, value = referent
    if kind == "cell":
        return any(a.kind == "move" and _toward(value, a.before, a.after) for a in acts)
    if kind == "cp":
        if any(a.kind in ("capture", "hold") and a.ref == value for a in acts):
            return True
        pos = index.cp_pos.get(value)
        return pos is not None and any(
            a.kind == "move" and _toward(pos, a.before, a.after) for a in acts
        )
    if kind == "rn":
        if any(a.kind == "gather" and a.ref == value for a in acts):
            return True
        pos = index.node_pos.get(value)
        return pos is not None and any(
            a.kind == "move" and _toward(pos, a.before, a.after) for a in acts
        )
    if kind == "ms":
        if any(a.kind == "mission" and a.ref == value for a in acts):
            return True
        mkind = index.mission_kind.get(value)
        pos = index.mission_pos.get(value)
        if mkind == "deliver" and any(a.kind == "deliver" for a in acts):
            return True
        if mkind == "hold":
            here = {cid for cid, cpos in index.cp_pos.items() if cpos == pos}
            if any(a.kind == "hold" and a.ref in here for a in acts):
                return True
        return pos is not None and any(
            a.kind == "move" and _toward(pos, a.before, a.after) for a in acts
        )
    if kind == "unit":
        return any(a.unit_id == value for a in acts)
    return False  # pragma: no cover - _extract_referents emits no other kinds


def _utterance_useful(index: _ActionIndex, team_id: str, turn: int, text: str, window: int) -> bool:
    """An utterance is useful iff at least one thing it names is realized."""
    referents = _extract_referents(text, team_id)
    return any(_referent_realized(index, team_id, turn, window, ref) for ref in referents)


def _cooperation_v1(
    log: MatchLog, team_id: str, roster_size: int, index: _ActionIndex
) -> dict[str, Any]:
    """v1 cooperation for one team — content-aware, log-derived, inspectable.

    The returned ``components`` expose each sub-score's inputs so every v0→v1
    divergence traces to a named signal (honesty h3).
    """
    declared: dict[int, set[str]] = {}
    declared_count = 0
    rejected_count = 0
    messages: list[tuple[int, str]] = []
    plans: list[tuple[int, str]] = []

    for event in log.events:
        if event.data.get("team_id") != team_id:
            continue
        if event.kind == "action_declared":
            declared_count += 1
            declared.setdefault(event.turn, set()).add(str(event.data.get("unit_id")))
        elif event.kind == "action_rejected":
            rejected_count += 1
        elif event.kind == "message_sent":
            messages.append((event.turn, str(event.data.get("text", ""))))
        elif event.kind == "plan_declared":
            plans.append((event.turn, str(event.data.get("text", ""))))

    acting_turns = sorted(declared)
    if roster_size and acting_turns:
        base_spread = sum(len(declared[t]) / roster_size for t in acting_turns) / len(acting_turns)
    else:
        base_spread = 0.0
    # A rejected order is two failures: the unit's turn was wasted (delegation)
    # and the team broke the rules (discipline). v1 prices both — the rate is
    # the same, the penalties are separately weighted.
    rejection_rate = rejected_count / declared_count if declared_count else 0.0
    penalty = REJECTION_PENALTY * min(1.0, rejection_rate)
    delegation = max(0.0, base_spread - penalty)
    discipline = max(0.0, 1.0 - rejection_rate)

    useful_messages = sum(
        1
        for turn, text in messages
        if _utterance_useful(index, team_id, turn, text, CORRELATION_WINDOW)
    )
    message_utility = useful_messages / len(messages) if messages else 0.0
    useful_plans = sum(
        1 for turn, text in plans if _utterance_useful(index, team_id, turn, text, PLAN_WINDOW)
    )
    plan_fidelity = useful_plans / len(plans) if plans else 0.0

    signals = {
        "delegation_spread": round(delegation, 4),
        "message_utility": round(message_utility, 4),
        "plan_fidelity": round(plan_fidelity, 4),
        "discipline": round(discipline, 4),
    }
    score = round(100 * sum(V1_WEIGHTS[name] * value for name, value in signals.items()))
    components = {
        "delegation_spread": {
            "base_spread": round(base_spread, 4),
            "rejection_rate": round(rejection_rate, 4),
            "penalty": round(penalty, 4),
            "value": signals["delegation_spread"],
        },
        "message_utility": {
            "messages": len(messages),
            "useful": useful_messages,
            "value": signals["message_utility"],
        },
        "plan_fidelity": {
            "plans": len(plans),
            "useful": useful_plans,
            "value": signals["plan_fidelity"],
        },
        "discipline": {
            "declared": declared_count,
            "rejected": rejected_count,
            "value": signals["discipline"],
        },
    }
    return {"score": score, "signals": signals, "components": components, "version": "v1"}
