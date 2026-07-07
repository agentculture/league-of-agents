"""Preset registry tests (plan task t2, spec c11/h10): game modes as data.

A preset maps a name to a scenario, sides, driver kinds and a bot tier —
enough for :func:`league.presets.resolve` to hand back the EXACT dict shape
``league.harness.run_match`` accepts. These tests dry-run every bundled
preset: they build the real harness driver callables for each side (proving
the config is launchable) but never call ``run_match`` itself — no team is
registered, no match is created, nothing touches ``.league/``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from league.engine.scenario import get_scenario, scenario_ids
from league.harness import SESSION_TRANSPORTS, build_driver, driver_kind
from league.presets import (
    _RESIDENT_TRANSPORTS,
    Preset,
    TeamPreset,
    get_preset,
    preset_names,
    registry,
    resolve,
    resolve_preset,
)
from league.store import validate_id

PRESETS_MODULE = Path(__file__).resolve().parent.parent / "league" / "presets.py"

# The determinism ban the engine and the bot lane are held to (module
# docstrings of league/engine/state.py and bots/README.md) — presets carry
# explicit seeds, so nothing in this module should ever need the wall clock
# or a PRNG either.
_BANNED_MODULES = {"random", "time", "datetime", "secrets", "uuid"}


# -- acceptance 1: a pure, stably-ordered, enumerable registry --------------


def test_registry_returns_fresh_equal_tuples_every_call() -> None:
    """Pure function: two calls agree on content and order, but the registry
    is never a single shared mutable object a caller could corrupt."""
    first = registry()
    second = registry()
    assert first == second
    assert [p.name for p in first] == [p.name for p in second]
    assert isinstance(first, tuple)


def test_preset_names_is_stably_ordered_and_has_no_duplicates() -> None:
    names = preset_names()
    assert names == tuple(sorted(set(names), key=names.index))  # already stable
    assert len(names) == len(set(names)), "preset names must be unique"
    assert preset_names() == names, "ordering must be stable across calls"


def test_documented_modes_are_all_represented() -> None:
    """t3's brief lists these exact modes; t2 only has to bundle presets that
    cover them (t3 wires the CLI verb) — solo-vs-bot, team-vs-bot,
    team-vs-team (bot-vs-bot), orchestrator, and both a resident and a
    stateless residency variant."""
    names = preset_names()
    assert any("solo" in n for n in names)
    assert any("team-vs-bot" in n for n in names)
    assert any("team-vs-team" in n for n in names)
    assert any("orchestrator" in n for n in names)
    assert any("resident" in n for n in names)

    # At least one preset must resolve to a "stateless" command driver and
    # at least one to a "resident" driver (league.harness.driver_kind is the
    # authority on what a driver spec's residency actually is).
    kinds = {driver_kind(team["driver"]) for name in names for team in resolve(name)["teams"]}
    assert "stateless" in kinds
    assert "resident" in kinds
    assert "bot" in kinds


def test_get_preset_unknown_name_raises_with_known_names_listed() -> None:
    with pytest.raises(ValueError, match="unknown preset"):
        get_preset("does-not-exist")
    try:
        get_preset("does-not-exist")
    except ValueError as err:
        for name in preset_names():
            assert name in str(err)


# -- acceptance 2: every preset dry-runs to a launchable harness config -----


def _scenario_dict(scenario_id: str) -> dict:
    """The same shape ``league arena show --json`` / ``run_match`` hand a
    driver factory — built straight from the engine scenario object so this
    test never has to shell out through the CLI to get it."""
    scenario = get_scenario(scenario_id)
    return {
        "id": scenario.id,
        "grid": {"width": scenario.grid_width, "height": scenario.grid_height},
        "turn_limit": scenario.turn_limit,
        "capture_hold_turns": scenario.capture_hold_turns,
        "roles": {
            name: {"move": st.move, "carry": st.carry, "vision": st.vision}
            for name, st in scenario.role_stats
        },
    }


REQUIRED_MATCH_KEYS = {"scenario", "mode", "seed", "id"}
REQUIRED_TEAM_KEYS = {"id", "name", "driver", "agents"}
REQUIRED_AGENT_KEYS = {"id", "model", "role"}


@pytest.mark.parametrize("name", preset_names())
def test_every_preset_resolves_to_a_launchable_config(name: str) -> None:
    config = resolve(name)

    # -- top-level shape: exactly what league.harness.run_match consumes --
    assert set(config) <= {"match", "teams", "max_rounds", "fog"}
    assert REQUIRED_MATCH_KEYS <= set(config["match"])
    assert isinstance(config["teams"], list) and config["teams"]

    scenario_id = config["match"]["scenario"]
    assert scenario_id in scenario_ids()
    scenario = get_scenario(scenario_id)
    mode = config["match"]["mode"]
    assert mode in scenario.modes
    assert isinstance(config["match"]["seed"], int) and config["match"]["seed"] >= 0

    required_sides = 2 if mode == "competitive" else 1
    assert len(config["teams"]) == required_sides

    scenario_dict = _scenario_dict(scenario_id)
    seen_team_ids: set[str] = set()
    for team in config["teams"]:
        assert REQUIRED_TEAM_KEYS <= set(team)
        validate_id(team["id"], what="team id")  # never raises for a bundled preset
        assert team["id"] not in seen_team_ids, "team ids must be unique within a match"
        seen_team_ids.add(team["id"])

        roles = sorted(a["role"] for a in team["agents"])
        assert roles == sorted(scenario.unit_roles), "roster roles must match the scenario"
        for agent in team["agents"]:
            assert REQUIRED_AGENT_KEYS <= set(agent)
            validate_id(agent["id"], what="agent id")

        # The driver kind is derivable (never raises) — the fairness-axis
        # metadata run_match records for every team.
        driver_kind(team["driver"])

        # This is the actual "does it resolve to a launchable config"
        # proof: building the driver never executes it (no subprocess is
        # spawned, no session opened, no file written) — see
        # league.harness.build_driver / make_resident_driver, whose session
        # dict starts empty and is only populated inside the returned
        # closure, which this test never calls.
        driver = build_driver(
            team["driver"],
            scenario_dict,
            team["agents"],
            fog=bool(config.get("fog", False)),
            map_read=team.get("map_read", "fog"),
            unit_comms=team.get("unit_comms", True),
        )
        assert callable(driver)

    if "max_rounds" in config:
        assert isinstance(config["max_rounds"], int) and config["max_rounds"] > 0
    if "fog" in config:
        assert isinstance(config["fog"], bool)


def test_dry_run_never_touches_the_store(tmp_path, monkeypatch) -> None:
    """Resolving + building drivers for every preset must never create
    ``.league/`` — proof that no match was started."""
    monkeypatch.chdir(tmp_path)
    for name in preset_names():
        config = resolve(name)
        scenario_dict = _scenario_dict(config["match"]["scenario"])
        for team in config["teams"]:
            build_driver(
                team["driver"],
                scenario_dict,
                team["agents"],
                fog=bool(config.get("fog", False)),
                map_read=team.get("map_read", "fog"),
                unit_comms=team.get("unit_comms", True),
            )
    assert not (tmp_path / ".league").exists()


# -- bot tier: data, validated structurally, not by filesystem existence ---


def test_bot_tier_recorded_for_bot_file_sides() -> None:
    for name in preset_names():
        for team in resolve(name)["teams"]:
            if team["driver"].get("type") == "bot-file":
                preset = get_preset(name)
                tp = next(t for t in preset.teams if t.id == team["id"])
                assert tp.bot_tier == team["driver"]["strategy"]


def test_bot_tier_validates_structurally_not_against_the_filesystem() -> None:
    """House tiers beyond ``rusher`` are plan task t4's job — the registry
    must accept a tier name that has no bots/<name>.py on disk yet, and only
    reject names that fail the id-hygiene rule every other id in this repo
    follows (league.store.validate_id)."""
    future_tier_preset = Preset(
        name="probe-future-tier",
        description="probe only, not part of the bundled registry",
        scenario_id="skirmish-1",
        mode="competitive",
        seed=1,
        teams=(
            TeamPreset(
                id="a",
                name="A",
                driver={"type": "bot-file", "strategy": "veteran-tier-not-shipped-yet"},
                model="bot-file:veteran-tier-not-shipped-yet",
                bot_tier="veteran-tier-not-shipped-yet",
            ),
            TeamPreset(id="b", name="B", driver={"type": "bot"}, model="bot:greedy"),
        ),
    )
    config = resolve_preset(future_tier_preset)  # must not raise: no filesystem check
    assert config["teams"][0]["driver"]["strategy"] == "veteran-tier-not-shipped-yet"

    bad_tier_preset = Preset(
        name="probe-bad-tier",
        description="probe only",
        scenario_id="skirmish-1",
        mode="competitive",
        seed=1,
        teams=(
            TeamPreset(
                id="a",
                name="A",
                driver={"type": "bot-file", "strategy": "../escape"},
                model="bot-file:escape",
                bot_tier="../escape",
            ),
            TeamPreset(id="b", name="B", driver={"type": "bot"}, model="bot:greedy"),
        ),
    )
    with pytest.raises(ValueError):
        resolve_preset(bad_tier_preset)


def test_rusher_is_the_one_strategy_that_exists_today() -> None:
    """Sanity anchor: whichever bundled presets reference a real bot-file
    strategy today must point at a file that actually exists (``rusher`` —
    ``bots/README.md``'s reference strategy); this is a fact about the
    bundled data, not a rule this module enforces for hypothetical tiers."""
    bots_dir = Path(__file__).resolve().parent.parent / "bots"
    real_tiers_used = {
        team["driver"]["strategy"]
        for name in preset_names()
        for team in resolve(name)["teams"]
        if team["driver"].get("type") == "bot-file"
    }
    assert real_tiers_used, "expected at least one bundled bot-file preset"
    for tier in real_tiers_used:
        assert (bots_dir / f"{tier}.py").is_file()


# -- acceptance 3: adding a preset is a data entry, not special-cased code --


def test_resolve_preset_is_generic_over_arbitrary_preset_data() -> None:
    """resolve_preset() must not special-case any bundled preset's name —
    proof: a hand-built Preset never registered anywhere resolves the same
    way a bundled one does."""
    custom = Preset(
        name="a-brand-new-preset-nobody-registered",
        description="",
        scenario_id="skirmish-2",
        mode="cooperative",
        seed=42,
        teams=(TeamPreset(id="solo", name="Solo", driver={"type": "bot"}, model="bot:greedy"),),
    )
    config = resolve_preset(custom)
    assert config["match"]["scenario"] == "skirmish-2"
    assert config["match"]["mode"] == "cooperative"
    assert len(config["teams"]) == 1
    assert config["teams"][0]["agents"][0]["role"] in get_scenario("skirmish-2").unit_roles


# -- structural validation: bad data fails loudly, before anything launches -


def test_resolve_rejects_wrong_team_count_for_mode() -> None:
    bad = Preset(
        name="probe-bad-count",
        description="",
        scenario_id="skirmish-1",
        mode="competitive",
        seed=1,
        teams=(TeamPreset(id="a", name="A", driver={"type": "bot"}, model="bot:greedy"),),
    )
    with pytest.raises(ValueError):
        resolve_preset(bad)


def test_resolve_rejects_unsupported_mode_for_scenario() -> None:
    bad = Preset(
        name="probe-bad-mode",
        description="",
        scenario_id="skirmish-1",
        mode="deathmatch",
        seed=1,
        teams=(
            TeamPreset(id="a", name="A", driver={"type": "bot"}, model="bot:greedy"),
            TeamPreset(id="b", name="B", driver={"type": "bot"}, model="bot:greedy"),
        ),
    )
    with pytest.raises(ValueError):
        resolve_preset(bad)


def test_resolve_rejects_unknown_scenario() -> None:
    bad = Preset(
        name="probe-bad-scenario",
        description="",
        scenario_id="no-such-scenario",
        mode="competitive",
        seed=1,
        teams=(
            TeamPreset(id="a", name="A", driver={"type": "bot"}, model="bot:greedy"),
            TeamPreset(id="b", name="B", driver={"type": "bot"}, model="bot:greedy"),
        ),
    )
    with pytest.raises(ValueError):
        resolve_preset(bad)


def test_resolve_rejects_negative_seed() -> None:
    bad = Preset(
        name="probe-negative-seed",
        description="",
        scenario_id="skirmish-1",
        mode="competitive",
        seed=-1,
        teams=(
            TeamPreset(id="a", name="A", driver={"type": "bot"}, model="bot:greedy"),
            TeamPreset(id="b", name="B", driver={"type": "bot"}, model="bot:greedy"),
        ),
    )
    with pytest.raises(ValueError):
        resolve_preset(bad)


def test_resolve_rejects_duplicate_team_ids() -> None:
    bad = Preset(
        name="probe-dup-ids",
        description="",
        scenario_id="skirmish-1",
        mode="competitive",
        seed=1,
        teams=(
            TeamPreset(id="same", name="A", driver={"type": "bot"}, model="bot:greedy"),
            TeamPreset(id="same", name="B", driver={"type": "bot"}, model="bot:greedy"),
        ),
    )
    with pytest.raises(ValueError):
        resolve_preset(bad)


def test_resolve_rejects_invalid_team_id() -> None:
    bad = Preset(
        name="probe-bad-team-id",
        description="",
        scenario_id="skirmish-1",
        mode="competitive",
        seed=1,
        teams=(
            TeamPreset(id="../escape", name="A", driver={"type": "bot"}, model="bot:greedy"),
            TeamPreset(id="b", name="B", driver={"type": "bot"}, model="bot:greedy"),
        ),
    )
    with pytest.raises(ValueError):
        resolve_preset(bad)


def test_resolve_rejects_command_driver_without_argv() -> None:
    bad = Preset(
        name="probe-no-argv",
        description="",
        scenario_id="skirmish-1",
        mode="competitive",
        seed=1,
        teams=(
            TeamPreset(id="a", name="A", driver={"type": "command"}, model="claude-sonnet-5"),
            TeamPreset(id="b", name="B", driver={"type": "bot"}, model="bot:greedy"),
        ),
    )
    with pytest.raises(ValueError):
        resolve_preset(bad)


def test_resolve_rejects_command_driver_with_solo_and_per_seat() -> None:
    bad = Preset(
        name="probe-solo-and-per-seat",
        description="",
        scenario_id="skirmish-1",
        mode="competitive",
        seed=1,
        teams=(
            TeamPreset(
                id="a",
                name="A",
                driver={
                    "type": "command",
                    "solo": True,
                    "per_seat": True,
                    "argv": ["claude"],
                },
                model="claude-sonnet-5",
            ),
            TeamPreset(id="b", name="B", driver={"type": "bot"}, model="bot:greedy"),
        ),
    )
    with pytest.raises(ValueError):
        resolve_preset(bad)


def test_resolve_rejects_resident_driver_with_unknown_transport() -> None:
    bad = Preset(
        name="probe-bad-transport",
        description="",
        scenario_id="skirmish-1",
        mode="competitive",
        seed=1,
        teams=(
            TeamPreset(
                id="a", name="A", driver={"type": "resident", "transport": "telepathy"}, model="x"
            ),
            TeamPreset(id="b", name="B", driver={"type": "bot"}, model="bot:greedy"),
        ),
    )
    with pytest.raises(ValueError):
        resolve_preset(bad)


def test_resolve_rejects_unknown_driver_type() -> None:
    bad = Preset(
        name="probe-bad-driver-type",
        description="",
        scenario_id="skirmish-1",
        mode="competitive",
        seed=1,
        teams=(
            TeamPreset(id="a", name="A", driver={"type": "telepathy"}, model="x"),
            TeamPreset(id="b", name="B", driver={"type": "bot"}, model="bot:greedy"),
        ),
    )
    with pytest.raises(ValueError):
        resolve_preset(bad)


# -- the resident transport list must never silently drift from harness's --


def test_resident_transports_mirror_the_harness_session_transports() -> None:
    assert set(_RESIDENT_TRANSPORTS) == set(SESSION_TRANSPORTS)


# -- determinism: no randomness, no wall clock (design guidance) -----------


def test_presets_module_imports_no_nondeterministic_stdlib() -> None:
    tree = ast.parse(PRESETS_MODULE.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [(node.module or "").split(".")[0]]
        else:
            continue
        offenders += [n for n in names if n in _BANNED_MODULES]
    assert not offenders, f"banned nondeterministic imports in league/presets.py: {offenders}"


def test_every_preset_seed_is_an_explicit_int() -> None:
    for preset in registry():
        assert isinstance(preset.seed, int)
