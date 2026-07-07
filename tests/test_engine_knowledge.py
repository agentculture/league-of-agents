"""Acceptance tests for the per-team knowledge fold (cycle-3 plan task t3, spec c13/h4/h13).

Criteria under test:

* **knowledge is a fold over events** — re-folding the same log (including a
  JSONL round trip) reproduces per-team knowledge exactly, and folding never
  mutates the log or any state (the package-wide AST import ban in
  ``test_engine_state.py`` covers ``league/engine/knowledge.py`` automatically);
* **an out-of-vision fact enters a team's knowledge ONLY via a logged message
  or its own units' sighting** — a state where team A cannot see an entity
  keeps it absent from A's knowledge; a ``message_sent`` event naming it makes
  it appear flagged ``told`` (told-not-seen); a later sighting upgrades it to
  ``seen`` with dynamic attributes;
* the fold is **derived-only**: computing it changes no state, no hash, no log
  bytes — it is a read-side projection like scoring.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from league.engine.events import MatchLog, fold_events
from league.engine.knowledge import (
    SOURCE_SEEN,
    SOURCE_TOLD,
    KnowledgeFrame,
    KnownNode,
    fold_knowledge,
    initial_knowledge,
    knowledge_by_turn,
    latest_knowledge,
)
from league.engine.scenario import get_scenario, instantiate
from league.engine.state import AgentSlot, state_hash, state_to_json
from league.engine.tick import resolve_turn, start_match
from league.replay import build_replay_data


def _roster(team: str, model: str = "colleague/qwen") -> tuple[AgentSlot, ...]:
    return (
        AgentSlot(id=f"{team}-scout", model=model, role="scout"),
        AgentSlot(id=f"{team}-harvester", model=model, role="harvester"),
        AgentSlot(id=f"{team}-defender", model=model, role="defender"),
    )


def _competitive_state():
    scenario = get_scenario("skirmish-1")
    state = instantiate(
        scenario,
        match_id="m-knowledge",
        seed=11,
        mode="competitive",
        teams=(
            ("blue", "Blue Foundry", _roster("blue")),
            ("red", "Red Relay", _roster("red", model="claude-sonnet-5")),
        ),
    )
    return scenario, state


def _move_unit(state, unit_id: str, pos: tuple[int, int]):
    units = tuple(dataclasses.replace(u, pos=pos) if u.id == unit_id else u for u in state.units)
    return dataclasses.replace(state, units=units)


def _play(initial, scenario, turns) -> MatchLog:
    """Run scripted orders through the real tick and return the whole log."""
    state, events = start_match(initial)
    all_events = list(events)
    for orders in turns:
        state, events = resolve_turn(state, scenario, orders, seq_start=len(all_events))
        all_events.extend(events)
    return MatchLog(initial_state=initial, events=tuple(all_events))


def _known_ids(frame: KnowledgeFrame) -> dict[str, set[str]]:
    return {
        "units": {f.id for f in frame.units},
        "nodes": {f.id for f in frame.resource_nodes},
        "cps": {f.id for f in frame.control_points},
    }


def _fact(facts, fact_id: str):
    return next(f for f in facts if f.id == fact_id)


def _scripted_log() -> tuple[MatchLog, object]:
    """A short match exercising moves, messages naming entities, and a gather."""
    scenario, initial = _competitive_state()
    turns = [
        {
            "blue": {
                "plan": "sweep west, relay via the node",
                "messages": [{"from": "blue-scout", "text": "flank via rn-west now"}],
                "actions": [
                    {"unit_id": "blue-u1", "action": "move", "to": [0, 3]},
                    {"unit_id": "blue-u2", "action": "move", "to": [1, 2]},
                ],
            },
            "red": {
                "messages": [{"from": "red-defender", "text": "guard the rn-east approach"}],
                "actions": [{"unit_id": "red-u1", "action": "move", "to": [9, 8]}],
            },
        },
        {
            "blue": {
                "messages": [{"from": "blue-scout", "text": "watch for red-u1 out east"}],
                "actions": [{"unit_id": "blue-u1", "action": "move", "to": [0, 5]}],
            },
            "red": {"actions": [{"unit_id": "red-u1", "action": "move", "to": [9, 5]}]},
        },
        {
            "blue": {"actions": [{"unit_id": "blue-u1", "action": "gather"}]},
            "red": {"actions": [{"unit_id": "red-u1", "action": "move", "to": [9, 2]}]},
        },
    ]
    return _play(initial, scenario, turns), scenario


# --- acceptance 1: knowledge is a fold — re-folding reproduces it exactly --


def test_refolding_the_same_log_reproduces_knowledge_exactly() -> None:
    log, scenario = _scripted_log()
    first = knowledge_by_turn(log, scenario)
    second = knowledge_by_turn(log, scenario)
    assert first == second
    # A JSONL round trip is the same log — and the same knowledge.
    reloaded = MatchLog.from_jsonl(log.to_jsonl())
    assert knowledge_by_turn(reloaded, scenario) == first


def test_folding_knowledge_mutates_nothing_and_touches_no_hash() -> None:
    log, scenario = _scripted_log()
    jsonl_before = log.to_jsonl()
    final_hash_before = state_hash(log.final_state())
    initial_json_before = state_to_json(log.initial_state)
    knowledge_by_turn(log, scenario)
    assert log.to_jsonl() == jsonl_before, "the fold must never touch the log"
    assert state_hash(log.final_state()) == final_hash_before
    assert state_to_json(log.initial_state) == initial_json_before


def test_incremental_fold_agrees_with_the_batch_entry_point() -> None:
    """fold_knowledge turn by turn (the live-harness path) equals knowledge_by_turn."""
    log, scenario = _scripted_log()
    batch = knowledge_by_turn(log, scenario)

    grouped: dict[int, list] = {}
    for event in log.events:
        grouped.setdefault(event.turn, []).append(event)
    state = log.initial_state
    for team in log.initial_state.teams:
        frames = [initial_knowledge(log.initial_state, scenario, team.id)]
        folded_state = state
        for turn in sorted(grouped):
            folded_state = fold_events(folded_state, tuple(grouped[turn]))
            frames.append(fold_knowledge(frames[-1], tuple(grouped[turn]), folded_state, scenario))
        assert tuple(frames) == batch[team.id]


def test_frames_align_one_to_one_with_replay_frames() -> None:
    """The overlay contract: one knowledge frame per replay frame, same order."""
    log, scenario = _scripted_log()
    replay_frames = build_replay_data(log)["frames"]
    for frames in knowledge_by_turn(log, scenario).values():
        assert len(frames) == len(replay_frames)


def test_latest_knowledge_is_the_last_frame() -> None:
    log, scenario = _scripted_log()
    frames = knowledge_by_turn(log, scenario)
    latest = latest_knowledge(log, scenario)
    assert set(latest) == set(frames)
    for team_id, frame in latest.items():
        assert frame == frames[team_id][-1]


# --- acceptance 2: out-of-vision facts arrive ONLY by message or sighting ---


def test_out_of_vision_fact_absent_until_a_message_names_it() -> None:
    scenario, initial = _competitive_state()
    # Quiet opening: nobody moves, nobody talks. Nothing on skirmish-1 is
    # inside either spawn's vision (proven in test_engine_vision).
    quiet = _play(initial, scenario, [{}])
    for team_id in ("blue", "red"):
        frame = latest_knowledge(quiet, scenario)[team_id]
        known = _known_ids(frame)
        assert known["nodes"] == set(), f"{team_id} has seen and been told nothing"
        assert known["cps"] == set()
        assert known["units"] == {f"{team_id}-u1", f"{team_id}-u2", f"{team_id}-u3"}

    # Same match, plus one blue message naming the far-side node.
    told = _play(
        initial,
        scenario,
        [{}, {"blue": {"messages": [{"from": "blue-scout", "text": "regroup at rn-east"}]}}],
    )
    blue = latest_knowledge(told, scenario)["blue"]
    fact = _fact(blue.resource_nodes, "rn-east")
    assert fact.source == SOURCE_TOLD, "told-not-seen must be flagged as told"
    assert fact.turn == 2
    assert fact.pos == (11, 4), "furniture position is static scenario identity"
    assert fact.remaining is None, "a mention never reveals dynamic board state"
    # The message was blue's — red learns nothing from it.
    assert _known_ids(latest_knowledge(told, scenario)["red"])["nodes"] == set()


def test_a_sighting_upgrades_a_told_fact_and_reveals_dynamics() -> None:
    scenario, initial = _competitive_state()
    log = _play(
        initial,
        scenario,
        [
            {"blue": {"messages": [{"from": "blue-scout", "text": "flank via rn-west"}]}},
            {"blue": {"actions": [{"unit_id": "blue-u1", "action": "move", "to": [0, 3]}]}},
        ],
    )
    frames = knowledge_by_turn(log, scenario)["blue"]
    told = _fact(frames[-2].resource_nodes, "rn-west")
    assert told.source == SOURCE_TOLD and told.remaining is None
    # Post-turn-2 the scout at (0,3) sees rn-west at (0,5): told upgrades to seen.
    seen = _fact(frames[-1].resource_nodes, "rn-west")
    assert seen.source == SOURCE_SEEN
    assert seen.turn == 2
    assert seen.remaining == 12, "a sighting reveals the dynamic attribute"
    assert (0, 5) in frames[-1].cells_seen


def test_a_told_enemy_unit_carries_identity_but_no_position() -> None:
    scenario, initial = _competitive_state()
    log = _play(
        initial,
        scenario,
        [{"blue": {"messages": [{"from": "blue-scout", "text": "red-u1 is their scout"}]}}],
    )
    blue = latest_knowledge(log, scenario)["blue"]
    fact = _fact(blue.units, "red-u1")
    assert fact.source == SOURCE_TOLD
    assert fact.team_id == "red" and fact.role == "scout"
    assert fact.pos is None, "a bare mention must never leak a live position"
    assert fact.alive is None


def test_last_seen_facts_persist_after_the_entity_leaves_vision() -> None:
    scenario, initial = _competitive_state()
    # Stage the red scout inside blue's spawn vision, then march it away.
    staged = _move_unit(initial, "red-u1", (2, 2))
    log = _play(
        staged,
        scenario,
        [{"red": {"actions": [{"unit_id": "red-u1", "action": "move", "to": [4, 3]}]}}],
    )
    frames = knowledge_by_turn(log, scenario)["blue"]
    opening = _fact(frames[0].units, "red-u1")
    assert opening.source == SOURCE_SEEN and opening.pos == (2, 2)
    # (4,3) is outside every blue unit's radius: the stale sighting is retained.
    stale = _fact(frames[-1].units, "red-u1")
    assert stale.source == SOURCE_SEEN
    assert stale.pos == (2, 2), "knowledge keeps the last-seen position, not the truth"
    assert stale.turn == 0, "the fact still carries the turn it was actually seen"


def test_a_message_never_downgrades_a_seen_fact() -> None:
    scenario, initial = _competitive_state()
    staged = _move_unit(initial, "red-u1", (2, 2))
    log = _play(
        staged,
        scenario,
        [
            {
                "blue": {"messages": [{"from": "blue-scout", "text": "red-u1 spotted earlier"}]},
                "red": {"actions": [{"unit_id": "red-u1", "action": "move", "to": [4, 3]}]},
            }
        ],
    )
    fact = _fact(latest_knowledge(log, scenario)["blue"].units, "red-u1")
    assert fact.source == SOURCE_SEEN, "a mention adds nothing a sighting already gave"
    assert fact.pos == (2, 2) and fact.turn == 0


def test_told_parsing_is_conservative_exact_id_tokens_only() -> None:
    scenario, initial = _competitive_state()
    log = _play(
        initial,
        scenario,
        [
            {
                "blue": {
                    "messages": [
                        {"from": "blue-scout", "text": "head west to the western node"},
                        {"from": "blue-scout", "text": "rn-westish is a trap, avoid it"},
                        {"from": "blue-scout", "text": "the xrn-west route is mined"},
                    ]
                }
            }
        ],
    )
    known = _known_ids(latest_knowledge(log, scenario)["blue"])
    assert known["nodes"] == set(), "prose and near-miss tokens must not become knowledge"
    assert known["cps"] == set()


def test_told_control_points_and_re_mentions_of_seen_nodes() -> None:
    """The seen-beats-told guard holds for furniture too, and told CPs hide owners."""
    scenario, initial = _competitive_state()
    log = _play(
        initial,
        scenario,
        [
            # Turn 1: the scout walks into sight of rn-west.
            {"blue": {"actions": [{"unit_id": "blue-u1", "action": "move", "to": [0, 3]}]}},
            # Turn 2: the scout walks back out of sight while a message names
            # the now-unseen node and a never-seen control point.
            {
                "blue": {
                    "messages": [
                        {"from": "blue-scout", "text": "hold near rn-west, push to cp-east"}
                    ],
                    "actions": [{"unit_id": "blue-u1", "action": "move", "to": [1, 1]}],
                }
            },
        ],
    )
    blue = latest_knowledge(log, scenario)["blue"]
    node = _fact(blue.resource_nodes, "rn-west")
    assert node.source == SOURCE_SEEN, "re-mentioning a seen node must not downgrade it"
    assert node.turn == 1, "the fact keeps the turn of the actual sighting"
    assert node.remaining == 12, "the witnessed dynamic attribute survives the mention"
    cp = _fact(blue.control_points, "cp-east")
    assert cp.source == SOURCE_TOLD
    assert cp.pos == (9, 2), "a control point's static position is scenario identity"
    assert cp.owner is None, "told-only means the owner is unknown, not unowned"
    assert cp.to_dict()["source"] == SOURCE_TOLD

    # And the same guard for a control point the team has already SEEN: stage
    # the scout next to cp-east, walk it away, then name the point.
    staged = _move_unit(initial, "blue-u1", (7, 3))
    log = _play(
        staged,
        scenario,
        [
            {
                "blue": {
                    "messages": [{"from": "blue-scout", "text": "fall back, cp-east is hot"}],
                    "actions": [{"unit_id": "blue-u1", "action": "move", "to": [4, 3]}],
                }
            }
        ],
    )
    seen_cp = _fact(latest_knowledge(log, scenario)["blue"].control_points, "cp-east")
    assert seen_cp.source == SOURCE_SEEN, "re-mentioning a seen point must not downgrade it"
    assert seen_cp.turn == 0, "the fact keeps the turn of the actual sighting"


def test_an_unknown_source_is_a_loud_error() -> None:
    with pytest.raises(ValueError, match="unknown knowledge source"):
        KnownNode(id="rn-x", pos=(0, 0), remaining=None, turn=0, source="guessed")


def test_own_units_are_always_known_and_cells_seen_accumulates() -> None:
    scenario, initial = _competitive_state()
    log = _play(
        initial,
        scenario,
        [{"blue": {"actions": [{"unit_id": "blue-u1", "action": "move", "to": [3, 0]}]}}],
    )
    frames = knowledge_by_turn(log, scenario)["blue"]
    for frame in frames:
        own = {f.id for f in frame.units if f.team_id == "blue"}
        assert own == {"blue-u1", "blue-u2", "blue-u3"}
        assert all(f.source == SOURCE_SEEN for f in frame.units if f.team_id == "blue")
    for earlier, later in zip(frames, frames[1:]):
        assert earlier.cells_seen <= later.cells_seen, "cells_seen only ever grows"
    assert frames[0].cells_seen < frames[-1].cells_seen, "the move revealed new ground"


def test_frames_serialize_to_canonical_json() -> None:
    log, scenario = _scripted_log()
    frame = latest_knowledge(log, scenario)["blue"]
    payload = frame.to_dict()
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert json.loads(encoded) == payload, "to_dict must be plain JSON types"
    assert payload["cells_seen"] == sorted(payload["cells_seen"])
    assert payload["team_id"] == "blue" and payload["turn"] == frame.turn
