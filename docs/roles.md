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
| scout | quick reconnaissance pass | fast | light | wide | yes | yes |
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
calls for, and their capability contract is the default (`can_gather` and
`can_capture` both `True`):

- **scout** — the original quick-reconnaissance role: fast, wide sight, light
  carry. It can still gather and hold, unlike the explorer.
- **harvester** — hauls and delivers the payload: high carry, slow.
- **defender** — captures and holds objectives: light carry, slow, steady.

These roles are unchanged by the coding-reflective additions. The explorer and
planner are a **JOIN, not a replace** (plan risk r4): scout/harvester/defender
keep their exact stats and behaviour, existing scenarios' rosters are untouched,
and the committed determinism fixture stays byte-identical.

## Where the roles are fielded

`skirmish-1` and `skirmish-2` field the original roster
(scout / harvester / defender). `recon-1` is the first scenario to field the
coding-reflective roster: an **explorer** and a **planner** alongside a
**harvester** and a **defender** (the executors) — read, plan, execute.

## Continuous-lane divergence: scout

Everything above describes the **grid** lane (`league/engine/scenario.py`'s
`RoleStats`, `can_capture`) — grid scout is **unchanged**: it still gathers and
holds exactly as described above. The two lanes are allowed to diverge (spec
c11/h11, "two-lane honesty": the continuous lane sits *beside* the grid, never
over it), and cycle 7 exercised that: a human-reviewed pre-publish decision on
the continuous lane's still-unpublished season ("scouts should not be able to
take posts — only be the 'eyes'") forbids the continuous scout from
`take_post` (`league/engine/continuous/roles.py`'s `CRoleStats`,
`can_take_post=False`, `take_post_duration=0`). It keeps every other
capability — move, vision (still widest among the continuous executor class),
gather, carry, deliver — untouched; only holding a control point is withdrawn.
The actual fog-reducing "eyes" mechanic (narrowing what *other* units can see)
is a later cycle's continuous fog work — this amendment only withdraws
post-taking, it does not yet add fog. See
[`docs/continuous-contract.md`](continuous-contract.md) for the continuous
mind-facing contract this shows up in.
