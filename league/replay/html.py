"""Render a match log as a self-contained, mesmerizing HTML replay.

Design notes (dataviz method — see ``docs/replay-design.md`` for the full
rationale, palette values, and the ``validate_palette.js`` results):

* **Color by job.** Team identity is the validated *categorical* pair — clay
  (slot 0) vs violet (slot 1) — stepped per surface (light ``#b65b38``/``#4b3ba6``,
  dark ``#cb6e44``/``#877ae0``); both modes pass all six checks, worst adjacent
  CVD ΔE 86.7 light / 85.7 dark. Control-point ownership is the owner's hue as a
  low-opacity tint. Resources are a fixed element hue (aqua) carried on a
  distinct diamond mark with a numeric label (the secondary encoding that keeps
  it legal beside the team hues). **Status colors** (good ``#0ca30c``, critical
  ``#d03b3b``) are reserved for event moments — delivery/mission/defeat — always
  paired with an icon+label, and never worn by a team. A restrained green
  ``--accent`` (light ``#1e7a4d`` / dark ``#46c79e``) dresses *chrome* only
  (play button, slider, links) — never team identity. Text always wears text
  tokens; identity rides a colored chip/swatch beside the name, never the text.
* **Both themes are deliberately designed** — light is Anthropic cream (warm
  paper surface, warm near-black ink), dark is Culture black-green (deep
  green-tinged black, green-tinged elevation). Each carries its own surface,
  ink, and elevation tokens (not an auto-flip). ``prefers-color-scheme`` picks
  the default; a manual toggle stamps ``data-theme`` on the root and wins in
  both directions.
* **100%-smooth, purposeful motion, all gated by ``prefers-reduced-motion``.**
  During playback units glide between turns with *linear* timing whose duration
  exactly matches the turn-advance interval, so a multi-turn journey reads as one
  continuous, gapless glide (no per-turn accelerate–decelerate lurch); a paused
  step snaps with a short eased transition. A soft ring pulses on a fresh
  capture, a flash celebrates deliveries and mission completions, a red ring
  marks a defeat. Play/pause with an adjustable speed. Timing is CSS-only, so
  generation stays byte-deterministic — the same log renders identical HTML.
* **The side panel is a tabbed deck** (Guide / Events / Teams / Score /
  Scorecard) that uses the viewport width and keeps the board hero in view —
  the assessor guide is the default tab, scrolling inside its own panel rather
  than pushing the board off-screen.
* **The Scorecard tab is the per-unit axis** (cycle-8 t8, spec c6/h6): units
  ranked by grade descending (canonical tie-break), MVP/LVP chips riding the
  winner-chip vocabulary, and every unit's per-purpose breakdown with its
  role's HOME purpose typographically marked (bold ink + a ×2 tag — no new
  color job). Grades come from :func:`league.engine.grades.grade_units` at
  render time, so the document stays a pure function of the log; the guide
  gains a section explaining exactly what the grade weighs.
* **An ambient score, off by default** (cycle-8 t4, spec c17/h10). The
  transport's note toggle plays a generative Eno-vein score — slow lydian pads
  under sparse bells — synthesized at play time with WebAudio primitives from a
  seed derived from data already in the page (match id + seed), so the same
  match always plays the same music. No audio asset, no request, no bytes
  change: the AudioContext is created lazily on the enabling gesture, and
  enabling/disabling never touches the document (see ``docs/replay-design.md``).
* The page embeds the replay data as one ``<script type="application/json">``
  block derived from the log — the HTML and ``--json`` projections cannot
  diverge because they are the same fold.
"""

from __future__ import annotations

import json
import math
from typing import Any, Callable

from league.engine.events import MatchLog, fold_events
from league.engine.grades import (
    CAPTURE_POINTS,
    HOLD_POINTS,
    MESSAGE_POINTS,
    MOVE_POINTS,
    OFF_ROLE_MULTIPLIER,
    ON_ROLE_MULTIPLIER,
    grade_units,
)
from league.engine.probe import probe_match
from league.engine.scenario import Scenario, get_scenario
from league.engine.scoring import (
    CORRELATION_WINDOW,
    PLAN_WINDOW,
    _build_action_index,
    _utterance_useful,
    score_match,
)
from league.engine.state import MatchState
from league.engine.tick import CP_POINTS

# Per-theme palette tokens — the SAME validated hex values behind the CSS
# custom properties in ``_TEMPLATE`` below, one deliberately-stepped set per
# surface (light = Anthropic cream, dark = Culture black-green). Exported as
# structured themes so other renderers built on the same replay fold (e.g.
# ``league.replay.video``'s raster frames, plan task t6) draw with the
# identical, already-validated hues — for either theme — instead of
# re-deriving their own (dataviz palette.md). Team identity is the validated
# categorical pair clay (slot 0) vs violet (slot 1); the full 6-slot order
# passes all six checks in both modes (validate_palette.js — see
# docs/replay-design.md for the recorded verdicts).
THEME_LIGHT: dict[str, Any] = {
    "plane": "#ebe7dc",
    "line": "#c3bba4",
    "ink": "#242019",
    "muted": "#8c8674",
    "glyph_ink": "#ffffff",
    "resource": "#1baf7a",
    "good": "#0ca30c",
    "critical": "#d03b3b",
    "teams": ("#b65b38", "#4b3ba6", "#0e8f76", "#2a78d6", "#eda100", "#e87ba4"),
}
THEME_DARK: dict[str, Any] = {
    "plane": "#0e1613",
    "line": "#2c3b33",
    "ink": "#eaf1ec",
    "muted": "#788a7f",
    "glyph_ink": "#ffffff",
    "resource": "#199e70",
    "good": "#0ca30c",
    "critical": "#d03b3b",
    "teams": ("#cb6e44", "#877ae0", "#1fa083", "#3987e5", "#c98500", "#d55181"),
}
THEMES: dict[str, dict[str, Any]] = {"light": THEME_LIGHT, "dark": THEME_DARK}

# Flat aliases (the light theme) preserved for importers that predate the theme
# split; the raster renderer now selects a theme explicitly via ``THEMES``.
TEAM_COLORS: tuple[str, ...] = THEME_LIGHT["teams"]
RESOURCE_COLOR = THEME_LIGHT["resource"]
STATUS_GOOD = THEME_LIGHT["good"]
STATUS_CRITICAL = THEME_LIGHT["critical"]
BOARD_PLANE = THEME_LIGHT["plane"]
BOARD_LINE = THEME_LIGHT["line"]
BOARD_INK = THEME_LIGHT["ink"]
BOARD_MUTED = THEME_LIGHT["muted"]
GLYPH_INK = THEME_LIGHT["glyph_ink"]


def _snapshot(state: MatchState) -> dict[str, Any]:
    return {
        "turn": state.turn,
        "status": state.status,
        "winner": state.winner,
        "teams": [{"id": t.id, "resources": t.resources} for t in state.teams],
        "units": [
            {
                "id": u.id,
                "team": u.team_id,
                "agent": u.agent_id,
                "role": u.role,
                "pos": list(u.pos),
                "carrying": u.carrying,
                "alive": u.alive,
            }
            for u in state.units
        ],
        "control_points": [
            {"id": c.id, "pos": list(c.pos), "owner": c.owner, "hold": [list(h) for h in c.hold]}
            for c in state.control_points
        ],
        "missions": [
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
        ],
        "resource_nodes": [
            {"id": r.id, "pos": list(r.pos), "remaining": r.remaining} for r in state.resource_nodes
        ],
    }


def build_replay_data(log: MatchLog) -> dict[str, Any]:
    """Everything the replay shows, derived from the log and nothing else."""
    initial = log.initial_state
    grouped: dict[int, list] = {}
    for event in log.events:  # one pass; (turn, seq) order is the log order
        grouped.setdefault(event.turn, []).append(event)
    frames = [_snapshot(initial)]
    events_by_turn: dict[int, list[dict[str, Any]]] = {}
    state = initial
    for turn in sorted(grouped):
        batch = tuple(grouped[turn])
        state = fold_events(state, batch)
        frames.append(_snapshot(state))
        events_by_turn[turn] = [{"kind": e.kind, "data": e.data} for e in batch]

    return {
        "match_id": initial.match_id,
        "scenario_id": initial.scenario_id,
        "seed": initial.seed,
        "mode": initial.mode,
        "grid": {"width": initial.grid_width, "height": initial.grid_height},
        "turn_limit": initial.turn_limit,
        "teams": [
            {
                "id": t.id,
                "name": t.name,
                "agents": [{"id": a.id, "model": a.model, "role": a.role} for a in t.agents],
            }
            for t in initial.teams
        ],
        "frames": frames,
        "events_by_turn": {str(k): v for k, v in events_by_turn.items()},
        "scores": score_match(log),
        "scorecard": build_scorecard(log),
        "guide": build_assessor_guide(log),
    }


def build_scorecard(log: MatchLog) -> dict[str, Any]:
    """The per-unit scorecard the deck's Scorecard tab renders (plan C8-t8).

    A thin display projection over :func:`league.engine.grades.grade_units` —
    the grades themselves are the engine's own fold of the log (pure function,
    byte-deterministic); this only re-shapes them for ranked rendering:
    ``units`` is a LIST ordered by grade descending with the canonical
    ``(team_id, unit_id)`` tie-break (so the top row is the MVP), each entry
    carrying its role, home purpose, grade, full per-purpose breakdown, and
    ``mvp``/``lvp`` flags naming the exact units ``grade_units`` names.
    """
    grades = grade_units(log)
    mvp, lvp = grades["mvp"], grades["lvp"]
    ranked = sorted(
        grades["units"],
        key=lambda uid: (-grades["units"][uid]["grade"], grades["units"][uid]["team_id"], uid),
    )
    units = []
    for uid in ranked:
        entry = grades["units"][uid]
        units.append(
            {
                "unit_id": uid,
                "team_id": entry["team_id"],
                "role": entry["role"],
                "home_purpose": entry["home_purpose"],
                "grade": entry["grade"],
                "breakdown": dict(entry["breakdown"]),
                "mvp": mvp is not None and uid == mvp["unit_id"],
                "lvp": lvp is not None and uid == lvp["unit_id"],
            }
        )
    return {
        "purposes": grades["purposes"],
        "on_role_multiplier": ON_ROLE_MULTIPLIER,
        "off_role_multiplier": OFF_ROLE_MULTIPLIER,
        "units": units,
        "mvp": mvp,
        "lvp": lvp,
    }


# --------------------------------------------------------------------------- #
# The embedded assessor guide (plan task C6-t5, spec c6/h6). The replay must
# TEACH a human to judge coordination quality — phase by phase, from THIS
# match's own facts (real turns, unit ids, mission names), never boilerplate.
# Every fact below is computed here in Python, at render time, from the log
# and the scenario — so the guide is testable server-side and the client JS
# only lays out what the fold already decided.
# --------------------------------------------------------------------------- #

# Stable render order when several key moments share a turn.
_MOMENT_ORDER = {
    "first_capture": 0,
    "mission_completed": 1,
    "delivery_streak": 2,
    "rejection": 3,
    "idle": 4,
}


def build_assessor_guide(log: MatchLog) -> dict[str, Any]:
    """A per-match judge's guide, derived from the scenario and the log alone.

    Four sections a human evaluator reads to score coordination quality:
    ``scenario`` (objectives + the coordination pressure the map creates),
    ``key_moments`` (log-computed inflection points, each a ``#tN`` deep link),
    ``judging`` (the cooperation-v1 signals explained with this match's real
    numbers), and ``checklist`` (how to review: opening/midgame/endgame, real
    delegation vs pseudo-coordination, where dead time and collisions show).
    """
    initial = log.initial_state
    final = log.final_state()

    frame_turns = sorted({initial.turn} | {e.turn for e in log.events})
    frame_set = set(frame_turns)

    def snap(turn: int) -> int:
        """Snap any turn onto the nearest existing frame, so a deep link that
        points at (say) an idle turn with no events still resolves on click."""
        if turn in frame_set:
            return turn
        below = [t for t in frame_turns if t <= turn]
        return below[-1] if below else frame_turns[0]

    try:
        scenario: Scenario | None = get_scenario(initial.scenario_id)
    except Exception:  # noqa: BLE001 - a generated/unknown id just loses the prose extras
        scenario = None

    guide: dict[str, Any] = {
        "scenario": _scenario_facts(initial, scenario),
        "phases": _phases(initial, frame_turns),
        "key_moments": _key_moments(log, final, snap),
        "judging": _judging(log),
        "scorecard": _scorecard_guide(build_scorecard(log)),
        "listening": _listening(initial),
    }
    guide["checklist"] = _checklist(log, guide, snap)

    turns: set[int] = {m["turn"] for m in guide["key_moments"]}
    for jt in guide["judging"].values():
        example_turn = jt["message_utility"]["example_turn"]
        if example_turn is not None:
            turns.add(snap(int(example_turn)))
    for item in guide["checklist"]:
        turns.update(item["turns"])
    guide["deep_link_turns"] = sorted(turns)
    return guide


def _scenario_facts(initial: MatchState, scenario: Scenario | None) -> dict[str, Any]:
    """Section (a): what the scenario asks for and why it forces coordination."""
    objectives = []
    for m in initial.missions:
        pos = tuple(m.pos)
        if m.kind == "deliver":
            text = (
                f"{m.id}: deliver {m.amount} resources to the drop at {pos} — worth {m.reward} pts"
            )
        elif m.kind == "hold":
            text = f"{m.id}: hold the point at {pos} for {m.amount} turns — worth {m.reward} pts"
        else:
            text = f"{m.id}: {m.kind} {m.amount} at {pos} — worth {m.reward} pts"
        objectives.append(
            {
                "id": m.id,
                "kind": m.kind,
                "pos": list(m.pos),
                "amount": m.amount,
                "reward": m.reward,
                "text": text,
            }
        )

    roles = _roles_facts(initial, scenario)
    if initial.mode == "cooperative":
        win = (
            f"One team versus the clock: complete every mission before turn "
            f"{initial.turn_limit}. There is no opponent — the pressure is the turn budget "
            f"and the map, and the only score that separates runs is cooperation quality."
        )
    else:
        win = (
            f"Two teams; the winner is the higher outcome total at turn {initial.turn_limit} "
            f"(or an earlier decisive lead). Outcome = mission rewards + {CP_POINTS} per control "
            f"point held at the end + delivered resources."
        )

    return {
        "id": initial.scenario_id,
        "name": scenario.name if scenario else initial.scenario_id,
        "description": scenario.description if scenario else "",
        "mode": initial.mode,
        "turn_limit": initial.turn_limit,
        "grid": {"width": initial.grid_width, "height": initial.grid_height},
        "teams": [
            {"id": t.id, "name": t.name, "roles": [a.role for a in t.agents]} for t in initial.teams
        ],
        "objectives": objectives,
        "control_points": [{"id": c.id, "pos": list(c.pos)} for c in initial.control_points],
        "resource_nodes": [
            {"id": r.id, "pos": list(r.pos), "remaining": r.remaining}
            for r in initial.resource_nodes
        ],
        "roles": roles,
        "win_condition": win,
        "coordination_pressure": _coordination_pressure(initial, roles),
    }


def _roles_facts(initial: MatchState, scenario: Scenario | None) -> list[dict[str, Any]]:
    order: list[str] = list(scenario.unit_roles) if scenario else []
    if not order:
        for u in initial.units:
            if u.role not in order:
                order.append(u.role)
    out: list[dict[str, Any]] = []
    for role in order:
        entry: dict[str, Any] = {"role": role}
        if scenario is not None:
            try:
                stats = scenario.stats_for(role)
            except ValueError:
                stats = None
            if stats is not None:
                entry.update(
                    {
                        "move": stats.move,
                        "carry": stats.carry,
                        "vision": stats.vision,
                        "can_gather": stats.can_gather,
                        "can_capture": stats.can_capture,
                        "analog": stats.analog,
                    }
                )
        out.append(entry)
    return out


def _coordination_pressure(initial: MatchState, roles: list[dict[str, Any]]) -> list[str]:
    lines = [
        f"{len(initial.missions)} missions and {len(initial.control_points)} control points "
        f"must be handled in parallel inside a {initial.turn_limit}-turn budget — one seat "
        f"cannot be everywhere, so the team has to split the board.",
    ]
    stat_roles = [r for r in roles if "move" in r]
    if stat_roles:
        fastest = max(stat_roles, key=lambda r: r["move"])
        haulier = max(stat_roles, key=lambda r: r["carry"])
        if fastest["role"] != haulier["role"]:
            lines.append(
                f"Roles are lopsided by design: {fastest['role']} moves {fastest['move']} but "
                f"carries only {fastest['carry']}; {haulier['role']} carries {haulier['carry']} "
                f"but crawls at move {haulier['move']}. No unit can scout, haul, and hold at once."
            )
        noecon = [
            r
            for r in stat_roles
            if not r.get("can_gather", True) and not r.get("can_capture", True)
        ]
        if noecon:
            names = ", ".join(r["role"] for r in noecon)
            lines.append(
                f"{names} cannot gather or capture at all (engine-enforced) — they only pay off "
                f"by turning vision and messages into a teammate's action. A team that ignores "
                f"them wastes a seat."
            )
    return lines


def _phase_chunks(
    initial: MatchState, frame_turns: list[int]
) -> tuple[list[int], list[int], list[int]]:
    playable = [t for t in frame_turns if t > initial.turn]
    if not playable:
        return [initial.turn], [initial.turn], [initial.turn]
    k = max(1, math.ceil(len(playable) / 3))
    opening, midgame, endgame = playable[:k], playable[k : 2 * k], playable[2 * k :]
    if not midgame:
        midgame = [opening[-1]]
    if not endgame:
        endgame = [midgame[-1]]
    return opening, midgame, endgame


def _phases(initial: MatchState, frame_turns: list[int]) -> dict[str, list[int]]:
    opening, midgame, endgame = _phase_chunks(initial, frame_turns)
    return {
        "opening": [opening[0], opening[-1]],
        "midgame": [midgame[0], midgame[-1]],
        "endgame": [endgame[0], endgame[-1]],
    }


def _longest_run(sorted_turns: list[int]) -> list[int]:
    best = [sorted_turns[0]]
    cur = [sorted_turns[0]]
    for t in sorted_turns[1:]:
        if t == cur[-1] + 1:
            cur.append(t)
        else:
            if len(cur) > len(best):
                best = cur
            cur = [t]
    return cur if len(cur) > len(best) else best


def _longest_idle(acting: list[int], lo: int, hi: int) -> tuple[int, int] | None:
    if lo > hi:
        return None
    acting_set = set(acting)
    idle_turns = [t for t in range(lo, hi + 1) if t not in acting_set]
    if not idle_turns:
        return None
    run = _longest_run(idle_turns)
    return (run[0], run[-1])


def _key_moments(
    log: MatchLog, final: MatchState, snap: Callable[[int], int]
) -> list[dict[str, Any]]:
    """Section (b): the inflection points a reviewer should scrub to, computed
    from the log — first capture, mission completions, rejection clusters,
    delivery streaks, and the longest idle span per team."""
    initial = log.initial_state
    events = log.events
    team_ids = [t.id for t in initial.teams]
    moments: list[dict[str, Any]] = []

    caps = sorted(
        (e for e in events if e.kind == "control_point_captured"), key=lambda e: (e.turn, e.seq)
    )
    if caps:
        e = caps[0]
        moments.append(
            {
                "turn": e.turn,
                "kind": "first_capture",
                "team": e.data.get("team_id"),
                "title": f"{e.data.get('team_id')} captures {e.data.get('cp_id')}",
                "detail": (
                    "First control point taken. Step back a turn or two: did a teammate call this "
                    "target before the capture (delegation), or did a lone unit wander onto it "
                    "(parallel play)?"
                ),
            }
        )

    completions: dict[str, dict[str, Any]] = {}
    for e in events:
        if e.kind == "mission_completed":
            info = completions.setdefault(e.data["mission_id"], {"turn": e.turn, "teams": []})
            info["teams"].append(e.data["team_id"])
    for mid, info in sorted(completions.items(), key=lambda kv: (kv[1]["turn"], kv[0])):
        teams = sorted(set(info["teams"]))
        moments.append(
            {
                "turn": info["turn"],
                "kind": "mission_completed",
                "team": teams[0] if len(teams) == 1 else None,
                "title": f"{' + '.join(teams)} complete {mid}",
                "detail": (
                    "A mission pays off. Scrub back and reconstruct the setup chain that earned "
                    "it — a coordinated team's completion is the visible consequence of earlier "
                    "moves, not a lucky turn."
                ),
            }
        )

    rejections = sorted(e.turn for e in events if e.kind == "action_rejected")
    if rejections:
        run = _longest_run(rejections)
        count = sum(1 for t in rejections if run[0] <= t <= run[-1])
        span = f"turn {run[0]}" if run[0] == run[-1] else f"turns {run[0]}–{run[-1]}"
        moments.append(
            {
                "turn": run[0],
                "kind": "rejection",
                "team": None,
                "title": f"{count} rejected order{'s' if count != 1 else ''} at {span}",
                "detail": (
                    "A rejected order is wasted delegation — an out-of-range or illegal move that "
                    "burns a seat's turn. Check whether the team recovered next turn or kept "
                    "throwing bad orders."
                ),
            }
        )

    for tid in team_ids:
        deliveries = sorted(
            {
                e.turn
                for e in events
                if e.kind == "resource_delivered" and e.data.get("team_id") == tid
            }
        )
        if deliveries:
            run = _longest_run(deliveries)
            if len(run) >= 2:
                moments.append(
                    {
                        "turn": run[0],
                        "kind": "delivery_streak",
                        "team": tid,
                        "title": f"{tid} delivery streak, turns {run[0]}–{run[-1]}",
                        "detail": (
                            "A sustained gather→deliver loop. Watch the handoff cadence — a "
                            "clean relay keeps the harvester fed and the drop flowing without "
                            "collisions."
                        ),
                    }
                )
        acting = sorted(
            {e.turn for e in events if e.kind == "action_declared" and e.data.get("team_id") == tid}
        )
        gap = _longest_idle(acting, initial.turn + 1, final.turn)
        if gap and (gap[1] - gap[0] + 1) >= 2:
            moments.append(
                {
                    "turn": snap(gap[0]),
                    "kind": "idle",
                    "team": tid,
                    "title": f"{tid} quiet, turns {gap[0]}–{gap[1]}",
                    "detail": (
                        "This team declared no action across this stretch. Dead time is the "
                        "clearest sign of missing coordination — scrub here and decide: a "
                        "deliberate hold, or a stall?"
                    ),
                }
            )

    moments.sort(key=lambda m: (m["turn"], _MOMENT_ORDER.get(m["kind"], 9), m["title"]))
    for m in moments:
        m["anchor"] = f"#t{m['turn']}"
    return moments


def _first_useful_message(log: MatchLog, team_id: str, index: Any) -> tuple[int, str] | None:
    """The first team message whose named referent a teammate then realized —
    the 'click here to see one' example for message-utility (reuses cooperation
    v1's own correlation machinery, exactly as the span probe does)."""
    messages = sorted(
        (
            (e.turn, e.seq, str(e.data.get("text", "")))
            for e in log.events
            if e.kind == "message_sent" and e.data.get("team_id") == team_id
        ),
        key=lambda x: (x[0], x[1]),
    )
    for turn, _seq, text in messages:
        if _utterance_useful(index, team_id, turn, text, CORRELATION_WINDOW):
            return (turn, text)
    return None


def _judging(log: MatchLog) -> dict[str, Any]:
    """Section (c): the cooperation-v1 signals explained with this match's real
    numbers, plus the span-of-control read that separates real delegation from a
    single mind narrating personas it never fielded."""
    initial = log.initial_state
    cooperation = score_match(log, version="v1")["cooperation"]
    probe = probe_match(log)["teams"]
    index = _build_action_index(log)

    out: dict[str, Any] = {}
    for team in initial.teams:
        tid = team.id
        coop = cooperation[tid]
        comps = coop["components"]
        ds, mu = comps["delegation_spread"], comps["message_utility"]
        pf, dis = comps["plan_fidelity"], comps["discipline"]
        example = _first_useful_message(log, tid, index)
        pr = probe.get(tid, {})
        out[tid] = {
            "team_name": team.name,
            "cooperation_score": coop["score"],
            "signals": coop["signals"],
            "delegation_spread": {
                **ds,
                "plain": (
                    f"{ds['base_spread']:.0%} of the roster acted per active turn, minus a "
                    f"{ds['penalty']:.0%} tax for a {ds['rejection_rate']:.0%} rejection rate "
                    f"→ {ds['value']:.2f}. One hero doing everything scores low."
                ),
            },
            "message_utility": {
                "messages": mu["messages"],
                "useful": mu["useful"],
                "value": mu["value"],
                "example_turn": example[0] if example else None,
                "example_text": example[1] if example else None,
                "example_anchor": f"#t{example[0]}" if example else None,
                "plain": (
                    f"{mu['useful']} of {mu['messages']} team messages named something a teammate "
                    f"then did within {CORRELATION_WINDOW} turns → {mu['value']:.2f}. "
                    f"Referent-free chatter never scores."
                ),
            },
            "plan_fidelity": {
                **pf,
                "plain": (
                    f"{pf['useful']} of {pf['plans']} declared plans were followed through within "
                    f"{PLAN_WINDOW} turns → {pf['value']:.2f}."
                ),
            },
            "discipline": {
                **dis,
                "plain": (
                    f"{dis['declared'] - dis['rejected']} of {dis['declared']} declared orders "
                    f"were legal ({dis['rejected']} rejected) → {dis['value']:.2f}."
                ),
            },
            "span": {
                "span": pr.get("span"),
                "roster_size": pr.get("roster_size"),
                "evidence": pr.get("evidence"),
                "plain": (
                    f"{pr.get('span')} of {pr.get('roster_size')} seats show real acting evidence "
                    f"({pr.get('evidence')} mode). A team that only names subagents with no log "
                    f"evidence fields zero — that is pseudo-coordination, not delegation."
                ),
            },
        }
    return out


def _mu_sentence(judging: dict[str, Any]) -> str:
    parts = []
    for tid, jt in judging.items():
        mu = jt["message_utility"]
        piece = f"{tid}: {mu['useful']}/{mu['messages']} messages realized"
        if mu["example_anchor"]:
            piece += f" (click {mu['example_anchor']} for one)"
        parts.append(piece)
    return "This match — " + "; ".join(parts) + "."


def _span_sentence(judging: dict[str, Any]) -> str:
    parts = [
        f"{tid}: span {jt['span']['span']}/{jt['span']['roster_size']}"
        for tid, jt in judging.items()
    ]
    return "This match — " + "; ".join(parts) + "."


def _checklist(
    log: MatchLog, guide: dict[str, Any], snap: Callable[[int], int]
) -> list[dict[str, Any]]:
    """Section (d): the 'how to review' checklist — opening/midgame/endgame,
    real delegation vs pseudo-coordination, and where dead time/collisions show.
    Every item points at concrete #tN turns to scrub to."""
    initial = log.initial_state
    frame_turns = sorted({initial.turn} | {e.turn for e in log.events})
    opening, midgame, endgame = _phase_chunks(initial, frame_turns)
    moments = guide["key_moments"]
    judging = guide["judging"]

    plan_turns = sorted(e.turn for e in log.events if e.kind == "plan_declared")
    opening_turns = sorted(set([opening[0]] + plan_turns[:1]))

    mid_events = sorted(
        {
            m["turn"]
            for m in moments
            if m["kind"] in ("first_capture", "mission_completed")
            and midgame[0] <= m["turn"] <= midgame[-1]
        }
    )
    example_turns = sorted(
        {
            jt["message_utility"]["example_turn"]
            for jt in judging.values()
            if jt["message_utility"]["example_turn"] is not None
        }
    )
    midgame_turns = mid_events or example_turns or [midgame[0]]

    endgame_missions = sorted(
        {
            m["turn"]
            for m in moments
            if m["kind"] == "mission_completed" and endgame[0] <= m["turn"] <= endgame[-1]
        }
    )
    endgame_turns = endgame_missions or [endgame[-1]]

    rejection_turns = sorted({m["turn"] for m in moments if m["kind"] == "rejection"})
    idle_turns = sorted({m["turn"] for m in moments if m["kind"] == "idle"})

    endgame_labels = ", ".join(f"t{t}" for t in endgame_turns)
    rejection_note = f" (see turn {rejection_turns[0]})" if rejection_turns else ""
    idle_note = f" is around turn {idle_turns[0]}" if idle_turns else " is short in this match"

    checklist = [
        {
            "phase": "opening",
            "title": "Opening — did the team break the board up?",
            "turns": opening_turns,
            "check": (
                f"Open the feed at turn {opening[0]}. Read the declared plan and the first "
                f"messages. A coordinating team starts with a plan on record and every seat "
                f"heading to a different objective; units clustered on one cell with no plan is "
                f"not coordination."
            ),
        },
        {
            "phase": "midgame",
            "title": "Midgame — real delegation or narration?",
            "turns": midgame_turns,
            "check": (
                "For each message that names a target (a control point, node, cell, or teammate), "
                "scrub forward one or two turns and check a teammate actually went there. Messages "
                "a teammate then realizes are delegation; chatter nobody acts on is "
                "pseudo-coordination. " + _mu_sentence(judging)
            ),
        },
        {
            "phase": "endgame",
            "title": "Endgame — did earlier moves compound?",
            "turns": endgame_turns,
            "check": (
                f"Watch the missions close ({endgame_labels}). A coordinated endgame is the "
                f"payoff of setup you already watched happen; a scramble of last-turn deliveries "
                f"with idle seats before it is not."
            ),
        },
        {
            "phase": "pseudo-vs-real",
            "title": "Pseudo-coordination vs real delegation",
            "turns": rejection_turns or midgame_turns,
            "check": (
                "Pseudo-coordination looks like: many messages with low message-utility; a "
                "rejection cluster of wasted orders" + rejection_note + "; a span below the roster "
                "size — one mind narrating several personas it never actually fielded. Real "
                "delegation: each seat evidenced acting, and its span equals the roster. "
                + _span_sentence(judging)
            ),
        },
        {
            "phase": "dead-time",
            "title": "Dead time and collisions",
            "turns": idle_turns or [endgame[-1]],
            "check": (
                "The longest stretch a team declared nothing" + idle_note + " — scrub there and "
                "decide deliberate hold vs stall. Also watch for units stacked on one cell and "
                "not moving (a screen is deliberate; a pile-up that blocks the drop is a "
                "collision) and any unit that never leaves spawn."
            ),
        },
    ]
    for item in checklist:
        item["turns"] = sorted({snap(int(t)) for t in item["turns"] if t is not None})
    return checklist


def _scorecard_guide(scorecard: dict[str, Any]) -> dict[str, Any]:
    """Section (c2): the per-unit scorecard explained EXACTLY (plan C8-t8,
    spec c6/h6/h15) — the four buckets and the event kinds that feed them, the
    on-role multiplier, the MVP/LVP tie-break, and a verdict naming THIS
    match's best and worst unit and why. Every number is interpolated from
    ``league.engine.grades``' own pinned constants, so the guide can never
    drift from the formula it explains; the reviewer test (spec h6) is that
    guide + deck alone answer who carried, who sank, and why."""
    what = (
        f"Every unit earns points in four buckets, each fed by the log events that are "
        f"its plainest observable proxy: economy (resource_gathered and resource_delivered, "
        f"weighted by the event's own amount), control (control_point_captured "
        f"{CAPTURE_POINTS} pts and control_point_held {HOLD_POINTS} pt, credited to the "
        f"team's units standing on the point), recon (unit_moved, {MOVE_POINTS} pt per "
        f"move), and coordination (message_sent, {MESSAGE_POINTS} pt per message)."
    )
    weights = (
        f"A contribution on the unit's own role's home purpose counts "
        f"×{ON_ROLE_MULTIPLIER} (double); the identical contribution made off-role counts "
        f"×{OFF_ROLE_MULTIPLIER} — still more than zero, always less than on-role. "
        f"A unit's grade is the sum of its four buckets; the marked bucket in each "
        f"Scorecard row is that unit's home purpose."
    )
    tie_break = (
        "MVP is the unit with the highest grade, LVP the lowest; ties break "
        "canonically, ascending by (team_id, unit_id)."
    )
    return {
        "title": "Scorecard — best and worst seat",
        "what": what,
        "weights": weights,
        "tie_break": tie_break,
        "verdict": _scorecard_verdict(scorecard),
    }


def _scorecard_verdict(scorecard: dict[str, Any]) -> str:
    """This match's own MVP/LVP named with the why (their top bucket)."""
    mvp, lvp = scorecard["mvp"], scorecard["lvp"]
    if mvp is None or lvp is None:
        return "No units to grade in this match."
    by_id = {u["unit_id"]: u for u in scorecard["units"]}

    def phrase(label: str, named: dict[str, Any]) -> str:
        u = by_id[named["unit_id"]]
        if u["grade"] == 0:
            detail = "no scored contribution in any bucket"
        else:
            top = max(scorecard["purposes"], key=lambda p: u["breakdown"][p])
            where = "its home purpose" if u["home_purpose"] == top else "off-role work"
            detail = f"top bucket {top} at {u['breakdown'][top]} — {where}"
        return f"{label}: {u['unit_id']} ({u['team_id']} {u['role']}, grade {u['grade']}; {detail})"

    if mvp["unit_id"] == lvp["unit_id"]:
        return f"This match graded a single unit, so it is both. {phrase('MVP and LVP', mvp)}."
    return f"This match — {phrase('MVP', mvp)}. {phrase('LVP', lvp)}."


def _listening(initial: MatchState) -> dict[str, Any]:
    """Section (e): the ambient score (cycle-8 t4, spec c17/h10/h12) — what the
    transport's note toggle plays, why it is deterministic for THIS match, and
    the verbatim mood target the next human review rates on the record. The
    mood sentence is the user's brief quoted, not paraphrased: if the score
    misses it, that is a recorded finding, never a silent pass (spec h11)."""
    return {
        "title": "Ambient score",
        "mood_target": "content and relaxed, but also curious and intrigued",
        "how": (
            f"The note toggle in the transport plays a generative ambient score — slow "
            f"lydian pads under sparse bell tones — synthesized live by WebAudio from a "
            f"seed derived from this match ({initial.match_id}, seed {initial.seed}). "
            f"No audio file and no network request: the same match always plays the same "
            f"music, audio stays off until you enable it, and enabling changes nothing "
            f"about the document."
        ),
        "rate": (
            "Rate the mood on the record: the target, verbatim from the user's brief, is "
            "“content and relaxed, but also curious and intrigued”. If the score "
            "misses that target, the miss is a finding for the next cycle, not a silent "
            "pass."
        ),
    }


def render_html(log: MatchLog) -> str:
    """The single-file human view. No external requests, ever."""
    payload = json.dumps(build_replay_data(log), sort_keys=True, ensure_ascii=False)
    payload = payload.replace("</", "<\\/")  # keep </script> out of the data block
    return _TEMPLATE.replace("__MATCH_DATA__", payload)


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>League of Agents — match replay</title>
<style>
:root {
  color-scheme: light;
  --font: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 20px; --s6: 28px;
  --r-sm: 8px; --r-md: 12px; --r-lg: 18px;
  /* movement timing — playback overrides these to (linear, interval) so a
     multi-turn glide is gapless; the paused default is a short eased snap */
  --move-dur: 320ms; --move-ease: cubic-bezier(.34, .03, .24, 1);
  /* status scale — fixed, never themed (dataviz palette.md) */
  --good: #0ca30c; --warning: #fab219; --serious: #ec835a; --critical: #d03b3b;
  /* light = Anthropic cream: warm paper surface + warm near-black ink */
  --plane: #f0eee5; --surface: #faf8f1; --surface-2: #fffef9;
  --ink: #242019; --ink-2: #5a5546; --muted: #8c8674;
  --grid: #ded9c9; --line: #c3bba4; --ring: rgba(36, 32, 25, .10);
  --chip: #ece8dd; --track: #e4dfd2; --board-top: #f3f0e7; --board-bot: #e9e5d9;
  /* chrome accent (restrained green) — buttons/slider/links, never a team */
  --accent: #1e7a4d; --accent-ink: #ffffff;
  /* team identity = validated categorical hues (clay, violet, …), fixed order */
  --team-0: #b65b38; --team-1: #4b3ba6; --team-2: #0e8f76;
  --team-3: #2a78d6; --team-4: #eda100; --team-5: #e87ba4;
  --resource: #1baf7a; --glyph-ink: #ffffff;
  --shadow: 0 1px 2px rgba(36, 32, 25, .05), 0 10px 30px -16px rgba(36, 32, 25, .22);
  --shadow-hero: 0 2px 6px rgba(36, 32, 25, .06), 0 26px 52px -28px rgba(36, 32, 25, .30);
}
@media (prefers-color-scheme: dark) { :root {
  color-scheme: dark;
  --plane: #0c1210; --surface: #111a16; --surface-2: #17231d;
  --ink: #eaf1ec; --ink-2: #aebcb2; --muted: #788a7f;
  --grid: #1e2a24; --line: #2c3b33; --ring: rgba(234, 241, 236, .10);
  --chip: #152019; --track: #182420; --board-top: #121b16; --board-bot: #0b120f;
  --accent: #46c79e; --accent-ink: #06100c;
  --team-0: #cb6e44; --team-1: #877ae0; --team-2: #1fa083;
  --team-3: #3987e5; --team-4: #c98500; --team-5: #d55181;
  --resource: #199e70; --glyph-ink: #ffffff;
  --shadow: 0 1px 0 rgba(255, 255, 255, .04) inset, 0 14px 34px -18px rgba(0, 0, 0, .75);
  --shadow-hero: 0 1px 0 rgba(255, 255, 255, .05) inset, 0 30px 60px -30px rgba(0, 0, 0, .85);
}}
:root[data-theme="light"] {
  color-scheme: light;
  --plane: #f0eee5; --surface: #faf8f1; --surface-2: #fffef9;
  --ink: #242019; --ink-2: #5a5546; --muted: #8c8674;
  --grid: #ded9c9; --line: #c3bba4; --ring: rgba(36, 32, 25, .10);
  --chip: #ece8dd; --track: #e4dfd2; --board-top: #f3f0e7; --board-bot: #e9e5d9;
  --accent: #1e7a4d; --accent-ink: #ffffff;
  --team-0: #b65b38; --team-1: #4b3ba6; --team-2: #0e8f76;
  --team-3: #2a78d6; --team-4: #eda100; --team-5: #e87ba4;
  --resource: #1baf7a; --glyph-ink: #ffffff;
  --shadow: 0 1px 2px rgba(36, 32, 25, .05), 0 10px 30px -16px rgba(36, 32, 25, .22);
  --shadow-hero: 0 2px 6px rgba(36, 32, 25, .06), 0 26px 52px -28px rgba(36, 32, 25, .30);
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --plane: #0c1210; --surface: #111a16; --surface-2: #17231d;
  --ink: #eaf1ec; --ink-2: #aebcb2; --muted: #788a7f;
  --grid: #1e2a24; --line: #2c3b33; --ring: rgba(234, 241, 236, .10);
  --chip: #152019; --track: #182420; --board-top: #121b16; --board-bot: #0b120f;
  --accent: #46c79e; --accent-ink: #06100c;
  --team-0: #cb6e44; --team-1: #877ae0; --team-2: #1fa083;
  --team-3: #3987e5; --team-4: #c98500; --team-5: #d55181;
  --resource: #199e70; --glyph-ink: #ffffff;
  --shadow: 0 1px 0 rgba(255, 255, 255, .04) inset, 0 14px 34px -18px rgba(0, 0, 0, .75);
  --shadow-hero: 0 1px 0 rgba(255, 255, 255, .05) inset, 0 30px 60px -30px rgba(0, 0, 0, .85);
}
* { box-sizing: border-box; margin: 0; }
body {
  font: 14px/1.55 var(--font); background: var(--plane); color: var(--ink);
  padding: 24px 20px; -webkit-font-smoothing: antialiased;
  transition: background .3s ease, color .3s ease;
}
.wrap { max-width: 1200px; margin: 0 auto; }
header { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 20px; }
.brand { display: flex; align-items: center; gap: 11px; }
.brand .mark {
  width: 22px; height: 22px; border-radius: 7px;
  background: linear-gradient(135deg, var(--team-0), var(--team-1));
  box-shadow: var(--shadow); flex: 0 0 auto;
}
header h1 { font-size: 20px; font-weight: 640; letter-spacing: -.02em; }
.meta { display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  background: var(--chip); color: var(--ink-2); border: 1px solid var(--ring);
  border-radius: 999px; padding: 3px 11px; font-size: 12px; white-space: nowrap;
}
.winner-chip { color: var(--good); font-weight: 600; border-color: var(--good); }
#theme-toggle {
  margin-left: auto; display: inline-flex; align-items: center; gap: 8px;
  background: var(--surface-2); color: var(--ink-2); border: 1px solid var(--ring);
  border-radius: 999px; padding: 6px 13px; cursor: pointer; font: inherit; font-size: 12px;
  box-shadow: var(--shadow); transition: color .15s, border-color .15s;
}
#theme-toggle:hover { color: var(--ink); border-color: var(--muted); }
#theme-toggle .tt-ico {
  width: 12px; height: 12px; border-radius: 50%;
  background: linear-gradient(135deg, var(--ink-2), var(--muted));
}
.layout {
  display: grid; grid-template-columns: minmax(0, 1fr) clamp(380px, 34vw, 560px);
  gap: 18px; align-items: start;
}
/* Wide: the board stays the hero on the left; the tabbed side deck sticks in
   view and scrolls INSIDE its own panel, so the guide never pushes the board
   off-screen. Narrow: stack, same tab bar. */
@media (min-width: 1101px) {
  .side { position: sticky; top: 16px; }
  #board-box { position: sticky; top: 16px; }
}
@media (max-width: 1100px) { .layout { grid-template-columns: 1fr; } }
.card {
  background: var(--surface); border: 1px solid var(--ring); border-radius: var(--r-lg);
  padding: 16px; box-shadow: var(--shadow);
}
.card h2 {
  font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: .12em;
  color: var(--muted); margin-bottom: 12px;
}
.board-card { padding: 14px; box-shadow: var(--shadow-hero); }
#board-box { display: flex; flex-direction: column; gap: 14px; }
.board-frame {
  border-radius: var(--r-md); padding: 8px; border: 1px solid var(--ring);
  background: linear-gradient(180deg, var(--board-top), var(--board-bot));
}
#board { width: 100%; height: auto; display: block; }
.gl { stroke: var(--grid); stroke-width: 1; }
#unit-layer g {
  transition: transform var(--move-dur) var(--move-ease), opacity .35s ease;
}
body.booting #unit-layer g { transition: none; }
.u-body { stroke: var(--surface); stroke-width: 2.4; }
.u-glyph { fill: var(--glyph-ink); font-weight: 700; }
.u-carry-dot { stroke: var(--surface); stroke-width: 1.5; }
.u-carry-num { fill: var(--glyph-ink); font-size: 8px; font-weight: 700; }
.cp-disc {
  fill: var(--surface); stroke: var(--line); stroke-width: 2.4;
  transform-box: fill-box; transform-origin: center;
}
.cp-disc.owned { fill-opacity: .24; }
.cp-disc.flood { animation: cp-flood .7s ease-out both; }
.cp-id { fill: var(--muted); font-size: 9px; letter-spacing: .05em; }
.cp-hold { fill: var(--ink-2); font-size: 10px; font-weight: 700; }
.node-num { fill: var(--glyph-ink); font-size: 11px; font-weight: 700; }
.m-ring { fill: none; stroke-width: 1.5; opacity: .5; }
.m-ring.done { stroke-width: 2.4; opacity: 1; }
.m-label { fill: var(--ink-2); font-size: 9.5px; }
.fx {
  fill: none; stroke-width: 2.6; pointer-events: none;
  transform-box: fill-box; transform-origin: center;
}
.fx.ring { animation: fx-ring .9s ease-out forwards; }
.fx.big { animation-duration: 1.15s; }
.fx.flash { stroke: none; animation: fx-flash 1s ease-out forwards; }
@keyframes fx-ring { from { opacity: .85; transform: scale(.3); }
  to { opacity: 0; transform: scale(2.7); } }
@keyframes fx-flash { 0% { opacity: 0; transform: scale(.35); } 30% { opacity: .85; }
  100% { opacity: 0; transform: scale(2.1); } }
@keyframes cp-flood { from { transform: scale(.4); } to { transform: scale(1); } }
@keyframes row-in { from { opacity: 0; transform: translateY(3px); } to { opacity: 1;
  transform: none; } }
.controls { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.transport { display: inline-flex; gap: 4px; }
.controls button {
  background: var(--chip); color: var(--ink); border: 1px solid var(--ring);
  border-radius: 9px; min-width: 34px; height: 32px; cursor: pointer; font-size: 13px;
  font-family: var(--font); display: inline-flex; align-items: center; justify-content: center;
  transition: border-color .15s, background .15s, color .15s;
}
.controls button:hover { border-color: var(--muted); }
#btn-play.on, #btn-audio.on {
  background: var(--accent); color: var(--accent-ink); border-color: var(--accent);
}
#turn-slider { flex: 1; min-width: 120px; accent-color: var(--accent); }
#turn-label {
  font-variant-numeric: tabular-nums; color: var(--ink-2); min-width: 92px;
  text-align: right; font-size: 13px;
}
.speed { display: inline-flex; gap: 4px; }
.speed button { min-width: 40px; font-size: 11px; font-variant-numeric: tabular-nums; }
.speed button.on { border-color: var(--accent); color: var(--accent); }
/* Tabbed side deck — Guide / Events / Teams / Score. Real buttons, roving
   tabindex + aria-selected; styled with the theme tokens in both modes. */
.side { padding: 0; overflow: hidden; }
.tabbar {
  display: flex; gap: 2px; padding: 6px 6px 0; border-bottom: 1px solid var(--grid);
  background: var(--surface-2); position: sticky; top: 0; z-index: 1;
}
.tab {
  appearance: none; background: transparent; color: var(--muted); border: 0;
  border-bottom: 2px solid transparent; margin-bottom: -1px; padding: 9px 13px;
  font: inherit; font-size: 12px; font-weight: 600; letter-spacing: .02em;
  cursor: pointer; border-radius: 8px 8px 0 0; transition: color .15s, border-color .15s;
}
.tab:hover { color: var(--ink-2); }
.tab[aria-selected="true"] { color: var(--accent); border-bottom-color: var(--accent); }
.tab:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.tabpanels { padding: 16px; }
@media (min-width: 1101px) { .tabpanels { max-height: calc(100vh - 210px); overflow-y: auto; } }
.tabpanel[hidden] { display: none; }
.team { display: flex; flex-direction: column; gap: 7px; padding: 11px 0; }
.team + .team { border-top: 1px solid var(--grid); }
.team-head { display: flex; align-items: center; gap: 9px; }
.swatch { width: 12px; height: 12px; border-radius: 4px; box-shadow: 0 0 0 1px var(--ring) inset; }
.team-name { font-weight: 640; letter-spacing: -.01em; }
.team-stats {
  display: flex; gap: 16px; color: var(--ink-2); font-variant-numeric: tabular-nums;
  font-size: 13px;
}
.team-stats b { color: var(--ink); font-weight: 650; }
.agents { display: flex; flex-wrap: wrap; gap: 6px; }
.agents .chip {
  font-size: 11px; padding: 2px 9px; display: inline-flex; align-items: center; gap: 5px;
}
.agents .chip .dot { width: 7px; height: 7px; border-radius: 50%; flex: 0 0 auto; }
#feed {
  display: flex; flex-direction: column; gap: 8px; max-height: 320px; overflow-y: auto;
  padding-right: 2px;
}
.evt {
  display: flex; gap: 9px; font-size: 13px; color: var(--ink-2); line-height: 1.4;
  animation: row-in .3s ease both;
}
.evt .glyph { flex: 0 0 18px; text-align: center; color: var(--muted); }
.evt .txt { min-width: 0; }
.evt.msg { color: var(--ink); }
.evt.msg .body {
  background: var(--chip); border-radius: 10px; padding: 3px 10px; border: 1px solid var(--ring);
  display: inline-block;
}
.evt .who { font-weight: 640; color: var(--ink); }
.evt.big { color: var(--ink); font-weight: 600; }
.evt.good .glyph { color: var(--good); }
.evt.reject { color: var(--critical); }
.evt.reject .glyph { color: var(--critical); }
.empty { color: var(--muted); font-style: italic; }
.score-grid {
  display: grid; grid-template-columns: auto repeat(2, 1fr); gap: 7px 14px;
  font-variant-numeric: tabular-nums; align-items: center;
}
.score-grid .h { color: var(--muted); font-size: 12px; }
.score-grid .team-col {
  color: var(--ink); font-weight: 640; display: inline-flex; align-items: center; gap: 6px;
  justify-content: flex-end;
}
.score-grid .team-col .dot { width: 9px; height: 9px; border-radius: 3px; flex: 0 0 auto; }
.score-grid .num { text-align: right; }
.score-grid .total {
  font-weight: 700; border-top: 1px solid var(--grid); padding-top: 7px; margin-top: 1px;
}
.sig { margin-top: 10px; }
.sig-row {
  display: grid; grid-template-columns: 132px 1fr 40px; gap: 9px; align-items: center;
  margin-bottom: 7px;
}
.sig-row .lbl { color: var(--ink-2); font-size: 11.5px; }
.sig-row .val {
  text-align: right; font-variant-numeric: tabular-nums; color: var(--ink-2); font-size: 11.5px;
}
.bar {
  height: 8px; border-radius: 5px; background: var(--track); position: relative; overflow: hidden;
}
.bar > i { position: absolute; inset: 0 auto 0 0; border-radius: 5px; display: block; }
/* Scorecard tab — the per-unit axis (cycle-8 t8). Units ranked by grade;
   MVP/LVP ride the chip vocabulary with the fixed status hues (the
   winner-chip precedent — a labeled verdict, never a team color); the HOME
   purpose is typographically marked (bold ink + a ×N tag), never a new color
   job. Theme tokens only, so both designed themes style it. */
.sc-unit { padding: 10px 0; border-top: 1px solid var(--grid); }
.sc-unit:first-of-type { border-top: none; padding-top: 2px; }
.sc-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.sc-head .dot { width: 9px; height: 9px; border-radius: 3px; flex: 0 0 auto; }
.sc-name { font-weight: 640; color: var(--ink); }
.sc-role { color: var(--muted); font-size: 12px; }
.sc-grade {
  margin-left: auto; font-weight: 700; color: var(--ink);
  font-variant-numeric: tabular-nums;
}
.sc-chip-mvp { color: var(--good); border-color: var(--good); font-weight: 600; }
.sc-chip-lvp { color: var(--critical); border-color: var(--critical); font-weight: 600; }
.sc-breakdown {
  display: flex; flex-wrap: wrap; gap: 5px 14px; margin-top: 6px;
  font-size: 12px; color: var(--ink-2); font-variant-numeric: tabular-nums;
}
.sc-purpose { display: inline-flex; align-items: baseline; gap: 4px; }
.sc-purpose.sc-home { color: var(--ink); font-weight: 650; }
.sc-x2 {
  background: var(--chip); border: 1px solid var(--ring); border-radius: 5px;
  padding: 0 4px; font-size: 10px; color: var(--ink-2); font-weight: 600;
}
footer { margin-top: 20px; color: var(--muted); font-size: 12px; line-height: 1.6; }
footer kbd {
  font-family: var(--font); background: var(--chip); border: 1px solid var(--ring);
  border-radius: 5px; padding: 1px 6px; font-size: 11px; color: var(--ink-2);
}
/* Assessor guide — the default tab in the side deck. Text wears ink tokens;
   deep links wear the chrome --accent (an interactive affordance, not a team
   identity). No new palette entries. */
#guide-body { display: grid; gap: 22px; }
.guide-h {
  font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .1em;
  color: var(--muted); margin-bottom: 9px;
}
.guide-p { color: var(--ink-2); margin-bottom: 6px; }
.guide-p.muted-p { color: var(--muted); font-size: 13px; }
.guide-list { margin: 4px 0 8px 18px; color: var(--ink-2); }
.guide-list li { margin-bottom: 3px; }
.guide-link {
  color: var(--accent); text-decoration: none; font-variant-numeric: tabular-nums;
  border-bottom: 1px dotted var(--accent); white-space: nowrap;
}
.guide-link:hover { color: var(--ink); border-bottom-color: var(--ink); }
.guide-moment {
  display: flex; gap: 11px; align-items: baseline; padding: 8px 0;
  border-top: 1px solid var(--grid);
}
.guide-moment:first-of-type { border-top: none; }
.guide-moment-title { color: var(--ink); font-weight: 600; }
.guide-moment-detail { color: var(--ink-2); font-size: 13px; margin-top: 1px; }
.guide-jteam {
  background: var(--chip); border: 1px solid var(--ring); border-radius: var(--r-md);
  padding: 12px 13px; margin-bottom: 10px;
}
.guide-jhead { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.guide-jname { font-weight: 640; color: var(--ink); }
.guide-sig { display: flex; gap: 12px; margin-bottom: 5px; }
.guide-sig-l {
  flex: 0 0 118px; color: var(--muted); font-size: 11.5px; text-transform: uppercase;
  letter-spacing: .04em; padding-top: 1px;
}
.guide-sig-v { color: var(--ink-2); font-size: 13px; min-width: 0; }
.guide-example { margin-top: 7px; font-size: 12.5px; color: var(--ink-2); }
.guide-quote { color: var(--ink); font-style: italic; }
.guide-check { padding: 8px 0; border-top: 1px solid var(--grid); }
.guide-check:first-of-type { border-top: none; }
.guide-check-title { color: var(--ink); font-weight: 600; margin-bottom: 2px; }
.guide-check-body { color: var(--ink-2); font-size: 13px; }
.guide-check-links { margin-top: 5px; font-size: 12.5px; color: var(--muted); }
@media (max-width: 560px) { .guide-sig { flex-direction: column; gap: 2px; } }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    transition-duration: 1ms !important; animation-duration: 1ms !important;
    animation-iteration-count: 1 !important;
  }
}
</style>
</head>
<body class="booting">
<div class="wrap">
  <header>
    <div class="brand"><span class="mark" aria-hidden="true"></span><h1>League of Agents</h1></div>
    <div class="meta">
      <span class="chip" id="meta-match"></span>
      <span class="chip" id="meta-mode"></span>
      <span class="chip" id="meta-seed"></span>
      <span class="chip winner-chip" id="meta-winner" hidden></span>
    </div>
    <button id="theme-toggle" type="button" aria-pressed="false">
      <span class="tt-ico" aria-hidden="true"></span><span class="tt-label">Dark</span>
    </button>
  </header>
  <div class="layout">
    <div class="card board-card" id="board-box">
      <div class="board-frame"><svg id="board" role="img" aria-label="match board"></svg></div>
      <div class="controls">
        <div class="transport" role="group" aria-label="transport">
          <button id="btn-first" title="first turn">&#171;</button>
          <button id="btn-prev" title="previous turn">&#8249;</button>
          <button id="btn-play" title="play/pause" aria-label="play">&#9654;</button>
          <button id="btn-next" title="next turn">&#8250;</button>
          <button id="btn-last" title="last turn">&#187;</button>
        </div>
        <input type="range" id="turn-slider" min="0" value="0" aria-label="turn">
        <span id="turn-label"></span>
        <div class="speed" role="group" aria-label="playback speed">
          <button data-speed="0.5" title="half speed">0.5&#215;</button>
          <button data-speed="1" class="on" title="normal speed">1&#215;</button>
          <button data-speed="2" title="double speed">2&#215;</button>
        </div>
        <button id="btn-audio" type="button" title="ambient score (off)"
          aria-pressed="false" aria-label="ambient score (off)">&#9834;</button>
      </div>
    </div>
    <div class="card side" id="side">
      <div class="tabbar" role="tablist" aria-label="side panels">
        <button class="tab" id="tab-guide" role="tab" data-tab="guide"
          aria-selected="true" aria-controls="panel-guide">Guide</button>
        <button class="tab" id="tab-events" role="tab" data-tab="events"
          aria-selected="false" aria-controls="panel-events" tabindex="-1">Events</button>
        <button class="tab" id="tab-teams" role="tab" data-tab="teams"
          aria-selected="false" aria-controls="panel-teams" tabindex="-1">Teams</button>
        <button class="tab" id="tab-score" role="tab" data-tab="score"
          aria-selected="false" aria-controls="panel-score" tabindex="-1">Score</button>
        <button class="tab" id="tab-scorecard" role="tab" data-tab="scorecard"
          aria-selected="false" aria-controls="panel-scorecard" tabindex="-1">Scorecard</button>
      </div>
      <div class="tabpanels">
        <div class="tabpanel" id="panel-guide" role="tabpanel" data-tab="guide"
          aria-labelledby="tab-guide"><div id="guide-body"></div></div>
        <div class="tabpanel" id="panel-events" role="tabpanel" data-tab="events"
          aria-labelledby="tab-events" hidden><div id="feed"></div></div>
        <div class="tabpanel" id="panel-teams" role="tabpanel" data-tab="teams"
          aria-labelledby="tab-teams" hidden><div id="teams"></div></div>
        <div class="tabpanel" id="panel-score" role="tabpanel" data-tab="score"
          aria-labelledby="tab-score" hidden><div id="scores"></div></div>
        <div class="tabpanel" id="panel-scorecard" role="tabpanel" data-tab="scorecard"
          aria-labelledby="tab-scorecard" hidden><div id="scorecard"></div></div>
      </div>
    </div>
  </div>
  <footer>Replay rendered from the match log &mdash; the same record agents read as JSON.
    <kbd>&larr;</kbd> <kbd>&rarr;</kbd> step turns, <kbd>space</kbd> plays; the Guide tab's
    <span class="guide-link">t&#8202;N</span> links scrub to the turn.</footer>
</div>
<script id="match-data" type="application/json">__MATCH_DATA__</script>
<script>
const M = JSON.parse(document.getElementById('match-data').textContent);
const CELL = 46, PAD = 14;
const SVGNS = 'http://www.w3.org/2000/svg';
const teamIndex = {}; M.teams.forEach((t, i) => teamIndex[t.id] = i);
const teamColor = id => `var(--team-${teamIndex[id] ?? 0})`;
const GLYPH = { scout: 'S', harvester: 'H', defender: 'D', striker: 'K', support: 'U' };
// Deterministic fan-out for units sharing a cell — nothing may ever be occluded.
const STACK_OFFSETS = [
  [[0, 0]],
  [[-9, 0], [9, 0]],
  [[0, -9], [-9, 8], [9, 8]],
  [[-9, -9], [9, -9], [-9, 9], [9, 9]],
];
const SPEEDS = { '0.5': 1400, '1': 800, '2': 400 };
const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
let frame = 0, playing = null, speed = 1;

const $ = id => document.getElementById(id);
const cx = x => PAD + x * CELL + CELL / 2;
const cy = y => PAD + y * CELL + CELL / 2;
function esc(s) {
  const d = document.createElement('i'); d.textContent = String(s); return d.innerHTML;
}
function svgEl(tag, attrs, text) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (text != null) el.textContent = text;
  return el;
}

$('meta-match').textContent = `${M.match_id} · ${M.scenario_id}`;
$('meta-mode').textContent = M.mode;
$('meta-seed').textContent = `seed ${M.seed}`;

// ---- static board scaffold (built once; only units + field + fx change per frame)
const W = M.grid.width * CELL + PAD * 2, H = M.grid.height * CELL + PAD * 2;
const svg = $('board');
svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
svg.innerHTML = '';
const gGrid = svgEl('g', { class: 'grid' });
for (let x = 0; x <= M.grid.width; x++)
  gGrid.appendChild(svgEl('line', { x1: PAD + x * CELL, y1: PAD, x2: PAD + x * CELL,
    y2: H - PAD, class: 'gl' }));
for (let y = 0; y <= M.grid.height; y++)
  gGrid.appendChild(svgEl('line', { x1: PAD, y1: PAD + y * CELL, x2: W - PAD,
    y2: PAD + y * CELL, class: 'gl' }));
const gField = svgEl('g', { class: 'field' });
const gUnits = svgEl('g', { id: 'unit-layer' });
const gFx = svgEl('g', { class: 'fx-layer' });
svg.appendChild(gGrid); svg.appendChild(gField); svg.appendChild(gUnits); svg.appendChild(gFx);

// Persistent unit nodes over the whole roster, so a move animates the SAME node
// from its old cell to its new one (a transform transition), never a redraw.
const roster = [], seen = new Set();
for (const f of M.frames) for (const u of f.units)
  if (!seen.has(u.id)) { seen.add(u.id); roster.push(u); }
const unitNodes = new Map();
for (const u of roster) {
  const g = svgEl('g', { class: 'unit', 'data-id': u.id });
  const body = svgEl('circle', { r: 12, class: 'u-body' }); body.style.fill = teamColor(u.team);
  const glyph = svgEl('text', { y: 4, 'text-anchor': 'middle', 'font-size': 11, class: 'u-glyph' },
    GLYPH[u.role] || u.role[0].toUpperCase());
  const carry = svgEl('g', { class: 'u-carry' }); carry.style.opacity = 0;
  const cdot = svgEl('circle', { r: 6, class: 'u-carry-dot' }); cdot.style.fill = 'var(--resource)';
  const cnum = svgEl('text', { y: 3, 'text-anchor': 'middle', class: 'u-carry-num' }, '');
  carry.appendChild(cdot); carry.appendChild(cnum);
  g.appendChild(body); g.appendChild(glyph); g.appendChild(carry);
  g.appendChild(svgEl('title', {}, `${u.id} — ${u.role} · ${u.agent}`));
  gUnits.appendChild(g);
  unitNodes.set(u.id, { g, body, glyph, carry, cnum });
}

// Per-frame placement, incl. the deterministic stack fan-out.
function placement(f) {
  const byCell = new Map();
  for (const u of f.units) {
    if (!u.alive) continue;
    const key = u.pos.join(',');
    if (!byCell.has(key)) byCell.set(key, []);
    byCell.get(key).push(u);
  }
  const out = {};
  for (const stack of byCell.values()) {
    stack.sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
    const n = stack.length;
    // Predefined aesthetic patterns cover 1-4; beyond that, place units evenly
    // on a circle so no two ever land on the same offset (nothing is occluded
    // no matter how many units share a cell — e.g. the deliver square doubling
    // as a control point can stack a full 6-unit match there).
    const offs = n <= STACK_OFFSETS.length ? STACK_OFFSETS[n - 1] : Array.from(
      { length: n },
      (_, i) => {
        const angle = (2 * Math.PI * i) / n - Math.PI / 2;
        return [Math.round(13 * Math.cos(angle)), Math.round(13 * Math.sin(angle))];
      },
    );
    stack.forEach((u, i) => {
      const [dx, dy] = offs[i];
      // Solitary units keep the full 12px radius; stacked ones shrink, never hide.
      const r = stack.length > 1 ? 9 : 12;
      out[u.id] = { x: cx(u.pos[0]) + dx, y: cy(u.pos[1]) + dy, r, carry: u.carrying };
    });
  }
  return out;
}

function renderUnits(f) {
  const p = placement(f);
  for (const [id, n] of unitNodes) {
    const s = p[id];
    if (!s) { n.g.style.opacity = 0; continue; }
    n.g.style.opacity = 1;
    n.g.style.transform = `translate(${s.x}px, ${s.y}px)`;
    n.body.setAttribute('r', s.r);
    n.glyph.setAttribute('font-size', s.r > 9 ? 11 : 9);
    n.glyph.setAttribute('y', s.r > 9 ? 4 : 3);
    if (s.carry > 0) {
      n.carry.style.opacity = 1;
      n.carry.setAttribute('transform', `translate(${s.r - 2}, ${2 - s.r})`);
      n.cnum.textContent = s.carry;
    } else n.carry.style.opacity = 0;
  }
}

function capturesOf(fi) {
  const s = new Set();
  const turn = M.frames[fi].turn;
  for (const e of (M.events_by_turn[String(turn)] || []))
    if (e.kind === 'control_point_captured') s.add(e.data.cp_id);
  return s;
}

function renderField(f, flooded) {
  gField.textContent = '';
  for (const n of f.resource_nodes) {
    const g = svgEl('g',
      { transform: `translate(${cx(n.pos[0])},${cy(n.pos[1])})`, class: 'node' });
    const d = svgEl('rect', { x: -11, y: -11, width: 22, height: 22, rx: 5,
      transform: 'rotate(45)' });
    d.style.fill = 'var(--resource)'; d.style.fillOpacity = n.remaining ? 0.95 : 0.28;
    g.appendChild(d);
    g.appendChild(svgEl('text', { y: 4, 'text-anchor': 'middle', class: 'node-num' }, n.remaining));
    gField.appendChild(g);
  }
  for (const m of f.missions) {
    const done = m.status === 'completed' && m.completed_by.length > 0;
    const single = done && m.completed_by.length === 1;
    const g = svgEl('g',
      { transform: `translate(${cx(m.pos[0])},${cy(m.pos[1])})`, class: 'mission' });
    if (m.kind === 'deliver') {
      // The ring is a MARK and carries team identity; a shared win wears the
      // neutral ink so neither team's color claims it (spec c15).
      const ring = svgEl('circle', { r: 18, class: 'm-ring' + (done ? ' done' : '') });
      ring.style.stroke = single ? teamColor(m.completed_by[0])
        : done ? 'var(--ink-2)' : 'var(--muted)';
      g.appendChild(ring);
    }
    // The label is TEXT — it wears a text token, never the team color.
    g.appendChild(svgEl('text', { y: 30, 'text-anchor': 'middle', class: 'm-label' },
      done ? `${m.id} → ${m.completed_by.join(' + ')}` : `${m.id}: ${m.kind} ${m.amount}`));
    gField.appendChild(g);
  }
  for (const c of f.control_points) {
    const owned = c.owner != null;
    const g = svgEl('g', { transform: `translate(${cx(c.pos[0])},${cy(c.pos[1])})`, class: 'cp' });
    const cls = 'cp-disc' + (owned ? ' owned' : '') + (flooded.has(c.id) ? ' flood' : '');
    const disc = svgEl('circle', { r: 15, class: cls });
    if (owned) { disc.style.fill = teamColor(c.owner); disc.style.stroke = teamColor(c.owner); }
    g.appendChild(disc);
    g.appendChild(svgEl('text', { y: -20, 'text-anchor': 'middle', class: 'cp-id' }, c.id));
    if (c.hold.length) g.appendChild(svgEl('text', { y: 5, 'text-anchor': 'middle',
      class: 'cp-hold' }, c.hold[0][1]));
    gField.appendChild(g);
  }
}

// Restrained, deterministic celebration — only on a forward step, never on a
// scrub or reverse, and never at all under prefers-reduced-motion.
function fxRing(x, y, color, r, big) {
  const c = svgEl('circle', { cx: x, cy: y, r, class: 'fx ring' + (big ? ' big' : '') });
  c.style.stroke = color; gFx.appendChild(c);
  c.addEventListener('animationend', () => c.remove(), { once: true });
}
function fxFlash(x, y, color, r) {
  const c = svgEl('circle', { cx: x, cy: y, r, class: 'fx flash' });
  c.style.fill = color; gFx.appendChild(c);
  c.addEventListener('animationend', () => c.remove(), { once: true });
}
function spawnFx(fi) {
  if (reduce) return;
  const f = M.frames[fi];
  for (const e of (M.events_by_turn[String(f.turn)] || [])) {
    if (e.kind === 'control_point_captured') {
      const cp = f.control_points.find(c => c.id === e.data.cp_id);
      if (cp) fxRing(cx(cp.pos[0]), cy(cp.pos[1]), teamColor(e.data.team_id), 15, true);
    } else if (e.kind === 'resource_delivered') {
      const u = f.units.find(x => x.id === e.data.unit_id);
      if (u) fxFlash(cx(u.pos[0]), cy(u.pos[1]), 'var(--good)', 13);
    } else if (e.kind === 'mission_completed') {
      const m = f.missions.find(x => x.id === e.data.mission_id);
      if (m) { fxRing(cx(m.pos[0]), cy(m.pos[1]), 'var(--good)', 16, true);
        fxFlash(cx(m.pos[0]), cy(m.pos[1]), 'var(--good)', 10); }
    } else if (e.kind === 'unit_defeated') {
      const u = f.units.find(x => x.id === e.data.unit_id);
      if (u) fxRing(cx(u.pos[0]), cy(u.pos[1]), 'var(--critical)', 12, false);
    }
  }
}

function drawTeams(f) {
  $('teams').innerHTML = M.teams.map(t => {
    const res = f.teams.find(x => x.id === t.id).resources;
    const done = f.missions.filter(m => m.completed_by.includes(t.id)).length;
    return `<div class="team">
      <div class="team-head"><span class="swatch" style="background:${teamColor(t.id)}"></span>
        <span class="team-name">${esc(t.name)}</span></div>
      <div class="team-stats"><span>resources <b>${esc(res)}</b></span>
        <span>missions <b>${esc(done)}</b></span></div>
      <div class="agents">${t.agents.map(a =>
        `<span class="chip"><span class="dot" style="background:${teamColor(t.id)}"></span>${
          esc(GLYPH[a.role] || '?')} ${esc(a.id)} · ${esc(a.model)}</span>`).join('')}</div>
    </div>`;
  }).join('');
}

const FEED = {
  match_started: () => ['&#9873;', 'big', 'match started'],
  plan_declared: d => ['&#9776;', 'msg', `<span class="who">${esc(d.team_id)}</span>
    <span class="body">plan · ${esc(d.text)}</span>`],
  message_sent: d => ['&#128172;', 'msg', `<span class="who">${esc(d.from)}</span>
    <span class="body">${esc(d.text)}</span>`],
  action_declared: d => ['&#8227;', '', `${esc(d.unit_id)} declares ${esc(d.action)}${d.to ?
    ' → ' + esc(d.to.join(',')) : ''}`],
  action_rejected: d => ['&#10007;', 'reject',
    `${esc(d.unit_id ?? '?')} rejected — ${esc(d.reason)}`],
  unit_moved: d => ['&#8599;', '', `${esc(d.unit_id)} moves to ${esc(d.to.join(','))}`],
  resource_gathered: d => ['&#9670;', '',
    `${esc(d.unit_id)} gathers ${esc(d.amount)} from ${esc(d.node_id)}`],
  resource_delivered: d => ['&#9679;', 'good', `${esc(d.unit_id)} delivers ${esc(d.amount)}`],
  control_point_captured: d => ['&#9873;', 'big', `${esc(d.team_id)} captures ${esc(d.cp_id)}`],
  control_point_held: d => d.turns ? ['&#9203;', '', `${esc(d.team_id)} holds ${esc(d.cp_id)}
    (${esc(d.turns)})`] : null,
  unit_defeated: d => ['&#9760;', 'reject', `${esc(d.unit_id)} is down`],
  mission_completed: d => ['&#9733;', 'good big',
    `${esc(d.team_id)} completes ${esc(d.mission_id)}`],
  match_finished: d => ['&#9873;', 'big', d.winner ? `match over — ${esc(d.winner)} wins`
    : 'match over'],
  turn_advanced: () => null, turn_resolved: () => null,
};

function drawFeed() {
  const f = M.frames[frame];
  const evts = frame === 0 ? [] : (M.events_by_turn[String(f.turn)] || []);
  const rows = evts.map(e => FEED[e.kind] ? FEED[e.kind](e.data) : null).filter(Boolean)
    .map(([g, cls, html]) => `<div class="evt ${cls}"><span class="glyph">${g}</span>
      <span class="txt">${html}</span></div>`);
  $('feed').innerHTML = rows.length ? rows.join('')
    : '<div class="empty">nothing happened this turn</div>';
}

function drawScores() {
  const S = M.scores, box = $('scores');
  // Team columns name teams in INK with a swatch — never coloured text.
  const head = `<div class="score-grid"><span class="h"></span>` + M.teams.map(t =>
    `<span class="h num team-col"><span class="dot" style="background:${teamColor(t.id)}"></span>${
      esc(t.name)}</span>`).join('') + rows() + `</div>` + sigs();
  function rows() {
    const parts = ['missions', 'control', 'resources'];
    let out = parts.map(p => `<span class="h">${p}</span>` + M.teams.map(t =>
      `<span class="num">${S.outcome[t.id][p]}</span>`).join('')).join('');
    out += `<span class="total">outcome</span>` + M.teams.map(t =>
      `<span class="num total">${S.outcome[t.id].total}</span>`).join('');
    out += `<span class="total">cooperation</span>` + M.teams.map(t =>
      `<span class="num total">${S.cooperation[t.id].score}</span>`).join('');
    return out;
  }
  function sigs() {
    return `<div class="sig">` + M.teams.map(t => {
      const sig = S.cooperation[t.id].signals;
      return Object.entries(sig).map(([k, v]) => `<div class="sig-row">
        <span class="lbl">${esc(t.id)} · ${esc(k.replace(/_/g, ' '))}</span>
        <span class="bar"><i style="width:${Math.round(v * 100)}%;
          background:${teamColor(t.id)}"></i></span>
        <span class="val">${v.toFixed(2)}</span></div>`).join('');
    }).join('') + `</div>`;
  }
  box.innerHTML = head;
}

function updateWinner() {
  const last = M.frames[M.frames.length - 1];
  if (last.status === 'finished') {
    const w = $('meta-winner');
    w.hidden = false;
    w.textContent = last.winner ? (last.winner === 'draw' ? 'draw' : `${last.winner} wins`)
      : 'unresolved';
  }
}

// The embedded assessor guide. Every fact is computed server-side (M.guide);
// this only lays it out. User-derived strings ride textContent, never innerHTML,
// so the panel is XSS-safe by construction — no escaping dance.
function gEl(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text != null) el.textContent = text;
  return el;
}
function gLink(turn) {
  const a = gEl('a', 'guide-link', 't' + turn);
  a.href = '#t' + turn;
  // Scrub in-page on click (works even re-clicking the current turn), and keep
  // the #tN in the URL so the deep link stays shareable.
  a.addEventListener('click', ev => { ev.preventDefault(); scrubToTurn(turn, true); });
  return a;
}
function gSection(title) {
  const s = gEl('div', 'guide-section');
  s.appendChild(gEl('h3', 'guide-h', title));
  return s;
}
function renderGuide() {
  const G = M.guide;
  if (!G) return;
  const body = $('guide-body');
  body.textContent = '';

  // (a) This scenario — objectives, win condition, coordination pressure.
  const sc = G.scenario;
  const s1 = gSection('This scenario \\u2014 ' + sc.name);
  s1.appendChild(gEl('p', 'guide-p', sc.win_condition));
  const ul = gEl('ul', 'guide-list');
  sc.objectives.forEach(o => ul.appendChild(gEl('li', null, o.text)));
  s1.appendChild(ul);
  sc.coordination_pressure.forEach(t => s1.appendChild(gEl('p', 'guide-p muted-p', t)));
  body.appendChild(s1);

  // (b) This match's key moments — each a clickable #tN deep link.
  const s2 = gSection("This match's key moments");
  if (!G.key_moments.length) {
    s2.appendChild(gEl('p', 'guide-p', 'No standout events \\u2014 a quiet match.'));
  }
  G.key_moments.forEach(m => {
    const row = gEl('div', 'guide-moment');
    row.appendChild(gLink(m.turn));
    const wrap = gEl('div', 'guide-moment-txt');
    wrap.appendChild(gEl('div', 'guide-moment-title', m.title));
    wrap.appendChild(gEl('div', 'guide-moment-detail', m.detail));
    row.appendChild(wrap);
    s2.appendChild(row);
  });
  body.appendChild(s2);

  // (c) Judging coordination — the v1 signals in this match's own numbers.
  const s3 = gSection('Judging coordination (cooperation v1)');
  Object.keys(G.judging).forEach(tid => {
    const jt = G.judging[tid];
    const card = gEl('div', 'guide-jteam');
    const head = gEl('div', 'guide-jhead');
    const sw = gEl('span', 'swatch');
    sw.style.background = teamColor(tid);
    head.appendChild(sw);
    head.appendChild(gEl('span', 'guide-jname',
      jt.team_name + ' \\u2014 cooperation ' + jt.cooperation_score + '/100'));
    card.appendChild(head);
    [['delegation spread', jt.delegation_spread.plain],
     ['message utility', jt.message_utility.plain],
     ['plan fidelity', jt.plan_fidelity.plain],
     ['discipline', jt.discipline.plain],
     ['span of control', jt.span.plain]].forEach(pair => {
      const r = gEl('div', 'guide-sig');
      r.appendChild(gEl('span', 'guide-sig-l', pair[0]));
      r.appendChild(gEl('span', 'guide-sig-v', pair[1]));
      card.appendChild(r);
    });
    if (jt.message_utility.example_turn != null) {
      const ex = gEl('div', 'guide-example');
      ex.appendChild(document.createTextNode('a message that landed: '));
      ex.appendChild(gLink(jt.message_utility.example_turn));
      ex.appendChild(gEl('span', 'guide-quote',
        ' \\u201C' + jt.message_utility.example_text + '\\u201D'));
      card.appendChild(ex);
    }
    s3.appendChild(card);
  });
  body.appendChild(s3);

  // (c2) The scorecard — exactly what the per-unit grade weighs (buckets,
  // event kinds, the on-role multiplier, the tie-break) and this match's own
  // MVP/LVP verdict, so guide + deck alone answer who carried and why.
  if (G.scorecard) {
    const sc = gSection(G.scorecard.title);
    sc.appendChild(gEl('p', 'guide-p', G.scorecard.what));
    sc.appendChild(gEl('p', 'guide-p', G.scorecard.weights));
    sc.appendChild(gEl('p', 'guide-p', G.scorecard.tie_break));
    sc.appendChild(gEl('p', 'guide-p muted-p', G.scorecard.verdict));
    body.appendChild(sc);
  }

  // (d) How to review — the checklist, each item pointing at scrub turns.
  const s4 = gSection('How to review this match');
  G.checklist.forEach(c => {
    const item = gEl('div', 'guide-check');
    item.appendChild(gEl('div', 'guide-check-title', c.title));
    item.appendChild(gEl('div', 'guide-check-body', c.check));
    if (c.turns && c.turns.length) {
      const links = gEl('div', 'guide-check-links');
      links.appendChild(document.createTextNode('scrub to '));
      c.turns.forEach((tn, i) => {
        if (i) links.appendChild(document.createTextNode(' \\u00B7 '));
        links.appendChild(gLink(tn));
      });
      item.appendChild(links);
    }
    s4.appendChild(item);
  });
  body.appendChild(s4);

  // (e) The ambient score — what plays, why it is deterministic for this
  // match, and the verbatim mood target the reviewer rates on the record.
  if (G.listening) {
    const s5 = gSection(G.listening.title);
    s5.appendChild(gEl('p', 'guide-p', G.listening.how));
    s5.appendChild(gEl('p', 'guide-p', G.listening.rate));
    body.appendChild(s5);
  }
}

// The Scorecard tab (cycle-8 t8): units ranked by grade descending (the
// server already ordered them with the canonical tie-break — the top row IS
// the MVP), each row a team dot + unit + role, MVP/LVP chips (the winner-chip
// vocabulary: status hue + text label), the grade, and the full per-purpose
// breakdown with the unit's HOME purpose marked (bold ink + a ×N tag naming
// the on-role multiplier). Every fact is computed server-side (M.scorecard,
// via league.engine.grades.grade_units); this only lays it out — log-derived
// strings ride textContent, never innerHTML, so the panel is XSS-safe.
function drawScorecard() {
  const SC = M.scorecard, box = $('scorecard');
  if (!SC) return;
  box.textContent = '';
  const homeTag = '\\u00D7' + SC.on_role_multiplier + ' home';
  SC.units.forEach(u => {
    const row = gEl('div', 'sc-unit');
    const head = gEl('div', 'sc-head');
    const dot = gEl('span', 'dot');
    dot.style.background = teamColor(u.team_id);
    head.appendChild(dot);
    head.appendChild(gEl('span', 'sc-name', u.unit_id));
    head.appendChild(gEl('span', 'sc-role', u.role));
    if (u.mvp) head.appendChild(gEl('span', 'chip sc-chip-mvp', 'MVP'));
    if (u.lvp) head.appendChild(gEl('span', 'chip sc-chip-lvp', 'LVP'));
    head.appendChild(gEl('span', 'sc-grade', String(u.grade)));
    row.appendChild(head);
    const bd = gEl('div', 'sc-breakdown');
    SC.purposes.forEach(p => {
      const home = u.home_purpose === p;
      const cell = gEl('span', 'sc-purpose' + (home ? ' sc-home' : ''));
      cell.appendChild(gEl('span', 'sc-lbl', p));
      cell.appendChild(gEl('span', 'sc-val', String(u.breakdown[p])));
      if (home) cell.appendChild(gEl('span', 'sc-x2', homeTag));
      bd.appendChild(cell);
    });
    row.appendChild(bd);
    box.appendChild(row);
  });
}

function render(forward) {
  const f = M.frames[frame];
  const flooded = (forward && !reduce) ? capturesOf(frame) : new Set();
  renderField(f, flooded);
  renderUnits(f);
  drawTeams(f);
  drawFeed();
  $('turn-slider').value = frame;
  $('turn-label').textContent = `turn ${f.turn} / ${M.turn_limit}`;
  updateWinner();
  if (forward && !reduce) spawnFx(frame);
}

function go(i) {
  i = Math.max(0, Math.min(M.frames.length - 1, i));
  const forward = i === frame + 1;
  frame = i;
  render(forward);
}
const SNAP_MS = 320;
// The fix for the "step accelerate–decelerate" lurch: during PLAYBACK the unit
// glide is LINEAR and its duration is exactly the turn-advance interval, so
// consecutive same-direction turns flow at constant velocity with no pause
// between waypoints — one continuous glide. Paused steps (scrub / prev-next /
// deep link) snap with a short eased transition. Reduced motion collapses both
// to instant via the global media block.
function applyTiming() {
  const st = document.documentElement.style;
  if (playing) {
    st.setProperty('--move-dur', SPEEDS[String(speed)] + 'ms');
    st.setProperty('--move-ease', 'linear');
  } else {
    st.setProperty('--move-dur', SNAP_MS + 'ms');
    st.setProperty('--move-ease', 'cubic-bezier(.34, .03, .24, 1)');
  }
}
function stop() {
  if (!playing) return;
  clearInterval(playing); playing = null;
  const b = $('btn-play'); b.classList.remove('on'); b.innerHTML = '&#9654;';
  b.setAttribute('aria-label', 'play');
  applyTiming();
}
function play() {
  const b = $('btn-play'); b.classList.add('on'); b.innerHTML = '&#10073;&#10073;';
  b.setAttribute('aria-label', 'pause');
  playing = setInterval(() => {
    if (frame >= M.frames.length - 1) stop(); else go(frame + 1);
  }, SPEEDS[String(speed)]);
  applyTiming();
}
function toggle() { playing ? stop() : play(); }
function setSpeed(s) {
  speed = s;
  document.querySelectorAll('.speed button').forEach(b =>
    b.classList.toggle('on', b.dataset.speed === String(s)));
  if (playing) { stop(); play(); }
  applyTiming();
}

$('turn-slider').max = M.frames.length - 1;
$('turn-slider').addEventListener('input', e => { stop(); go(+e.target.value); });
$('btn-first').onclick = () => { stop(); go(0); };
$('btn-prev').onclick = () => { stop(); go(frame - 1); };
$('btn-next').onclick = () => go(frame + 1);
$('btn-last').onclick = () => { stop(); go(M.frames.length - 1); };
$('btn-play').onclick = toggle;
document.querySelectorAll('.speed button').forEach(b =>
  b.onclick = () => setSpeed(parseFloat(b.dataset.speed)));
document.addEventListener('keydown', e => {
  // Keyboard inside the tab bar drives tab navigation, not turn transport.
  if (e.target.closest && e.target.closest('.tabbar')) return;
  if (e.key === 'ArrowLeft') { stop(); go(frame - 1); }
  else if (e.key === 'ArrowRight') go(frame + 1);
  else if (e.key === ' ') { e.preventDefault(); toggle(); }
});
// --- Side-deck tabs: Guide / Events / Teams / Score. Real tab-role buttons
// with roving tabindex + aria-selected, arrow/Home/End navigation, and hidden
// panels; the Guide tab is the default when a guide is present. Deep links and
// the guide's scrub links keep working (they only drive the board), and the
// panels' content is rendered by the same draw* functions as before.
const tabs = Array.from(document.querySelectorAll('.tab'));
function selectTab(name, focus) {
  tabs.forEach(b => {
    const on = b.dataset.tab === name;
    b.setAttribute('aria-selected', String(on));
    b.tabIndex = on ? 0 : -1;
    if (on && focus) b.focus();
  });
  document.querySelectorAll('.tabpanel').forEach(p => { p.hidden = p.dataset.tab !== name; });
}
tabs.forEach((b, i) => {
  b.addEventListener('click', () => selectTab(b.dataset.tab, false));
  b.addEventListener('keydown', ev => {
    let j = null;
    const n = tabs.length;
    if (ev.key === 'ArrowRight' || ev.key === 'ArrowDown') j = (i + 1) % n;
    else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowUp') j = (i - 1 + n) % n;
    else if (ev.key === 'Home') j = 0;
    else if (ev.key === 'End') j = n - 1;
    if (j != null) {
      ev.preventDefault(); ev.stopPropagation();
      while (tabs[j].hidden) j = (j + 1) % n;
      selectTab(tabs[j].dataset.tab, true);
    }
  });
});
if (!M.guide) {
  const gt = $('tab-guide'); if (gt) gt.hidden = true;
  selectTab('events', false);
} else {
  selectTab('guide', false);
}
// The guide's #tN links scrub in-page to the turn a moment or checklist item
// points at, and bring the board into view. Shared by the link click handler
// and the hashchange listener (so a pasted #tN in the address bar works too).
function scrubToTurn(turn, updateHash) {
  const idx = M.frames.findIndex(f => f.turn === +turn);
  if (idx < 0) return;
  // replaceState updates the URL without firing hashchange (no double-scrub).
  if (updateHash && history.replaceState) history.replaceState(null, '', '#t' + turn);
  stop(); go(idx);
  $('board-box').scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'nearest' });
}
window.addEventListener('hashchange', () => {
  const t = (location.hash.match(/^#t(\\d+)$/) || [])[1];
  if (t != null) scrubToTurn(t, false);
});
$('theme-toggle').onclick = () => {
  const root = document.documentElement;
  const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const cur = root.dataset.theme || (dark ? 'dark' : 'light');
  const next = cur === 'dark' ? 'light' : 'dark';
  root.dataset.theme = next;
  const tt = $('theme-toggle');
  tt.setAttribute('aria-pressed', String(next === 'dark'));
  tt.querySelector('.tt-label').textContent = next === 'dark' ? 'Light' : 'Dark';
};
(function initToggleLabel() {
  const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const cur = document.documentElement.dataset.theme || (dark ? 'dark' : 'light');
  $('theme-toggle').querySelector('.tt-label').textContent = cur === 'dark' ? 'Light' : 'Dark';
})();

// ---- Ambient score (cycle-8 t4, spec c17/h10): a generative Eno-vein score,
// synthesized at PLAY TIME from WebAudio primitives — oscillators, gains, a
// low-pass filter, and a convolver whose impulse response is itself
// synthesized from the seeded stream, never a fetched asset. The seed derives
// from data already embedded in this page (match id + seed), so the same
// match always plays the same music; nothing about enabling or disabling the
// score touches the document. OFF by default: the AudioContext is created
// lazily inside the enable path, on the user's own gesture (autoplay policy
// requires one anyway). Two layers map the mood brief: a warm pad bed of open
// major lydian voicings for "content and relaxed", sparse bell tones — with
// the lydian sharp-4 saved as a rare color — for "curious and intrigued".
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function audioSeed() {
  const s = M.match_id + '|' + M.seed;  // data already embedded in the page
  let h = 2166136261 >>> 0;             // FNV-1a over it
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
// Master stays conservative (about a -18 dBFS feel behind a gentle safety
// compressor): the score plays UNDER someone watching a replay, never over it.
const MASTER_LEVEL = 0.3;
const ROOT_MIDI = [41, 43, 45, 48];     // F2 G2 A2 C3 — warm roots only
const PAD_CHORDS = [                    // semitones above root; no minor-3rd low intervals
  [0, 7, 14, 16],   // 1 5 9 3 — home, warm
  [0, 7, 16, 21],   // 1 5 3 6 — the add-6 lift
  [2, 9, 14, 18],   // the lydian II — bright, forward-leaning
  [0, 7, 19, 23],   // 1 5 5 maj7 — open, suspended calm
];
const BELL_STEPS = [0, 2, 4, 7, 9, 11, 14, 16];  // pentatonic-plus-maj7, two octaves up
const midiHz = m => 440 * Math.pow(2, (m - 69) / 12);
const AUDIO = { graph: null, timer: null, on: false };

function makeImpulse(ctx, rnd) {        // synthesized reverb tail — never a fetched asset
  const len = Math.floor(3.2 * ctx.sampleRate);
  const buf = ctx.createBuffer(2, len, ctx.sampleRate);
  for (let ch = 0; ch < 2; ch++) {
    const d = buf.getChannelData(ch);
    for (let i = 0; i < len; i++) d[i] = (rnd() * 2 - 1) * Math.pow(1 - i / len, 2.9);
  }
  return buf;
}
function buildAudio(seed) {
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const master = ctx.createGain(); master.gain.value = 0;
  const safety = ctx.createDynamicsCompressor();
  safety.threshold.value = -22; safety.knee.value = 18; safety.ratio.value = 4;
  safety.attack.value = 0.012; safety.release.value = 0.3;
  master.connect(safety); safety.connect(ctx.destination);
  const rev = ctx.createConvolver();
  rev.buffer = makeImpulse(ctx, mulberry32(seed ^ 0x1F123BB5));
  const wet = ctx.createGain(); wet.gain.value = 0.5; rev.connect(wet); wet.connect(master);
  const padLp = ctx.createBiquadFilter();
  padLp.type = 'lowpass'; padLp.frequency.value = 950; padLp.Q.value = 0.4;
  const padBus = ctx.createGain(); padBus.gain.value = 0.9;
  padBus.connect(padLp); padLp.connect(master);
  const padSend = ctx.createGain(); padSend.gain.value = 0.3;
  padLp.connect(padSend); padSend.connect(rev);
  const lfo = ctx.createOscillator(); lfo.frequency.value = 0.045;  // slow breathing
  const lfoAmt = ctx.createGain(); lfoAmt.gain.value = 240;
  lfo.connect(lfoAmt); lfoAmt.connect(padLp.frequency); lfo.start();
  const bellBus = ctx.createGain(); bellBus.gain.value = 0.75; bellBus.connect(master);
  const bellSend = ctx.createGain(); bellSend.gain.value = 0.9;
  bellBus.connect(bellSend); bellSend.connect(rev);   // bells ride mostly in the reverb
  return { ctx, master, padBus, bellBus };
}
function padChord(A, rootHz, steps, t, dur) {
  // long attack, long release — successive chords crossfade into one bed
  const env = g => {
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(0.05, t + 6);
    g.gain.setValueAtTime(0.05, t + dur - 7);
    g.gain.linearRampToValueAtTime(0, t + dur);
  };
  for (const st of steps) {
    const f = rootHz * Math.pow(2, st / 12);
    for (const det of [-2.5, 2.5]) {
      const o = A.ctx.createOscillator();
      o.type = 'sine'; o.frequency.value = f; o.detune.value = det;
      const g = A.ctx.createGain(); env(g);
      o.connect(g); g.connect(A.padBus); o.start(t); o.stop(t + dur + 0.2);
    }
  }
  const sub = A.ctx.createOscillator();               // a quiet sub-octave root
  sub.type = 'triangle'; sub.frequency.value = rootHz * Math.pow(2, steps[0] / 12) / 2;
  const sg = A.ctx.createGain(); env(sg);
  sub.connect(sg); sg.connect(A.padBus); sub.start(t); sub.stop(t + dur + 0.2);
}
function bellNote(A, f, t, vel) {
  // near-harmonic partials, fast attack, long exponential decay
  for (const [ratio, amp] of [[1, 1], [2.01, 0.38], [3.02, 0.13]]) {
    const o = A.ctx.createOscillator(); o.type = 'sine'; o.frequency.value = f * ratio;
    const g = A.ctx.createGain();
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(0.16 * vel * amp, t + 0.012);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 5 / ratio);
    o.connect(g); g.connect(A.bellBus); o.start(t); o.stop(t + 5 / ratio + 0.1);
  }
}
function startScore() {
  const seed = audioSeed();
  const A = AUDIO.graph = buildAudio(seed);
  // One seeded stream per voice, so the look-ahead scheduler's wall-clock
  // tick cadence can never reorder draws — the whole musical timeline is a
  // pure function of the seed, identical on every enable.
  const padRnd = mulberry32(seed ^ 0x51AB3C02);
  const bellRnd = mulberry32(seed ^ 0x9E3779B9);
  const rootHz = midiHz(ROOT_MIDI[Math.floor(mulberry32(seed)() * ROOT_MIDI.length)]);
  const t0 = A.ctx.currentTime + 0.08;
  let padT = 0, chord = 0, bellT = 2 + bellRnd() * 3;
  function ahead() {
    const now = A.ctx.currentTime - t0;
    while (padT < now + 1.5) {
      const dur = 18 + padRnd() * 8;
      padChord(A, rootHz, PAD_CHORDS[chord], t0 + padT, dur + 8);
      chord = (chord + 1 + Math.floor(padRnd() * (PAD_CHORDS.length - 1))) % PAD_CHORDS.length;
      padT += dur;
    }
    while (bellT < now + 1.5) {
      const curious = bellRnd() < 0.11;               // the rare lydian sharp-4 color
      const step = curious ? 6 : BELL_STEPS[Math.floor(bellRnd() * BELL_STEPS.length)];
      const f = rootHz * Math.pow(2, (24 + step + (bellRnd() < 0.3 ? 12 : 0)) / 12);
      const vel = 0.5 + bellRnd() * 0.5;
      bellNote(A, f, t0 + bellT, vel);
      if (bellRnd() < 0.22)                            // an occasional soft answer
        bellNote(A, f * Math.pow(2, (bellRnd() < 0.5 ? 7 : 4) / 12),
          t0 + bellT + 0.7 + bellRnd() * 0.8, vel * 0.55);
      bellT += 3.5 + bellRnd() * 5.5;
    }
  }
  ahead();
  AUDIO.timer = setInterval(ahead, 240);
  A.master.gain.setValueAtTime(0, A.ctx.currentTime);  // anchor, then fade in
  A.master.gain.linearRampToValueAtTime(MASTER_LEVEL, A.ctx.currentTime + 2);
}
function setAudioButton(on) {
  const b = $('btn-audio');
  b.classList.toggle('on', on);
  b.setAttribute('aria-pressed', String(on));
  const label = on ? 'ambient score (on)' : 'ambient score (off)';
  b.setAttribute('aria-label', label); b.title = label;
}
function audioToggle() {
  if (AUDIO.on) {
    AUDIO.on = false;
    clearInterval(AUDIO.timer); AUDIO.timer = null;
    const A = AUDIO.graph; AUDIO.graph = null;
    if (A) {
      A.master.gain.cancelScheduledValues(A.ctx.currentTime);
      A.master.gain.setValueAtTime(A.master.gain.value, A.ctx.currentTime);
      A.master.gain.linearRampToValueAtTime(0, A.ctx.currentTime + 0.5);
      setTimeout(() => A.ctx.close(), 650);           // runtime teardown only
    }
    setAudioButton(false);
  } else {
    AUDIO.on = true;
    startScore();                // the ctx is born here, on the user's gesture
    setAudioButton(true);
  }
}
$('btn-audio').onclick = audioToggle;

setSpeed(1);
// Deep link: replay.html#t7 opens on turn 7, so reviewers can point at a frame.
const hashTurn = (location.hash.match(/^#t(\\d+)$/) || [])[1];
if (hashTurn != null) {
  const idx = M.frames.findIndex(f => f.turn === +hashTurn);
  if (idx >= 0) frame = idx;
}
drawScores();
drawScorecard();
renderGuide();
render(false);
// Let the first paint land at rest, then arm the movement transitions.
requestAnimationFrame(() => document.body.classList.remove('booting'));
</script>
</body>
</html>
"""
