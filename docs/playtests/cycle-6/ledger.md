# Cycle-6 closure ledger (t12, spec c1/h7 · c3/h9)

Every thread of the cycle-6 announcement, mapped to its committed artifact and
the audience it serves. Nothing below is claimed without a pointer.

| Announcement thread | Artifact on main | Audience served |
|--------------------|------------------|-----------------|
| Mesmerizing replays, designed | `league/replay/html.py` redesign + [`docs/replay-design.md`](../../replay-design.md) (validated palette, both themes, motion) — PR #16 | The human evaluator |
| …with a built-in judge's guide | The embedded assessor guide (log-derived, per-scenario) + the first [human review](human-review.md) conducted through it — *"amazing and helps a lot"*, plus 7 recorded findings | The human evaluator (h6 closed: design checks AND a recorded review) |
| Any match exports to shareable video | `league match record` (pure-stdlib GIF, provenance embedded) + [`memory-longhorizon.gif`](memory-longhorizon.gif), shared live during review | The human evaluator, sharing |
| Seeded generation from skirmish to campaign | `league/engine/genscenario.py` (`gen-<seed>-…`, symmetry-proven, 41×41/200-turn/`executor_scale` knobs) + the [memory playtest](memory-longhorizon.report.md) played live on `gen-777-w21y17t60c2r2m2k2` | Researchers (long-horizon, memory) |
| Coding-shaped roles | explorer/planner in `recon-1`, engine-enforced capabilities, [`docs/roles.md`](../../roles.md) | Agent developers |
| …and the subagent chains they command, measured | `league match probe` (p0, evidence-hierarchy, self-report scores zero) + the [two-mind span comparison](span-comparison.report.md) (sonnet 100 vs colleague 98 on the same board) | Agent developers, researchers |

## The plan's 12 tasks

t1 generator · t2 scale knobs · t3 roles · t4 replay overhaul · t5 assessor
guide · t6 video export · t7 probe · t11 compat sweep — merged in
[PR #16](https://github.com/agentculture/league-of-agents/pull/16) (code,
0.10.0). t8 [memory playtest](memory-longhorizon.report.md) ·
t9 [span comparison](span-comparison.report.md) ·
t10 [human review](human-review.md) · t12 this ledger — this closure PR.

## What the cycle learned (already feeding forward)

- **Residency is a 6.5× tempo lever** (t8) — the resident-vs-stateless
  benchmark row is queued.
- **Commanding costs ~3× obeying on the colleague substrate** (t9) — span of
  control is budget-bounded before intelligence-bounded.
- **The reviewer judges one level deeper than the guide teaches** (t10) —
  MVP/LVP per-unit grades are the remedy, seeded for cycle 8 with delivery
  lockdown, eyes-only scouts (constraint already applied to the in-flight
  cycle-7 lane by user directive), and continuous-fog scout work.
- The first human review also redirected the visual system live
  (cream/black-green themes, continuous motion, tabbed guide) — the
  `feat/replay-theme-restyle` branch.
