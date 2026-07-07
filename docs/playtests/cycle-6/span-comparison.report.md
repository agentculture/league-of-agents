# Span of control — two minds command the same team (cycle-6 t9, spec c10/h10)

Two orchestrator-mode matches on the identical board (skirmish-2, fogged, seed
20260713, vs the greedy house bot): a **master mind commands three per-seat
sub-minds by message only** (`unit_comms` off). Same scenario, same seed, same
opponent — the only variable is the mind, measured by the p0 probe from log
evidence alone.

- **claude-sonnet-5** master + 3 sonnet seats (cloud, stateless per turn) —
  [`span-sonnet.log.jsonl`](span-sonnet.log.jsonl) ·
  [`probe`](span-sonnet.probe.json) · [`score`](span-sonnet.score.json)
- **colleague / Qwen3.6-27B** master + 3 colleague seats (local lobes, the
  work-loop harness) — [`span-colleague.log.jsonl`](span-colleague.log.jsonl) ·
  [`probe`](span-colleague.probe.json) · [`score`](span-colleague.score.json) ·
  [`config`](span-colleague.config.json)

## The comparison

| Axis | Sonnet orchestration | Colleague orchestration |
|------|---------------------|-------------------------|
| Outcome | **won 31–11** (t16) | **won 18–11** (t16) |
| Probe p0 score | **100** | 98 |
| — span_coverage | 3/3 | 3/3 |
| — realization_rate | 1.00 | 1.00 |
| — guidance_linkage | **1.00** | 0.92 |
| Cooperation v1 | 100 | 98 |
| Tempo raw median | 12,814 ms | 56,996 ms |
| Setup attempts needed | 1 | **3** (see below) |

Both minds fielded all three subagents with perfect realization — every seat
order resolved. The separating signals:

1. **Guidance linkage** — every sonnet master message named something a seat
   then did (1.00); the colleague master's guidance linked at 0.92 — a real,
   attributable gap in command precision, not a formatting artifact (the probe
   reuses v1's referent matcher).
2. **Outcome margin** — same seats-per-side, same board: sonnet's orchestration
   converted command into 31 points, colleague's into 18. Command quality, not
   span, is what separated them.
3. **The cost of commanding (the finding the numbers alone don't show):** the
   colleague master **failed twice at default configuration** — orchestration-
   sized work items burned the work loop's default 6 steps past a 420 s
   timeout while simple seat prompts converged in ~70 s. It succeeded only at
   `--max-steps 3` with a 900 s ceiling (this match: zero master idles). On
   this substrate, *commanding costs roughly 3× obeying* — span of control is
   bounded by the master's work-loop budget before it is bounded by
   intelligence. Recorded here rather than filed upstream because the tuned
   configuration works; the default-budget ergonomics are colleague feedback
   for when orchestration becomes a common colleague workload.

## Honesty notes

- Every number reconstructs from the committed logs:
  `league match probe <id> --json` and
  `league match score <id> --cooperation-version v1 --substrate <team>=<sub> --substrate house=bot --json`.
- The two failed colleague attempts are part of the record (this report), not
  erased; their matches were discarded pre-completion (master idle from turn 1
  — measuring a misconfiguration, not a mind).
- The colleague seats again shared a scratch workdir (the known cycle-5
  limitation, disclosed in
  [`colleague-coop.report.md`](../cycle-5/colleague-coop.report.md)); the
  per-seat workdir fix remains queued.
- Tempo medians are cross-substrate and the calibration baselines remain
  illustrative — compare within a column, not across
  ([`tempo methodology`](../../tempo-methodology.md)).
