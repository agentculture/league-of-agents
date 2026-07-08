# Roles — capability contracts that mirror coding work

In *League of Agents* a role is not a label an agent chooses to honour — it is a
**capability contract the engine enforces**. Two levers are quantitative
(`move`, `carry`, `vision`) and two are hard capability booleans (`can_gather`,
`can_capture`). The capability differences live in engine data
(`league/engine/scenario.py`'s `RoleStats`) and in the tick's legality
(`league/engine/tick.py`, mirrored by `league/engine/legal.py`) — never in
prompt convention (spec honesty h11). If a role cannot do something, the tick
rejects the order and `legal_actions` never offers it.

Each role maps to a piece of real software work.

## The roster

| Role | Software-work analog | move | carry | vision | can_gather | can_capture |
|------|----------------------|------|-------|--------|------------|-------------|
| explorer | reconnaissance / code-reading | high (far reach) | 0 | high (far sight) | no | no |
| planner | architect / tech-lead | 1 | 0 | baseline | no | no |
| scout | quick reconnaissance pass | fast | light | wide | yes | **no** (cycle 8) |
| harvester | implementer (executor class) | slow | high | baseline | yes | yes |
| defender | implementer (executor class) | slow | light | baseline | yes | yes |

The exact numbers are per-scenario (`arena show <id> --json` reports them); the
table above is the shape, not a single fixed board.

## explorer — reconnaissance / code-reading

The explorer ranges far and sees far. Its job is to read the board — the
software analog of reading an unfamiliar codebase before anyone writes a line —
and hand what it learns to the planner and the executors through the team's
message and plan channels. It deliberately **produces nothing directly**:

- `carry = 0` and `can_gather = False` — it cannot touch the economy. A
  `gather` order is rejected by the tick (`this role cannot gather resources`)
  and is absent from `legal_actions` (`gather: false`, `can_gather: false`).
- `can_capture = False` — **an explorer never counts as an occupant of a
  control point.** Its presence neither builds a capture streak nor contests
  another team's. An explorer standing alone on a point leaves it effectively
  unoccupied; an enemy explorer stepping onto a point you are capturing does
  *not* reset your streak. Capture is streak-based (there is no `capture`
  order), so this occupancy rule in the tick *is* the enforcement, and
  `legal_actions` mirrors it with `can_capture: false`.

Its edge is `move` and `vision`: strictly farther reach and sight than every
other role on its board, so it can map objectives no one else can see and get
back to report.

## planner — architect / tech-lead

The planner is **weak on the board by design**: `move = 1`, `carry = 0`,
baseline vision (no special sight), `can_gather = False`, `can_capture = False`.
Fielding one is a real tradeoff — that seat is not gathering, not holding, and
barely moving.

What the planner brings is coordination. It receives the explorer's intel and
hands instructions to teammates through the **existing** plan and message
channels (`plan_declared` / `message_sent` events) — no new engine mechanic is
needed for it to matter. The architect/tech-lead who writes no production code
this sprint but whose sequencing decides whether the team ships: that is the
planner. A team that cannot turn shared information into coordinated action
gains nothing from fielding one, which is exactly the point the arena is built
to measure.

## scout, harvester, defender — the executor class

The pre-existing roles are the **implementers** — they do the work the plan
calls for:

- **scout** — the original quick-reconnaissance role: fast, wide sight, light
  carry. It still gathers, carries, and delivers like any executor — but,
  as of cycle 8, it no longer holds ground (see the
  [Decision](#decision-the-scout-is-eyes-only-cycle-8) below): `can_capture
  = False`.
- **harvester** — hauls and delivers the payload: high carry, slow.
  `can_capture = True` (default) — unchanged.
- **defender** — captures and holds objectives: light carry, slow, steady.
  `can_capture = True` (default) — unchanged.

Through cycle 7, all three shared the same default capability contract
(`can_gather` and `can_capture` both `True`). The explorer and planner were a
**JOIN, not a replace** (plan risk r4): scout/harvester/defender kept their
exact stats and behaviour, existing scenarios' rosters were untouched, and the
committed determinism fixture stayed byte-identical. Cycle 8 (task t10) makes
one further, deliberate cut — described below — that touches the scout alone;
harvester and defender remain exactly as r4 pinned them.

## Where the roles are fielded

`skirmish-1` and `skirmish-2` field the original roster
(scout / harvester / defender), as does every seeded board the generator
(`league/engine/genscenario.py`) produces. `recon-1` is the first scenario to
field the coding-reflective roster: an **explorer** and a **planner** alongside
a **harvester** and a **defender** (the executors) — read, plan, execute.

## Decision: the scout is eyes-only (cycle 8)

**The grid scout can no longer capture control points.** `can_capture` flips
to `False` for the `scout` role everywhere it is fielded — `skirmish-1`,
`skirmish-2`, and every board `league/engine/genscenario.py` generates. A
scout's occupancy of a control point never builds or contests a capture
streak, exactly like the explorer and planner above; unlike them, the scout
keeps every other capability (`move`, `vision`, `can_gather`, `carry`,
`deliver`) untouched — only holding ground is withdrawn.

This closes a question cycle 7 explicitly parked: the continuous lane's own
eyes-only-scout amendment ("scouts should not be able to take posts — only be
the 'eyes'", a human-reviewed pre-publish decision, `can_take_post=False` on
`league/engine/continuous/roles.py`'s `CRoleStats`) was applied to the
continuous lane only, leaving the grid scout still capture-capable. Cycle 8
closes it, user-decided at the split-plan gate: **the grid scout becomes
eyes-only too.**

Rationale:

- **Parity with the continuous lane's eyes-only scout.** The cycle-7
  human-review amendment already settled that a scout's job is vision, not
  ground-holding; leaving the grid lane's scout capture-capable was an
  asymmetry between the two lanes with no principled reason behind it, not a
  considered design choice (two-lane honesty, spec c11/h11, permits the lanes
  to diverge *deliberately* — this was never that).
- **Cycle 8 gives the scout's value a legible measure that isn't capturing.**
  This cycle adds fog (vision-gated briefings) and per-unit role-purpose
  grades to the arena; a scout's contribution now shows up as *what it
  revealed* and *how well it did its role's actual job*, not as a bonus
  capture it happened to be standing near. Withdrawing capture removes the
  one capability that let a scout accidentally double as a defender.

**Mechanism (grid):** capture is streak-based, not a declared `capture` order
— a `can_capture=False` unit standing alone on a point simply never counts as
its occupant (`league/engine/tick.py` step 7, mirrored by
`league/engine/legal.py`'s `can_capture` flag and `league/cli/_commands/
arena.py`'s `no-capture` role note). Since there is no order to reject at
declaration time, the tick surfaces the impossibility explicitly instead of
silently: whenever a capture-incapable unit is the only thing standing between
its team and a streak, it emits an `action_rejected` event with reason `"this
role cannot capture control points"` — the same standard-failure-treatment
convention every other engine impossibility uses (`this role cannot gather
resources`, `target beyond this role's move range`, …), and the same shape as
the continuous lane's explicit `take_post` rejection for its own eyes-only
scout.

**Determinism-hash regeneration (documented, deliberate, pre-authorized):**
skirmish-1's canonical scripted match (`tests/test_determinism_gate.py`)
scripts the blue scout capturing `cp-east` — a real behavior this decision
removes. Flipping the rule regenerated `tests/fixtures/determinism.hash`; the
match still exercises capture, contest, and hold (blue's defender ends up
capturing `cp-center` instead, once the red scout that used to contest it no
longer counts as an occupant either) — see the commit that lands this task for
the before/after hash and the updated script commentary.

## Continuous-lane parity, in full

With this decision, the scout is eyes-only in **both** lanes, by the same
rationale, enforced by each lane's own mechanism:

- **Grid** — `league/engine/scenario.py`'s `RoleStats.can_capture=False`;
  enforced by `league/engine/tick.py`'s control-point occupancy filter (see
  above).
- **Continuous** — `league/engine/continuous/roles.py`'s `CRoleStats
  .can_take_post=False` (`take_post_duration=0`); enforced by
  `league/engine/continuous/legal.py` never offering `take_post` in the
  scout's menu, so a decision function can never even choose it. It keeps
  every other capability — move, vision (still widest among the continuous
  executor class), gather, carry, deliver — untouched.

The lanes remain free to diverge in mechanism (grid capture is occupancy/streak
based with no declared order; continuous `take_post` is a declared, timed
action a menu can simply omit) — spec c11/h11's "two-lane honesty" is about
never forcing one lane's implementation over the other's, not about
identical code paths. What converges here is the *rule*: a scout never holds
ground, in either lane. The actual fog-reducing "eyes" mechanic (narrowing
what *other* units can see) is a later cycle's continuous fog work — this
amendment only withdraws post-taking/capturing, it does not yet add fog. See
[`docs/continuous-contract.md`](continuous-contract.md) for the continuous
mind-facing contract this shows up in.
