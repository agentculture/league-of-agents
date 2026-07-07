"""Preset registry — game modes as data, not code (plan task t2, spec c11/h10).

The next increment ("league of agents goes single-player") wants any agent —
alone, with spawned subagents, or as a team — to face the house strategy bots
from one CLI command per mode (plan task t3, ``league play <preset>``). This
module is the DATA half of that story: a bundled registry mapping a preset
NAME to a scenario, its sides, each side's driver kind, and (for a bot side) a
bot tier — resolved into the EXACT dict shape :func:`league.harness.run_match`
accepts. Adding a new mode is a data entry here (plus, later, an explain-
catalog entry — plan task t3, not this module's job), never a code change:
:func:`resolve_preset` is generic over any :class:`Preset`, bundled or not.

Two invariants this module holds itself to, mirroring the engine's own rules
(``league/engine/state.py``'s import ban, ``bots/README.md``'s strategy
contract):

* **Deterministic.** No ``random``/``time``/``datetime``/``secrets``/``uuid``
  import, anywhere in this file — every preset's seed is an explicit,
  literal field, never generated.
* **Data-only bot tiers.** A bot side may declare a ``bot_tier`` that names a
  ``bots/<name>.py`` strategy the house-bot roster (plan task t4) hasn't
  shipped yet. :func:`resolve_preset` validates a tier for ID HYGIENE only
  (:func:`league.store.validate_id`'s letters/digits/``.``/``_``/``-`` rule)
  — never against what's actually on disk — so this registry never has to
  change shape when t4 lands new tiers. Only ``bots/rusher.py`` exists today
  (``bots/README.md``'s reference strategy); the bundled presets that need a
  REAL bot-file opponent point at it by name.

This module never imports :mod:`league.harness` or :mod:`league.cli` — it
only depends on :mod:`league.engine.scenario` (to validate a scenario id and
its role roster) and :mod:`league.store` (``validate_id``, the same
path-traversal hygiene every other id in this repo is held to). Proving a
resolved config is actually launchable — that ``league.harness.build_driver``
accepts every side's driver spec — is the test suite's job
(``tests/test_presets.py``), not this module's: keeping the dependency one
-way (presets -> engine/store, never presets -> harness) is what lets a new
preset stay "just a data entry."
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from league.engine.scenario import get_scenario, scenario_ids
from league.store import validate_id

# Mirrors league.harness.SESSION_TRANSPORTS's keys WITHOUT importing harness
# (see the module docstring's one-way-dependency note). A regression test
# (tests/test_presets.py::test_resident_transports_mirror_the_harness_session_transports)
# asserts the two never drift apart.
_RESIDENT_TRANSPORTS: tuple[str, ...] = ("claude", "colleague")

_DRIVER_TYPES = ("bot", "bot-file", "command", "resident")

# The season-0 playtest convention (docs/playtests/season-0/*.config.json):
# a live agent side is invoked as a fresh `claude -p` subprocess unless the
# operator overrides it. Building a driver from this argv never executes it
# (see build_driver docstrings) — it is a safe, literal default, not a live
# call.
_DEFAULT_AGENT_ARGV: tuple[str, ...] = ("claude", "-p", "--model", "claude-sonnet-5")
_DEFAULT_TIMEOUT = 240


@dataclass(frozen=True)
class TeamPreset:
    """One side of a preset match.

    Enough to build the harness ``teams[i]`` entry (``id``, ``name``,
    ``driver``, ``agents``) once the scenario's role roster is known —
    :func:`resolve_preset` derives every agent slot from
    ``Scenario.unit_roles`` directly, so a side's roster can never drift out
    of sync with the scenario it plays on. ``model`` labels every agent slot
    on this side (the season-0 configs use one label per team, not per
    unit). ``bot_tier`` is metadata for a bot-file side only — see the module
    docstring's "data-only bot tiers" note. ``map_read``/``unit_comms`` are
    orchestrator mode's two declared fairness axes (spec c4/c6/h3/h5,
    ``league.harness`` module docstring) — ``None`` means "omit the key
    entirely," the same opt-in contract ``run_match`` itself uses.
    """

    id: str
    name: str
    driver: Mapping[str, Any]
    model: str
    bot_tier: str | None = None
    map_read: str | None = None
    unit_comms: bool | None = None


@dataclass(frozen=True)
class Preset:
    """A named game mode: a scenario, a mode, an explicit seed, and sides."""

    name: str
    description: str
    scenario_id: str
    mode: str
    seed: int
    teams: tuple[TeamPreset, ...]
    max_rounds: int | None = None
    fog: bool = False


def _bot_side(team_id: str, name: str) -> TeamPreset:
    """The in-harness deterministic greedy bot (``league.harness.make_bot_driver``)
    — the baseline opponent, residency ``"bot"``."""
    return TeamPreset(id=team_id, name=name, driver={"type": "bot"}, model="bot:greedy")


def _bot_file_side(team_id: str, name: str, tier: str) -> TeamPreset:
    """A coded strategy from ``bots/<tier>.py`` (the bot-file lane, plan task
    t2 of the SEASON-0 plan, spec c3/h2) — also residency ``"bot"``."""
    return TeamPreset(
        id=team_id,
        name=name,
        driver={"type": "bot-file", "strategy": tier},
        model=f"bot-file:{tier}",
        bot_tier=tier,
    )


def _solo_vs_bot() -> Preset:
    return Preset(
        name="solo-vs-bot",
        description=(
            "One agent commands the whole roster alone, handicapped to a single "
            "action per turn (the coordination-necessity handicap), against the "
            "house ladder's named silver strategy (bots/rusher.py)."
        ),
        scenario_id="skirmish-1",
        mode="competitive",
        seed=20260710,
        teams=(
            TeamPreset(
                id="solo",
                name="Solo Agent",
                driver={
                    "type": "command",
                    "solo": True,
                    "argv": list(_DEFAULT_AGENT_ARGV),
                    "timeout": _DEFAULT_TIMEOUT,
                },
                model="claude-sonnet-5",
            ),
            _bot_file_side("house", "House Rusher (silver)", "rusher"),
        ),
    )


def _team_vs_bot() -> Preset:
    return Preset(
        name="team-vs-bot",
        description=(
            "One mind per seat, stateless (a fresh subprocess call every turn — "
            "the command driver's default residency), against the deterministic "
            "greedy bot baseline."
        ),
        scenario_id="skirmish-1",
        mode="competitive",
        seed=20260711,
        teams=(
            TeamPreset(
                id="team",
                name="Agent Team",
                driver={
                    "type": "command",
                    "per_seat": True,
                    "residency": "stateless",
                    "argv": list(_DEFAULT_AGENT_ARGV),
                    "timeout": _DEFAULT_TIMEOUT,
                },
                model="claude-sonnet-5",
            ),
            _bot_side("house", "House Baseline"),
        ),
    )


def _team_vs_team() -> Preset:
    return Preset(
        name="team-vs-team",
        description=(
            "Bot-vs-bot: two bot-file strategies (bots/rusher.py) play each "
            "other with no live process on either side — fully offline, "
            "deterministic given the seed."
        ),
        scenario_id="skirmish-1",
        mode="competitive",
        seed=20260712,
        teams=(
            _bot_file_side("blue", "Blue Rusher", "rusher"),
            _bot_file_side("red", "Red Rusher", "rusher"),
        ),
    )


def _orchestrator_vs_bot() -> Preset:
    return Preset(
        name="orchestrator-vs-bot",
        description=(
            "Orchestrator mode (plan task t6, spec c4/c6/h3/h5): a master mind "
            "guides per-seat ground agents by message only (unit_comms off, its "
            "own declared default) on the fogbound scenario, against the greedy "
            "bot baseline."
        ),
        scenario_id="skirmish-2",
        mode="competitive",
        seed=20260713,
        teams=(
            TeamPreset(
                id="fable",
                name="Orchestrated Team",
                driver={
                    "type": "command",
                    "per_seat": True,
                    "argv": list(_DEFAULT_AGENT_ARGV),
                    "timeout": _DEFAULT_TIMEOUT,
                    "master": {
                        "argv": list(_DEFAULT_AGENT_ARGV),
                        "timeout": _DEFAULT_TIMEOUT,
                        "id": "fable-master",
                    },
                },
                model="claude-sonnet-5",
                map_read="full",
                unit_comms=False,
            ),
            _bot_side("house", "House Baseline"),
        ),
        fog=True,
    )


def _resident_vs_bot() -> Preset:
    return Preset(
        name="resident-vs-bot",
        description=(
            "One long-lived session per seat for the whole match (plan task t5) "
            "on the fogbound scenario, against the deterministic greedy bot "
            "baseline."
        ),
        scenario_id="skirmish-2",
        mode="competitive",
        seed=20260714,
        teams=(
            TeamPreset(
                id="resident",
                name="Resident Team",
                driver={
                    "type": "resident",
                    "transport": "claude",
                    "command": "claude",
                    "model": "claude-sonnet-5",
                    "timeout": _DEFAULT_TIMEOUT,
                },
                model="claude-sonnet-5",
            ),
            _bot_side("house", "House Baseline"),
        ),
        fog=True,
    )


def _build_registry() -> tuple[Preset, ...]:
    """Declaration order IS the stable order — the one place a new preset is
    wired in (a data entry, per the module docstring)."""
    return (
        _solo_vs_bot(),
        _team_vs_bot(),
        _team_vs_team(),
        _orchestrator_vs_bot(),
        _resident_vs_bot(),
    )


def registry() -> tuple[Preset, ...]:
    """The bundled preset registry, in stable declaration order.

    Pure: builds a fresh tuple of frozen dataclasses on every call, so no
    caller can mutate the bundled set out from under another (acceptance 1:
    "presets are enumerable programmatically ... with stable ordering").
    """
    return _build_registry()


def preset_names() -> tuple[str, ...]:
    """Just the names, in the same stable order as :func:`registry`."""
    return tuple(p.name for p in registry())


def get_preset(name: str) -> Preset:
    """The one bundled preset named ``name``, or a ``ValueError`` listing
    every known name — the same "fail loud, name the fix" contract every
    other lookup in this repo follows (``league.engine.scenario.get_scenario``,
    ``league.harness.build_driver``)."""
    for preset in registry():
        if preset.name == name:
            return preset
    raise ValueError(f"unknown preset {name!r}; known: {', '.join(preset_names())}")


def _validate_driver(driver: Mapping[str, Any], *, team_id: str) -> None:
    kind = driver.get("type")
    if kind not in _DRIVER_TYPES:
        raise ValueError(
            f"team {team_id!r}: unknown driver type {kind!r}; expected one of {_DRIVER_TYPES}"
        )
    if kind == "bot-file":
        strategy = driver.get("strategy")
        if not strategy:
            raise ValueError(f"team {team_id!r}: 'bot-file' driver requires a 'strategy' name")
        validate_id(str(strategy), what="bot strategy name")
    if kind == "command":
        argv = driver.get("argv")
        if not argv or not isinstance(argv, list):
            raise ValueError(f"team {team_id!r}: 'command' driver requires a non-empty argv")
        if driver.get("solo") and driver.get("per_seat"):
            raise ValueError(
                f"team {team_id!r}: 'command' driver cannot set both 'solo' and 'per_seat'"
            )
        master = driver.get("master")
        if master is not None and (not master.get("argv") or not isinstance(master["argv"], list)):
            raise ValueError(
                f"team {team_id!r}: orchestrator 'master' sub-driver requires a non-empty argv"
            )
    if kind == "resident":
        transport = driver.get("transport")
        if transport not in _RESIDENT_TRANSPORTS:
            raise ValueError(
                f"team {team_id!r}: unknown resident transport {transport!r}; "
                f"expected one of {_RESIDENT_TRANSPORTS}"
            )


def _team_dict(team: TeamPreset, unit_roles: tuple[str, ...]) -> dict[str, Any]:
    validate_id(team.id, what="team id")
    _validate_driver(team.driver, team_id=team.id)
    if team.bot_tier is not None:
        validate_id(team.bot_tier, what="bot tier")
    agents = [
        {
            "id": validate_id(f"{team.id}-{i + 1}", what="agent id"),
            "model": team.model,
            "role": role,
        }
        for i, role in enumerate(unit_roles)
    ]
    out: dict[str, Any] = {
        "id": team.id,
        "name": team.name,
        "driver": dict(team.driver),
        "agents": agents,
    }
    if team.map_read is not None:
        out["map_read"] = team.map_read
    if team.unit_comms is not None:
        out["unit_comms"] = team.unit_comms
    return out


def resolve_preset(preset: Preset) -> dict[str, Any]:
    """Turn any :class:`Preset` — bundled or hand-built — into the EXACT dict
    shape :func:`league.harness.run_match` accepts (acceptance 3: this
    function is generic, never special-cased on ``preset.name``).

    Raises ``ValueError`` on structurally invalid data (unknown scenario,
    unsupported mode, wrong team count for the mode, duplicate/invalid team
    ids, a malformed driver spec) — every failure is caught here, before
    anything is ever handed to the harness.
    """
    validate_id(preset.name, what="preset name")
    if preset.scenario_id not in scenario_ids():
        raise ValueError(
            f"preset {preset.name!r}: unknown scenario {preset.scenario_id!r}; "
            f"known: {', '.join(scenario_ids())}"
        )
    scenario = get_scenario(preset.scenario_id)
    if preset.mode not in scenario.modes:
        raise ValueError(
            f"preset {preset.name!r}: scenario {scenario.id!r} does not support "
            f"mode {preset.mode!r}; supports {scenario.modes}"
        )
    required_sides = 2 if preset.mode == "competitive" else 1
    if len(preset.teams) != required_sides:
        raise ValueError(
            f"preset {preset.name!r}: mode {preset.mode!r} needs exactly {required_sides} "
            f"team(s), got {len(preset.teams)}"
        )
    if not isinstance(preset.seed, int) or preset.seed < 0:
        raise ValueError(f"preset {preset.name!r}: seed must be a non-negative int")

    team_dicts = [_team_dict(team, scenario.unit_roles) for team in preset.teams]
    seen_ids = set()
    for team in team_dicts:
        if team["id"] in seen_ids:
            raise ValueError(f"preset {preset.name!r}: duplicate team id {team['id']!r}")
        seen_ids.add(team["id"])

    config: dict[str, Any] = {
        "match": {
            "scenario": preset.scenario_id,
            "mode": preset.mode,
            "seed": preset.seed,
            "id": f"m-preset-{preset.name}",
        },
        "teams": team_dicts,
    }
    if preset.max_rounds is not None:
        config["max_rounds"] = preset.max_rounds
    if preset.fog:
        config["fog"] = True
    return config


def resolve(name: str) -> dict[str, Any]:
    """``preset name -> launchable harness config`` — the public entry point
    ``league play <preset>`` (plan task t3, not this module's job) will call."""
    return resolve_preset(get_preset(name))
