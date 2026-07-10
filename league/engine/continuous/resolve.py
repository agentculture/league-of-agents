"""The continuous resolver — time is the referee, and posts have race semantics.

This is the crown of the continuous lane (plan C7-t5, spec c9/h9, c8). Where the
grid's ``tick.py`` resolved one uniform simultaneous turn, this resolves an
*event timeline*: every action carries an in-game duration, the earliest
completion orders the world, and a unit that finishes sooner gets its next
decision point sooner. It obeys the grid engine's load-bearing discipline
exactly — **the resolver never edits state directly; it emits events and folds
them with** :func:`~league.engine.continuous.events.apply_event`, so replaying
the emitted log reproduces the final state byte-for-byte. The timeline is
resolver-local scheduling machinery, *not* match state, so managing it directly
is not a state mutation.

The loop
--------
1. Emit ``match_started``; then, in canonical ``(team_id, unit_id)`` order, give
   every unit a ``decision_point`` and ask the decision function for its first
   action, scheduling each on the timeline.
2. While the timeline is non-empty and the next completion is within
   ``time_limit`` and the missions have not all resolved: pop the earliest
   completion, resolve its effect (emit the effect event + ``action_completed``
   **or** ``action_failed``, plus any race cascade), then hand every unit that
   became idle a ``decision_point`` and schedule its next action.
3. Emit ``match_finished`` with the outcome winner.

The decision function is a pure callback ``decide(unit_id, state, menu) ->
action | None`` — it is handed the same menu :func:`~league.engine.continuous.
legal.legal_actions_continuous` returns and picks one entry (or ``None`` to
park). The resolver recomputes every duration and effect from role data and
state, never trusting the caller, so *submission does not decide resolution* —
two decision functions that make the same choices from differently ordered menus
produce byte-identical logs. Scripted callbacks drive the tests here; the live
harness (t7) will wrap real minds around the same signature.

Race and contest rules (explicit engine rules, each with a test)
----------------------------------------------------------------
* **The race.** ``take_post`` takes ``take_post_duration`` game-time to complete.
  A slower unit that starts first can be beaten by a faster unit that starts
  later: whoever's take *completes* first (``post_taken``) wins the post. At that
  instant every **other** in-progress attempt on that post is resolved *now*:
  a different team's attempt ``action_failed`` with reason ``"post taken by a
  faster agent"``, a same-team redundant attempt ``action_failed`` with reason
  ``"post already held by a teammate"``; each loser's timeline entry is canceled
  and it becomes idle with a fresh decision point. Simultaneous completions break
  ties by the timeline's canonical ``(time, team_id, unit_id)`` order.
* **(a) Owner changes mid-attempt.** Attempts do **not** continue against the new
  owner — the ``post_taken`` cascade fails every other live attempt immediately.
  A unit that still wants the post must start a *new* take against the new owner.
* **(b) Cancel/replace at a decision point.** :func:`fail_action` is the
  interruption primitive: it cancels the unit's timeline entry
  (``Timeline.cancel``) and emits ``action_failed`` (which withdraws any take
  attempt and idles the unit), after which a fresh action may be started.
* **(c) Two same-team attempts on one post.** Both count — both are represented
  as concurrent ``takers`` in state. The first to complete wins; the second is
  cleared as a benign ``action_failed`` (``"post already held by a teammate"``)
  in the winner's cascade.
* **(d) Take on a post the team already owns.** Illegal — not offered by the menu
  and refused by :func:`_Resolver._start_action` (via
  :func:`~league.engine.continuous.legal.plan_action`).

Delivery contention (spec c12/h3, plan c8-t3) — deny, don't delay
------------------------------------------------------------------
A delivery completing at a site an **enemy** unit currently occupies is
**DENIED**, not delayed: :func:`_Resolver._delivery_contested` checks, at the
delivery's completion instant, whether any *other-team* unit is
:func:`~league.engine.continuous.space.arrived` at the delivering unit's own
position (the delivery necessarily happens where the unit stands, since
reaching a deliver mission's site is already a precondition of the menu
offering ``deliver`` at all — see ``legal.py``'s ``_plan_deliver``). A contested
delivery emits the existing ``action_failed`` vocabulary with reason
``"delivery denied by enemy presence at the site"`` — the carried resources are
**not** banked (mirroring "nothing to deliver"), and the unit goes idle with a
fresh decision point, exactly like every other denied/interrupted action in
this module. No new event kind is needed: contention is a reason, not a new
fact shape.

**Why DENY, not DELAY.** Both were on the table (plan c8-t3's design note).
Delay would need to re-schedule the pending completion to a later instant —
a second timeline entry, a new "how much later" number to invent and justify,
and a window during which the delivery could be re-contested again, silently
compounding. Deny is atomic: it reuses the timeline's existing pop-one-
completion-at-a-time discipline, needs no new scheduling primitive, and is
exactly as legible in the replay as the race's own loser-cascade
(``action_failed`` with a reason, nothing more). It is also strictly additive:
the rule only ever fires when an enemy unit is actually standing at the site,
so an uncontested delivery (every committed scenario today) takes the
identical code path it always did.

**Why "arrived", not a new radius constant.** "At the site" already has one
meaning everywhere else in this engine — :func:`~league.engine.continuous.
space.arrived` is how ``take_post`` and ``gather`` decide a unit has reached
its target. Reusing it for delivery contention keeps "presence" consistent
lane-wide instead of inventing a second, differently-tuned notion of
closeness this cycle would have to separately justify.

**Same-team simultaneous deliveries: co-delivery, not contention.** The
enemy check only ever looks at *other*-team units, so two teammates
completing a delivery at the identical ``completion_time`` are never
contenders for each other — each is resolved as its own, independent
completion. The timeline's existing canonical ``(completion_time, team_id,
unit_id)`` tie-break (``Timeline.peek``/``advance``) is what orders the two
pops when the instant ties; both bank their carry and both earn their own
``resource_delivered`` + ``action_completed`` pair — nothing new to
implement, since "process one completion at a time, in canonical order" was
already this resolver's rule for every other simultaneous-completion case
(the post race included).

Missions and the outcome
------------------------
Deliver mirrors the grid: a completed delivery banks the whole carry into team
resources, and a deliver mission completes when the team reaches its ``amount``
(dual-award safe). A **hold** mission models an *uninterrupted-ownership window*:
when a team takes the post, the resolver schedules a synthetic ``hold_expiry``
timeline entry at ``taken_time + amount`` (keyed by a reserved ``__hold__:<cp>``
id); if the post is re-taken before then, that entry is canceled and rescheduled
for the new owner, so the window is genuinely uninterrupted. When it fires with
the post still held by the same team since it was taken, the mission completes.
The synthetic entry emits no decision point and starts no action. The winner is
the grid's outcome rule ported to continuous state: mission rewards, plus
``CP_POINTS`` per owned control point, plus delivered resources; cooperative
mode wins iff every mission completed within the limit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from league.engine.continuous.events import CEvent, CMatchLog, apply_event
from league.engine.continuous.legal import legal_actions_continuous, plan_action
from league.engine.continuous.roles import CRoleStats, stats_for
from league.engine.continuous.space import arrived, move_toward
from league.engine.continuous.state import CMatchState
from league.engine.continuous.timeline import ScheduledAction, Timeline

#: Points a competitive team earns per owned control point (mirrors the grid tick).
CP_POINTS = 2

#: Reserved timeline-key prefix for synthetic hold-ownership-window entries. No
#: real unit id may begin with it (validated at resolve start).
_HOLD_PREFIX = "__hold__:"

RoleTable = tuple[tuple[str, CRoleStats], ...]


@dataclass(frozen=True)
class DecisionReply:
    """A decision function's FULL answer at one decision point: the chosen
    ``action`` (a menu-shaped dict, or ``None`` to park) plus the social
    record that rode along with it — the engine-level shape of the pinned
    driver reply ``{"action", "message"?, "plan"?}``
    (``docs/continuous-contract.md``).

    A plain action dict (or ``None``) is still accepted everywhere a
    ``DecisionReply`` is — every pre-existing decision function keeps
    working unchanged; the reply object is only needed when a decision
    carries messages or a plan.

    The interleave convention (issue #36, shared by ``run_cmatch`` and the
    ``cmatch`` CLI so the two driving paths stay byte-identical): the
    resolver records each ``messages`` entry as a ``message_sent`` event and
    ``plan`` as a ``plan_declared`` event immediately AFTER the decision's
    own ``decision_point``/``action_started`` pair (after the lone
    ``decision_point`` when the decision parks). ``from`` is always the
    acting unit's own agent id — never caller input — and a plan is recorded
    once per agent (first declaration wins), both exactly the rules
    ``run_cmatch`` has always enforced.
    """

    action: Optional[dict] = None
    messages: tuple[str, ...] = ()
    plan: Optional[str] = None


DecisionFn = Callable[[str, CMatchState, dict], "Optional[dict] | DecisionReply"]


def _unpack_reply(
    choice: "Optional[dict] | DecisionReply",
) -> tuple[Optional[dict], tuple[str, ...], Optional[str]]:
    if isinstance(choice, DecisionReply):
        return choice.action, tuple(choice.messages), choice.plan
    return choice, (), None


class IllegalContinuousAction(ValueError):
    """A decision function returned an action that is not legal in the state.

    Raised by the resolver's ``_start_action`` when
    :func:`~league.engine.continuous.legal.plan_action` refuses the order — the
    "illegal never resolves" half of the legal<->resolver agreement. Decision
    functions are expected to choose from the menu; a stray order is a loud bug,
    never a silent no-op that advances game time.
    """


@dataclass(frozen=True)
class _HoldExpiry:
    """Synthetic timeline payload marking the close of a hold-ownership window."""

    cp_id: str
    team_id: str
    owned_since: int


@dataclass(frozen=True)
class ResolveResult:
    """The whole resolved match: the ``log`` (initial state + events) and the
    folded ``final_state`` (identical to ``log.final_state()``)."""

    log: CMatchLog
    final_state: CMatchState


def _hold_key(cp_id: str) -> str:
    return f"{_HOLD_PREFIX}{cp_id}"


def _missions_force_end(state: CMatchState) -> bool:
    """True when there are missions and every one is resolved (the grid's
    end-of-match trigger; a mission-free scenario ends only by drained timeline
    or time limit)."""
    return bool(state.missions) and all(m.status != "open" for m in state.missions)


def outcome_points(state: CMatchState) -> dict[str, int]:
    """The deterministic competitive tally (grid ``outcome_points`` ported):
    mission rewards (dual awards paid in full) + ``CP_POINTS`` per owned control
    point + delivered resources."""
    points = {team.id: 0 for team in state.teams}
    for mission in state.missions:
        if mission.status != "completed":
            continue
        for team_id in mission.completed_by:
            if team_id in points:
                points[team_id] += mission.reward
    for cp in state.control_points:
        if cp.owner in points:
            points[cp.owner] += CP_POINTS
    for team in state.teams:
        points[team.id] += team.resources
    return points


def _pick_winner(state: CMatchState, all_resolved: bool) -> str | None:
    if state.mode == "cooperative":
        return state.teams[0].id if all_resolved else None
    points = outcome_points(state)
    if not points:
        return "draw"
    best = max(points.values())
    leaders = sorted(t for t, p in points.items() if p == best)
    return leaders[0] if len(leaders) == 1 else "draw"


class _Resolver:
    """Mutable driver for one resolve pass. Everything reaches state through
    :meth:`emit` (emit + fold); the timeline holds only pending completions."""

    def __init__(
        self,
        initial: CMatchState,
        role_table: RoleTable,
        decision_fn: DecisionFn,
        driver_kinds: dict[str, str] | None,
    ) -> None:
        self.initial = initial
        self.role_table = role_table
        self.decide = decision_fn
        self.driver_kinds = dict(driver_kinds or {})
        self.state = initial
        self.timeline = Timeline()
        self.events: list[CEvent] = []
        self.seq = 0
        self.owned_since: dict[str, int] = {}
        self.plans_declared: set[str] = set()  # agent ids; first declaration wins

    # -- event plumbing ----------------------------------------------------- #
    def emit(self, game_time: int, kind: str, data: dict[str, Any]) -> None:
        """Record one event and fold it into ``self.state`` immediately."""
        event = CEvent(game_time=game_time, seq=self.seq, kind=kind, data=data)
        self.seq += 1
        self.events.append(event)
        self.state = apply_event(self.state, event)

    def _unit(self, unit_id: str):
        for unit in self.state.units:
            if unit.id == unit_id:
                return unit
        raise ValueError(f"unknown unit {unit_id!r}")

    def _by_id(self, items: tuple, item_id: str):
        for item in items:
            if item.id == item_id:
                return item
        raise ValueError(f"no element with id {item_id!r}")

    # -- lifecycle ---------------------------------------------------------- #
    def run(self) -> ResolveResult:
        self._require_no_reserved_ids()
        if self.state.status != "pending":
            raise ValueError(f"cannot resolve a match in status {self.state.status!r}")

        self.emit(0, "match_started", {})
        self._offer_decisions([u.id for u in self.state.units], 0)

        time_limited = False
        while not self.timeline.is_empty():
            nxt = self.timeline.peek()
            if nxt is None or nxt.completion_time > self.state.time_limit:
                time_limited = True
                break
            entry = self.timeline.advance()
            idle = self._resolve_completion(entry)
            if _missions_force_end(self.state):
                break
            self._offer_decisions(idle, entry.completion_time)

        self._finish(time_limited)
        log = CMatchLog(
            initial_state=self.initial, events=tuple(self.events), driver_kinds=self.driver_kinds
        )
        return ResolveResult(log=log, final_state=self.state)

    def _require_no_reserved_ids(self) -> None:
        for unit in self.initial.units:
            if unit.id.startswith(_HOLD_PREFIX):
                raise ValueError(
                    f"unit id {unit.id!r} uses the reserved timeline prefix {_HOLD_PREFIX!r}"
                )

    def _finish(self, time_limited: bool) -> None:
        end_time = self.state.time_limit if time_limited else self.state.clock
        winner = _pick_winner(self.state, _missions_force_end(self.state))
        self.emit(end_time, "match_finished", {"winner": winner})

    # -- decisions ---------------------------------------------------------- #
    def _offer_decisions(self, unit_ids: list[str], game_time: int) -> None:
        """Give each idle unit (canonical order) a decision point and schedule
        whatever its mind chooses. A ``None`` / ``idle`` choice parks the unit.

        A decision may answer with a :class:`DecisionReply` to attach the
        social record: its messages/plan are recorded immediately after the
        decision's own ``decision_point``/``action_started`` pair (the pinned
        interleave convention — see :class:`DecisionReply`)."""
        ordered = sorted(unit_ids, key=lambda uid: (self._unit(uid).team_id, uid))
        for unit_id in ordered:
            unit = self._unit(unit_id)
            if not unit.alive or unit.action is not None:
                continue
            self.emit(game_time, "decision_point", {"unit_id": unit_id, "game_time": game_time})
            menu = legal_actions_continuous(self.state, self.role_table, unit_id)
            action, messages, plan = _unpack_reply(self.decide(unit_id, self.state, menu))
            if action is not None and action.get("kind") not in (None, "idle"):
                self._start_action(unit_id, action, game_time)
            self._record_social(unit, game_time, messages, plan)

    def _record_social(
        self, unit, game_time: int, messages: tuple[str, ...], plan: Optional[str]
    ) -> None:
        """Record a decision's social record as OBSERVATION events (fold
        no-ops), riding the decision they were attached to. ``from`` is the
        seat's own agent id, never caller input (spoof-proof, like the grid);
        a plan is recorded once per agent — first declaration wins."""
        for text in messages:
            self.emit(
                game_time,
                "message_sent",
                {"team_id": unit.team_id, "from": unit.agent_id, "unit_id": unit.id, "text": text},
            )
        if plan and unit.agent_id not in self.plans_declared:
            self.plans_declared.add(unit.agent_id)
            self.emit(
                game_time,
                "plan_declared",
                {"team_id": unit.team_id, "from": unit.agent_id, "text": str(plan)},
            )

    def _start_action(self, unit_id: str, action: dict, game_time: int) -> None:
        plan = plan_action(self.state, self.role_table, unit_id, action)
        if plan is None:
            raise IllegalContinuousAction(
                f"action {action!r} is not legal for unit {unit_id!r} at t={game_time}"
            )
        unit = self._unit(unit_id)
        completion = game_time + plan.duration
        data: dict[str, Any] = {
            "unit_id": unit_id,
            "kind": plan.kind,
            "start_time": game_time,
            "completion_time": completion,
        }
        if plan.target_id is not None:
            data["target_id"] = plan.target_id
        if plan.target_pos is not None:
            data["target_pos"] = plan.target_pos.to_dict()
        self.emit(game_time, "action_started", data)
        caction = self._unit(unit_id).action
        self.timeline.schedule(
            ScheduledAction(
                completion_time=completion, team_id=unit.team_id, unit_id=unit_id, action=caction
            )
        )

    def fail_action(self, unit_id: str, reason: str, game_time: int) -> None:
        """Interruption primitive (contest case b): cancel a unit's pending
        completion and emit ``action_failed`` — withdrawing any take attempt and
        idling the unit — so a fresh order may replace it. Safe on a unit with no
        pending timeline entry (the cancel is a no-op)."""
        self.timeline.cancel(unit_id)
        self.emit(game_time, "action_failed", {"unit_id": unit_id, "reason": reason})

    # -- completion resolution --------------------------------------------- #
    def _resolve_completion(self, entry: ScheduledAction) -> list[str]:
        payload = entry.action
        game_time = entry.completion_time
        if isinstance(payload, _HoldExpiry):
            self._resolve_hold_expiry(payload, game_time)
            return []
        kind = payload.kind
        unit_id = entry.unit_id
        if kind == "move":
            return self._complete_move(unit_id, payload, game_time)
        if kind == "gather":
            return self._complete_gather(unit_id, payload, game_time)
        if kind == "deliver":
            return self._complete_deliver(unit_id, game_time)
        if kind == "take_post":
            return self._complete_take(unit_id, payload, game_time)
        raise ValueError(f"cannot resolve action kind {kind!r}")

    def _complete_move(self, unit_id: str, action, game_time: int) -> list[str]:
        unit = self._unit(unit_id)
        role = stats_for(self.role_table, unit.role)
        duration = action.completion_time - action.start_time
        to = move_toward(unit.pos, action.target_pos, role.move_rate_mu, duration)
        self.emit(
            game_time,
            "unit_moved",
            {"unit_id": unit_id, "from": unit.pos.to_dict(), "to": to.to_dict()},
        )
        self.emit(game_time, "action_completed", {"unit_id": unit_id})
        return [unit_id]

    def _complete_gather(self, unit_id: str, action, game_time: int) -> list[str]:
        unit = self._unit(unit_id)
        role = stats_for(self.role_table, unit.role)
        node = self._by_id(self.state.resource_nodes, action.target_id)
        take = min(role.carry - unit.carrying, node.remaining)
        if take > 0:
            self.emit(
                game_time,
                "resource_gathered",
                {"unit_id": unit_id, "node_id": node.id, "amount": take},
            )
            self.emit(game_time, "action_completed", {"unit_id": unit_id})
        else:
            self.emit(
                game_time,
                "action_failed",
                {"unit_id": unit_id, "reason": "resource node exhausted"},
            )
        return [unit_id]

    def _delivery_contested(self, unit) -> bool:
        """True when an enemy unit is present at ``unit``'s position — the
        delivery site is defended (see the module docstring's "Delivery
        contention" section for the rule and why DENY, not delay)."""
        return any(
            other.alive and other.team_id != unit.team_id and arrived(other.pos, unit.pos)
            for other in self.state.units
        )

    def _complete_deliver(self, unit_id: str, game_time: int) -> list[str]:
        unit = self._unit(unit_id)
        amount = unit.carrying
        if amount <= 0:
            self.emit(
                game_time, "action_failed", {"unit_id": unit_id, "reason": "nothing to deliver"}
            )
            return [unit_id]
        if self._delivery_contested(unit):
            self.emit(
                game_time,
                "action_failed",
                {"unit_id": unit_id, "reason": "delivery denied by enemy presence at the site"},
            )
            return [unit_id]
        team_id = unit.team_id
        self.emit(
            game_time,
            "resource_delivered",
            {"unit_id": unit_id, "team_id": team_id, "amount": amount},
        )
        self.emit(game_time, "action_completed", {"unit_id": unit_id})
        team = self._by_id(self.state.teams, team_id)
        for mission in self.state.missions:
            if (
                mission.kind == "deliver"
                and mission.status == "open"
                and team.resources >= mission.amount
            ):
                self.emit(
                    game_time, "mission_completed", {"mission_id": mission.id, "team_id": team_id}
                )
        return [unit_id]

    def _complete_take(self, unit_id: str, action, game_time: int) -> list[str]:
        unit = self._unit(unit_id)
        cp = self._by_id(self.state.control_points, action.target_id)
        if cp.owner == unit.team_id:
            # Normally unreachable: a teammate's post_taken would already have
            # failed this attempt in its cascade. Kept as a defensive benign fail.
            self.emit(
                game_time,
                "action_failed",
                {"unit_id": unit_id, "reason": "post already held by a teammate"},
            )
            return [unit_id]

        self.emit(
            game_time, "post_taken", {"cp_id": cp.id, "team_id": unit.team_id, "unit_id": unit_id}
        )
        self.emit(game_time, "action_completed", {"unit_id": unit_id})
        self._on_post_taken(cp.id, unit.team_id, game_time)

        idle = [unit_id]
        cp_after = self._by_id(self.state.control_points, cp.id)
        for att in cp_after.takers:  # canonical order; the winner is already cleared
            if att.unit_id == unit_id:
                continue
            reason = (
                "post already held by a teammate"
                if att.team_id == unit.team_id
                else "post taken by a faster agent"
            )
            self.timeline.cancel(att.unit_id)
            self.emit(game_time, "action_failed", {"unit_id": att.unit_id, "reason": reason})
            idle.append(att.unit_id)
        return idle

    # -- hold-ownership window --------------------------------------------- #
    def _open_hold_amounts(self, cp) -> list[int]:
        return [
            m.amount
            for m in self.state.missions
            if m.kind == "hold" and m.status == "open" and arrived(m.pos, cp.pos)
        ]

    def _on_post_taken(self, cp_id: str, team_id: str, game_time: int) -> None:
        self.owned_since[cp_id] = game_time
        self.timeline.cancel(_hold_key(cp_id))  # drop the previous owner's window, if any
        cp = self._by_id(self.state.control_points, cp_id)
        amounts = self._open_hold_amounts(cp)
        if amounts:
            self.timeline.schedule(
                ScheduledAction(
                    completion_time=game_time + min(amounts),
                    team_id=team_id,
                    unit_id=_hold_key(cp_id),
                    action=_HoldExpiry(cp_id=cp_id, team_id=team_id, owned_since=game_time),
                )
            )

    def _resolve_hold_expiry(self, marker: _HoldExpiry, game_time: int) -> None:
        cp = self._by_id(self.state.control_points, marker.cp_id)
        if cp.owner != marker.team_id or self.owned_since.get(cp.id) != marker.owned_since:
            return  # stale: ownership changed since this window opened
        elapsed = game_time - marker.owned_since
        for mission in self.state.missions:
            if (
                mission.kind == "hold"
                and mission.status == "open"
                and arrived(mission.pos, cp.pos)
                and elapsed >= mission.amount
            ):
                self.emit(
                    game_time,
                    "mission_completed",
                    {"mission_id": mission.id, "team_id": marker.team_id},
                )
        remaining = self._open_hold_amounts(cp)
        if remaining:
            self.timeline.schedule(
                ScheduledAction(
                    completion_time=marker.owned_since + min(remaining),
                    team_id=marker.team_id,
                    unit_id=_hold_key(cp.id),
                    action=_HoldExpiry(
                        cp_id=cp.id, team_id=marker.team_id, owned_since=marker.owned_since
                    ),
                )
            )


def resolve_match(
    initial_state: CMatchState,
    role_table: RoleTable,
    decision_fn: DecisionFn,
    *,
    driver_kinds: dict[str, str] | None = None,
) -> ResolveResult:
    """Resolve a full continuous match from a ``pending`` initial state.

    ``decision_fn(unit_id, state, menu)`` is a pure callback handed the menu from
    :func:`~league.engine.continuous.legal.legal_actions_continuous`; it returns a
    chosen menu entry (or ``None`` to park the unit). Returns a
    :class:`ResolveResult` whose ``log`` folds back to ``final_state`` exactly.
    Deterministic: the same inputs yield the identical event sequence and hash.
    """
    return _Resolver(initial_state, role_table, decision_fn, driver_kinds).run()


# -- external-driver stepwise resolution (issue #28) -------------------------
#
# The two functions below let an EXTERNAL caller (a CLI process, one decision
# at a time, across separate invocations -- the ``cmatch`` noun group) drive a
# match to the SAME log a single synchronous ``resolve_match`` call would
# produce, given the same decisions in the same order:
#
# * :func:`due_decisions` -- read-only: which units are OWED a decision right
#   now and have not yet been asked (log-derived, not merely "idle": a unit
#   that was asked and declined stays idle forever afterwards but is no
#   longer due -- see the function's own docstring).
# * :func:`advance_external` -- the write path: REPLAY the log's own already-
#   recorded decisions (extracted from its ``decision_point``/
#   ``action_started`` pairs) through a FRESH ``_Resolver``, then hand the
#   first genuinely new decision point to the caller's ``decide_external``
#   callback. Because this replays through the EXACT SAME ``_Resolver`` code
#   ``resolve_match`` itself uses, and the replayed prefix reproduces
#   byte-for-byte what already happened, the events this call appends are
#   exactly what ``resolve_match`` would have emitted next for the same
#   decision -- that identity IS the external-driver parity proof
#   (``tests/test_continuous_resolve.py``'s
#   ``test_advance_external_matches_resolve_match_byte_for_byte`` and the CLI
#   level proof in ``tests/test_cli_cmatch.py``).
#
# Cost is O(events-so-far) per call (a full replay from t=0) -- trivial at
# this scenario's scale (tens to low hundreds of events per match); a later
# cycle can add real incremental resume if match sizes grow enough to matter.
# No wall-clock/random is introduced anywhere here -- both functions are pure
# over their log/state arguments, so the package's own AST import ban
# (``tests/test_engine_state.py``) stays satisfied trivially.


class NeedsExternalDecision(Exception):
    """Raised by a caller's ``decide_external`` callback (passed to
    :func:`advance_external`) when it cannot answer a due unit's decision
    point synchronously -- the signal that stepwise resolution must stop here
    and wait for a future call. Never raised by this module itself; callers
    of :func:`advance_external` never see it either -- it is caught there."""


def _team_of(state: CMatchState, unit_id: str) -> str:
    for unit in state.units:
        if unit.id == unit_id:
            return unit.team_id
    raise ValueError(f"unknown unit {unit_id!r}")


def due_decisions(clog: CMatchLog) -> list[str]:
    """Units OWED a decision right now and NOT YET asked, in canonical
    ``(team_id, unit_id)`` order -- the exact order
    :meth:`_Resolver._offer_decisions` would ask them in, and (per
    :func:`advance_external`'s contract) the order external answers must
    arrive in for a caller's log to stay byte-identical to a single
    ``resolve_match`` run.

    A unit is due iff it is alive, idle (``action is None``), and has had no
    ``decision_point`` recorded since it most recently went idle (match
    start, or its own last ``action_completed``/``action_failed``). This is
    NOT the same as "idle": once a unit IS asked and the answer is to park
    (no ``action_started`` follows its ``decision_point``), it stays idle
    forever in the log's own terms but is no longer due -- exactly mirroring
    ``resolve_match``'s own behavior, where a parked unit is never offered a
    fresh decision point until something else (an action completing or
    failing) makes it idle again, and nothing does that for a unit with no
    action to complete or fail.

    Empty once the match has finished (or force-ended): the resolver never
    offers a decision after ``match_finished``, even to a unit that happened
    to go idle in the very completion that ended it (a mission-forced end can
    idle a unit without ever emitting its ``decision_point`` -- see
    ``_Resolver.run``'s ``break`` before ``_offer_decisions`` on
    ``_missions_force_end``) -- this mirrors that exactly rather than
    reporting a phantom due unit once play has stopped.
    """
    state = clog.final_state()
    if state.status != "active":
        return []
    idle_since: dict[str, int] = {}
    asked_since: dict[str, int] = {}
    for i, event in enumerate(clog.events):
        if event.kind in ("action_completed", "action_failed"):
            idle_since[event.data["unit_id"]] = i
        elif event.kind == "decision_point":
            asked_since[event.data["unit_id"]] = i
    due = [
        u.id
        for u in state.units
        if u.alive and u.action is None and asked_since.get(u.id, -1) <= idle_since.get(u.id, -1)
    ]
    due.sort(key=lambda uid: (_team_of(state, uid), uid))
    return due


def _recorded_decisions(events: tuple[CEvent, ...]) -> dict[str, list[DecisionReply]]:
    """Replay table: for every PAST ``decision_point``, exactly what it was
    answered with -- a :class:`DecisionReply` whose ``action`` is recomputed
    from the paired ``action_started``'s own recorded ``kind``/``target_id``/
    ``target_pos`` (never trusting anything beyond that -- duration is never
    stored here, since the resolver always recomputes it fresh from role
    data) or ``None`` (it declined / parked), and whose ``messages``/``plan``
    are the social record that rode along with that decision. Keyed by unit
    id, one queue entry per past decision point for that unit, oldest first
    -- a unit asked more than once over the match gets one entry per ask,
    consumed in order by :func:`advance_external`'s replay.

    Relies on ``_offer_decisions``'s own emission order: a ``decision_point``
    is IMMEDIATELY followed by its own ``action_started`` when the decision
    started one (and by nothing for that unit at all when it declined), then
    by the decision's own contiguous ``message_sent``/``plan_declared`` run
    (the :class:`DecisionReply` interleave convention) -- so scanning
    adjacency is a complete and correct test, never a heuristic. A
    ``message_sent`` naming a DIFFERENT unit stops the scan, so a log whose
    observations were tail-appended by the pre-#36 harness simply replays
    those decisions without their social record (such logs are always
    finished -- ``run_cmatch`` runs to completion -- so nothing is ever
    appended after them anyway).
    """
    out: dict[str, list[DecisionReply]] = {}
    for i, event in enumerate(events):
        if event.kind != "decision_point":
            continue
        unit_id = event.data["unit_id"]
        j = i + 1
        action: dict[str, Any] | None = None
        if (
            j < len(events)
            and events[j].kind == "action_started"
            and events[j].data.get("unit_id") == unit_id
        ):
            data = events[j].data
            action = {"kind": data["kind"]}
            if data.get("target_id") is not None:
                action["target_id"] = data["target_id"]
            if data.get("target_pos") is not None:
                action["target_pos"] = data["target_pos"]
            j += 1
        texts: list[str] = []
        plan: str | None = None
        while j < len(events):
            nxt = events[j]
            if nxt.kind == "message_sent" and nxt.data.get("unit_id") == unit_id:
                texts.append(nxt.data["text"])
            elif nxt.kind == "plan_declared" and plan is None:
                plan = nxt.data["text"]
            else:
                break
            j += 1
        out.setdefault(unit_id, []).append(
            DecisionReply(action=action, messages=tuple(texts), plan=plan)
        )
    return out


def advance_external(
    clog: CMatchLog,
    role_table: RoleTable,
    decide_external: DecisionFn,
) -> tuple[CMatchLog, bool]:
    """Replay ``clog`` and extend it by exactly as much as ``decide_external``
    can answer -- the write path behind ``cmatch act``/``cmatch tick``.

    Every decision point ``clog`` has ALREADY recorded an answer for is
    replayed exactly as it happened (:func:`_recorded_decisions`, social
    record included); the first genuinely NEW decision point is handed to
    ``decide_external(unit_id, state, menu)``, which returns a chosen
    menu-shaped action dict, ``None`` (park), a :class:`DecisionReply` (an
    action plus the messages/plan riding it), or raises
    :class:`NeedsExternalDecision` to stop without answering. Whatever it
    returns, the resolver's OWN loop then continues exactly as
    ``resolve_match`` would -- auto-advancing through any FURTHER decision
    points ``decide_external`` can also answer (e.g. a ``tick`` resolving
    several bot-driven units and completions in a row) -- until either a
    decision point neither the log nor ``decide_external`` can answer is
    reached (:class:`NeedsExternalDecision` stops the replay there, caught
    internally -- callers never see it) or the match naturally finishes
    (empty timeline / time limit / missions all resolved -- the same
    conditions ``resolve_match`` itself applies).

    Returns ``(new_log, finished)``: ``new_log`` is ``clog`` with every event
    this call produced appended (identical to ``clog`` if it could not
    advance at all); ``finished`` is True iff ``match_finished`` was emitted
    this call.

    Two pieces of bookkeeping beyond a plain replay:

    * when ``decide_external`` raises, ``_offer_decisions`` has ALREADY
      emitted that unit's ``decision_point`` (it always emits it before
      asking) -- so the freshly-replayed event stream ends with one dangling,
      unanswered ``decision_point``. Persisting it would wrongly mark that
      unit "already asked" (and therefore no longer :func:`due_decisions`)
      on the next call, when it was never actually answered -- so it is
      trimmed off before anything is returned.
    * ``seat_latency`` events are the one observation kind the resolver never
      emits (wall-clock instrumentation, appended harness-side after
      ``run_cmatch``'s resolution), so the replayed prefix is compared
      against the log with them excluded. A stepwise-driven log never
      contains any; a ``run_cmatch``-produced log that does is always
      finished, so nothing is ever appended after one.
    """
    recorded = _recorded_decisions(clog.events)
    cursor: dict[str, int] = {}

    def decide(unit_id: str, state: CMatchState, menu: dict) -> "Optional[dict] | DecisionReply":
        queue = recorded.get(unit_id)
        idx = cursor.get(unit_id, 0)
        if queue is not None and idx < len(queue):
            cursor[unit_id] = idx + 1
            return queue[idx]
        return decide_external(unit_id, state, menu)

    resolver = _Resolver(clog.initial_state, role_table, decide, dict(clog.driver_kinds))
    try:
        resolver.run()
        finished = True
    except NeedsExternalDecision:
        finished = False
    produced = resolver.events
    if not finished and produced and produced[-1].kind == "decision_point":
        produced = produced[:-1]
    replayable = sum(1 for e in clog.events if e.kind != "seat_latency")
    new_events = tuple(produced[replayable:])
    new_log = CMatchLog(
        initial_state=clog.initial_state,
        events=clog.events + new_events,
        driver_kinds=clog.driver_kinds,
        fog=clog.fog,
    )
    return new_log, finished
