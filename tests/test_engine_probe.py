"""Span-of-control probe — tests on SYNTHETIC logs (plan task t7, cycle 6:
"the watchable, vast arena"). Pins the plan's parked risk r2 ("the
span-of-control formula") the same way ``tests/test_engine_scoring_v1.py``
pinned risk r1 for cooperation v1: hand-built match logs, not prose.

Criteria under test:

* how many subagents a mind actually fielded (``span``), orders realized per
  subagent (``realization_rate``), and how command quality degrades as N
  grows (the degradation curve) are all derived from the log alone, with
  every constant named and pinned here;
* ONLY real, harness-recorded evidence counts a seat as active — a synthetic
  log where delegation is merely CLAIMED in message text, with no
  ``seat_latency``/``action_declared``/``action_rejected``/own-voice message
  evidence behind it, scores span 0 and an overall probe score of 0;
* ``seat_latency`` evidence, when present, is authoritative and overrides a
  weaker message-attribution heuristic (the ``solo`` handicap pattern: one
  whole-team driver call narrating three personas is NOT three subagents);
* the real committed season-0 orchestrator log (predates ``seat_latency``)
  still resolves to span 3 through the fallback evidence path.
"""

from __future__ import annotations

import pathlib

from league.engine.events import Event, MatchLog
from league.engine.probe import PROBE_VERSION, PROBE_WEIGHTS, probe_match
from league.engine.state import AgentSlot, MatchState, TeamState, Unit

_SEASON0 = pathlib.Path(__file__).resolve().parent.parent / "docs" / "playtests" / "season-0"
_CYCLE4 = pathlib.Path(__file__).resolve().parent.parent / "docs" / "playtests" / "cycle-4"
_HOUSE_TIERS = pathlib.Path(__file__).resolve().parent.parent / "docs" / "playtests" / "house-tiers"


# --------------------------------------------------------------------------- #
# Synthetic-log builders — mirrors tests/test_engine_scoring_v1.py's style.
# --------------------------------------------------------------------------- #


def _team(tid: str, agent_ids: list[str]) -> TeamState:
    agents = tuple(AgentSlot(id=aid, model="m", role="scout") for aid in agent_ids)
    return TeamState(id=tid, name=tid.title(), resources=0, agents=agents)


def _unit(tid: str, i: int, agent_id: str, pos: tuple[int, int] = (0, 0)) -> Unit:
    return Unit(id=f"{tid}-u{i}", team_id=tid, agent_id=agent_id, role="scout", pos=pos)


def _state(*, teams: tuple[TeamState, ...], units: tuple[Unit, ...]) -> MatchState:
    return MatchState(
        match_id="m-probe",
        scenario_id="skirmish-1",
        seed=0,
        mode="competitive",
        turn=1,
        turn_limit=30,
        grid_width=12,
        grid_height=10,
        status="active",
        winner=None,
        teams=teams,
        units=units,
        control_points=(),
        missions=(),
        resource_nodes=(),
    )


def _log(initial: MatchState, triples: list[tuple[int, str, dict]]) -> MatchLog:
    events = tuple(
        Event(turn=turn, seq=i, kind=kind, data=data)
        for i, (turn, kind, data) in enumerate(triples)
    )
    return MatchLog(initial_state=initial, events=events)


def _declare(team: str, turn: int, unit: str) -> tuple[int, str, dict]:
    return (turn, "action_declared", {"team_id": team, "unit_id": unit, "action": "move"})


def _reject(team: str, turn: int, unit: str) -> tuple[int, str, dict]:
    return (turn, "action_rejected", {"team_id": team, "unit_id": unit, "reason": "illegal"})


def _passive_reject(team: str, turn: int, unit: str) -> tuple[int, str, dict]:
    """A capture-incapable unit's incidental occupancy rejection (issue #31,
    ``league.engine.tick`` section 7) — fires from mere standing, never from a
    declared-order mistake, marked ``passive`` so probe/``match show`` can
    tell it apart from a genuine rejection."""
    return (
        turn,
        "action_rejected",
        {
            "team_id": team,
            "unit_id": unit,
            "reason": "this role cannot capture control points",
            "passive": True,
        },
    )


def _msg(team: str, turn: int, frm: str, text: str) -> tuple[int, str, dict]:
    return (turn, "message_sent", {"team_id": team, "from": frm, "text": text})


def _move(unit: str, turn: int, to: tuple[int, int]) -> tuple[int, str, dict]:
    return (turn, "unit_moved", {"unit_id": unit, "to": list(to)})


def _latency(
    team: str, turn: int, agent_id: str | None, unit_id: str | None, elapsed_ms: int = 10
) -> tuple[int, str, dict]:
    return (
        turn,
        "seat_latency",
        {"team_id": team, "agent_id": agent_id, "unit_id": unit_id, "elapsed_ms": elapsed_ms},
    )


# --------------------------------------------------------------------------- #
# 1. Named constants — pinned, not prose (risk r2 resolved here).
# --------------------------------------------------------------------------- #


def test_probe_version_is_pinned() -> None:
    assert PROBE_VERSION == "p0"


def test_probe_weights_are_named_and_sum_to_one() -> None:
    assert set(PROBE_WEIGHTS) == {"span_coverage", "realization_rate", "guidance_linkage"}
    assert abs(sum(PROBE_WEIGHTS.values()) - 1.0) < 1e-9
    assert PROBE_WEIGHTS == {
        "span_coverage": 0.25,
        "realization_rate": 0.45,
        "guidance_linkage": 0.30,
    }


# --------------------------------------------------------------------------- #
# 2. Claimed delegation WITHOUT log evidence scores zero (acceptance #2).
# --------------------------------------------------------------------------- #


def test_claimed_delegation_without_any_evidence_scores_zero() -> None:
    """A "master" narrates commanding two subagents by name; neither ever
    declares an action, is rejected, or speaks in its own voice, and the team
    has NO seat_latency events at all. Nothing behind the claim -> span 0,
    every signal 0, overall probe score 0."""
    initial = _state(
        teams=(_team("ghost", ["ghost-1", "ghost-2"]),),
        units=(_unit("ghost", 1, "ghost-1"), _unit("ghost", 2, "ghost-2")),
    )
    triples = [
        _msg(
            "ghost",
            1,
            "ghost-master",
            "I've assigned ghost-1 to the west flank and ghost-2 to the east flank.",
        ),
        (1, "turn_advanced", {"turn": 1}),
    ]
    report = probe_match(_log(initial, triples))
    team = report["teams"]["ghost"]
    assert team["span"] == 0
    assert team["signals"] == {
        "span_coverage": 0.0,
        "realization_rate": 0.0,
        "guidance_linkage": 0.0,
    }
    assert team["score"] == 0


def test_partial_claim_only_counts_the_seat_with_real_evidence() -> None:
    """ "leader" really acts and speaks; "shadow" is only ever named in
    leader's message, never speaks itself, never declares an action -> span 1,
    not 2."""
    initial = _state(
        teams=(_team("crew", ["leader", "shadow"]),),
        units=(_unit("crew", 1, "leader"), _unit("crew", 2, "shadow")),
    )
    triples = [
        _msg("crew", 1, "leader", "I've got west; shadow, you take east."),
        _declare("crew", 1, "crew-u1"),
        (1, "turn_advanced", {"turn": 1}),
    ]
    report = probe_match(_log(initial, triples))
    team = report["teams"]["crew"]
    assert team["span"] == 1
    assert "leader" in team["components"]["realization_rate"]["per_seat"]
    assert "shadow" not in team["components"]["realization_rate"]["per_seat"]


# --------------------------------------------------------------------------- #
# 3. seat_latency, when present, is authoritative over message attribution.
# --------------------------------------------------------------------------- #


def test_seat_latency_overrides_message_only_attribution() -> None:
    """The "solo handicap" shape: ONE whole-team driver call narrates three
    named personas in messages, but every seat_latency entry is
    agent_id=None/unit_id=None -> span stays 0, never 3."""
    initial = _state(
        teams=(_team("solo", ["solo-1", "solo-2", "solo-3"]),),
        units=(
            _unit("solo", 1, "solo-1"),
            _unit("solo", 2, "solo-2"),
            _unit("solo", 3, "solo-3"),
        ),
    )
    triples = [
        _msg("solo", 1, "solo-1", "holding position"),
        _msg("solo", 1, "solo-2", "heading to the node"),
        _msg("solo", 1, "solo-3", "screening the point"),
        _declare("solo", 1, "solo-u1"),
        _declare("solo", 1, "solo-u2"),
        _declare("solo", 1, "solo-u3"),
        _latency("solo", 1, None, None, elapsed_ms=5000),
        (1, "turn_advanced", {"turn": 1}),
    ]
    report = probe_match(_log(initial, triples))
    team = report["teams"]["solo"]
    assert team["evidence"] == "latency"
    assert team["span"] == 0


def test_seat_latency_with_unit_id_proves_real_per_seat_calls() -> None:
    """Three seats, each with its OWN seat_latency (agent_id+unit_id both
    set) every turn -> span 3, real per-seat evidence, no message needed."""
    initial = _state(
        teams=(_team("crew", ["crew-1", "crew-2", "crew-3"]),),
        units=(
            _unit("crew", 1, "crew-1"),
            _unit("crew", 2, "crew-2"),
            _unit("crew", 3, "crew-3"),
        ),
    )
    triples = [
        _latency("crew", 1, "crew-1", "crew-u1"),
        _latency("crew", 1, "crew-2", "crew-u2"),
        _latency("crew", 1, "crew-3", "crew-u3"),
        _declare("crew", 1, "crew-u1"),
        _declare("crew", 1, "crew-u2"),
        _declare("crew", 1, "crew-u3"),
        (1, "turn_advanced", {"turn": 1}),
    ]
    report = probe_match(_log(initial, triples))
    team = report["teams"]["crew"]
    assert team["evidence"] == "latency"
    assert team["span"] == 3
    assert team["signals"]["realization_rate"] == 1.0


def test_orchestrator_master_seat_latency_identifies_a_commander_not_a_seat() -> None:
    """A ``unit_id=None`` seat_latency entry (agent_id set) is the
    orchestrator-mode-for-real master's own per-turn call: a commander, never
    counted toward span."""
    initial = _state(
        teams=(_team("wing", ["wing-master", "wing-1"]),),
        units=(_unit("wing", 1, "wing-1", pos=(0, 0)),),
    )
    triples = [
        _latency("wing", 1, "wing-master", None),
        _latency("wing", 1, "wing-1", "wing-u1"),
        _msg("wing", 1, "wing-master", "push toward (9, 9)"),
        _msg("wing", 1, "wing-master", "good luck out there"),
        _move("wing-u1", 1, (9, 9)),
        _declare("wing", 1, "wing-u1"),
        (1, "turn_advanced", {"turn": 1}),
    ]
    report = probe_match(_log(initial, triples))
    team = report["teams"]["wing"]
    assert team["span"] == 1
    assert team["commanders"] == ["wing-master"]
    guidance = team["components"]["guidance_linkage"]
    assert guidance == {"messages": 2, "useful": 1, "value": 0.5}


# --------------------------------------------------------------------------- #
# 4. Realization per seat + the within-match degradation curve.
# --------------------------------------------------------------------------- #


def test_per_seat_realization_and_degradation_curve_show_command_quality() -> None:
    """grid-1/grid-2 are commanded cleanly; grid-3's only order is rejected —
    "commands 2 well, 1 badly" is visible in per_seat AND in the
    concurrent-span-bucketed degradation curve."""
    initial = _state(
        teams=(_team("grid", ["grid-1", "grid-2", "grid-3"]),),
        units=(
            _unit("grid", 1, "grid-1"),
            _unit("grid", 2, "grid-2"),
            _unit("grid", 3, "grid-3"),
        ),
    )
    triples = [
        _latency("grid", 1, "grid-1", "grid-u1"),
        _declare("grid", 1, "grid-u1"),
        _latency("grid", 2, "grid-1", "grid-u1"),
        _latency("grid", 2, "grid-2", "grid-u2"),
        _declare("grid", 2, "grid-u1"),
        _declare("grid", 2, "grid-u2"),
        _latency("grid", 3, "grid-1", "grid-u1"),
        _latency("grid", 3, "grid-2", "grid-u2"),
        _latency("grid", 3, "grid-3", "grid-u3"),
        _declare("grid", 3, "grid-u1"),
        _declare("grid", 3, "grid-u2"),
        _declare("grid", 3, "grid-u3"),
        _reject("grid", 3, "grid-u3"),
        (3, "turn_advanced", {"turn": 3}),
    ]
    report = probe_match(_log(initial, triples))
    team = report["teams"]["grid"]
    assert team["span"] == 3
    per_seat = team["components"]["realization_rate"]["per_seat"]
    assert per_seat["grid-1"]["realization_rate"] == 1.0
    assert per_seat["grid-2"]["realization_rate"] == 1.0
    assert per_seat["grid-3"]["realization_rate"] == 0.0
    assert team["signals"]["realization_rate"] == round((1.0 + 1.0 + 0.0) / 3, 4)
    curve = team["components"]["degradation_curve"]
    assert curve == {"1": 1.0, "2": 1.0, "3": round(2 / 3, 4)}


# --------------------------------------------------------------------------- #
# 4b. Passive capture-ineligibility never penalizes realization_rate (#31).
# --------------------------------------------------------------------------- #


def test_passive_capture_ineligibility_does_not_penalize_realization_rate() -> None:
    """A scout parked on a contested/owned point declares a clean 'hold' every
    turn (never rejected on its own terms) but the engine also fires a
    PASSIVE action_rejected each turn purely from occupancy — playtest: this
    used to drag realization_rate to 0.42 despite zero genuine mistakes. The
    passive events must not count toward the seat's rejected tally."""
    initial = _state(
        teams=(_team("blue", ["blue-scout"]),),
        units=(_unit("blue", 1, "blue-scout"),),
    )
    triples = [
        _latency("blue", 1, "blue-scout", "blue-u1"),
        _declare("blue", 1, "blue-u1"),
        _passive_reject("blue", 1, "blue-u1"),
        _latency("blue", 2, "blue-scout", "blue-u1"),
        _declare("blue", 2, "blue-u1"),
        _passive_reject("blue", 2, "blue-u1"),
        _latency("blue", 3, "blue-scout", "blue-u1"),
        _declare("blue", 3, "blue-u1"),
        _passive_reject("blue", 3, "blue-u1"),
        (3, "turn_advanced", {"turn": 3}),
    ]
    report = probe_match(_log(initial, triples))
    team = report["teams"]["blue"]
    per_seat = team["components"]["realization_rate"]["per_seat"]
    assert per_seat["blue-scout"] == {"declared": 3, "rejected": 0, "realization_rate": 1.0}
    assert team["signals"]["realization_rate"] == 1.0
    # The degradation curve is clean too — no phantom rejection inflates any
    # concurrent-span bucket.
    assert team["components"]["degradation_curve"] == {"1": 1.0}


def test_a_genuine_illegal_order_still_counts_alongside_passive_rejections() -> None:
    """Same shape as above, but turn 2's declared order is ALSO genuinely
    illegal (e.g. an out-of-range move) — that one must still penalize
    realization_rate even while the passive rejections around it don't."""
    initial = _state(
        teams=(_team("blue", ["blue-scout"]),),
        units=(_unit("blue", 1, "blue-scout"),),
    )
    triples = [
        _latency("blue", 1, "blue-scout", "blue-u1"),
        _declare("blue", 1, "blue-u1"),
        _passive_reject("blue", 1, "blue-u1"),
        _latency("blue", 2, "blue-scout", "blue-u1"),
        _declare("blue", 2, "blue-u1"),
        _reject("blue", 2, "blue-u1"),  # a genuine mistake, not passive
        _passive_reject("blue", 2, "blue-u1"),
        _latency("blue", 3, "blue-scout", "blue-u1"),
        _declare("blue", 3, "blue-u1"),
        _passive_reject("blue", 3, "blue-u1"),
        (3, "turn_advanced", {"turn": 3}),
    ]
    report = probe_match(_log(initial, triples))
    team = report["teams"]["blue"]
    per_seat = team["components"]["realization_rate"]["per_seat"]
    assert per_seat["blue-scout"] == {
        "declared": 3,
        "rejected": 1,
        "realization_rate": round(1 - 1 / 3, 4),
    }
    assert team["signals"]["realization_rate"] == round(1 - 1 / 3, 4)


# --------------------------------------------------------------------------- #
# 5. Integration: the real committed season-0 orchestrator log (no
#    seat_latency at all — predates plan C4-t1) and a real seat_latency-
#    evidenced solo/bot log.
# --------------------------------------------------------------------------- #


def test_probe_finds_three_real_subagents_in_the_season0_orchestrator_log() -> None:
    log = MatchLog.from_jsonl((_SEASON0 / "orchestrator.log.jsonl").read_text())
    report = probe_match(log)
    fable = report["teams"]["fable"]
    assert fable["evidence"] == "fallback"
    assert fable["span"] == 3
    assert set(fable["components"]["realization_rate"]["per_seat"]) == {
        "fable-scout",
        "fable-harvester",
        "fable-defender",
    }
    assert 0.0 < fable["signals"]["realization_rate"] <= 1.0
    assert fable["score"] > 0
    # The greedy bot opponent is not a per-seat mind; the fallback path is
    # conservative (0 or 1), never mistaken for real delegation.
    assert report["teams"]["baseline"]["span"] in (0, 1)


def test_probe_on_solo_vs_bot_log_is_not_per_seat() -> None:
    """seat_latency exists here (post plan C4-t1) and is unambiguous: every
    entry is agent_id=None -> both teams are single whole-team calls, span
    0/1 despite the solo team's per-persona messages."""
    log = MatchLog.from_jsonl((_CYCLE4 / "solo-vs-bot.log.jsonl").read_text())
    report = probe_match(log)
    for team_id in ("solo", "house"):
        team = report["teams"][team_id]
        assert team["evidence"] == "latency"
        assert team["span"] in (0, 1)


def test_probe_on_bot_vs_bot_log_with_no_messages_or_latency_is_all_zero() -> None:
    log = MatchLog.from_jsonl((_HOUSE_TIERS / "gold-vs-silver-seed101.log.jsonl").read_text())
    report = probe_match(log)
    for team_id in ("blue", "red"):
        team = report["teams"][team_id]
        assert team["span"] == 0
        assert team["score"] == 0


def test_probe_payload_shape_matches_scoring_style() -> None:
    """Mirrors league.engine.scoring's per-team payload: score/signals/
    components/version."""
    log = MatchLog.from_jsonl((_SEASON0 / "orchestrator.log.jsonl").read_text())
    report = probe_match(log)
    assert report["version"] == "p0"
    assert report["match_id"] == "m-season0-orchestrator"
    for team in report["teams"].values():
        assert {
            "span",
            "roster_size",
            "evidence",
            "commanders",
            "score",
            "signals",
            "version",
        } <= set(team)
        assert team["version"] == "p0"
        assert set(team["signals"]) == {"span_coverage", "realization_rate", "guidance_linkage"}
