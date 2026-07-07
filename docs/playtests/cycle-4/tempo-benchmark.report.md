# Tempo benchmark — three minds, one board (cycle-4 t8, spec c4/h4)

Three solo minds played the identical board (skirmish-1, seed 20260710, mode
competitive) against the identical opponent (`bots/rusher.py`, the named silver
house strategy), each under the one-action-per-turn solo handicap. Same map,
same missions, same enemy — every difference below is the mind, its harness,
and its substrate.

- **claude-sonnet-5** (cloud) — the `claude` CLI, one fresh session per turn.
  [`solo-vs-bot.log.jsonl`](solo-vs-bot.log.jsonl) (the preset-launched
  playtest, [report](solo-vs-bot.report.md))
- **claude-haiku-4-5** (cloud) — same harness, smaller model.
  [`bench-haiku.log.jsonl`](bench-haiku.log.jsonl) ·
  [`bench-haiku.score.json`](bench-haiku.score.json)
- **colleague / Qwen3.6-27B** (local, lobes vLLM) — fielded through its own
  agent harness (`scripts/colleague_driver.py`, the work-loop — field agents,
  not raw chat/completions).
  [`bench-colleague.log.jsonl`](bench-colleague.log.jsonl) ·
  [`bench-colleague.score.json`](bench-colleague.score.json)

## The table (raw always beside converted — spec h4)

| Axis | Sonnet (cloud) | Haiku (cloud) | Colleague Qwen (local) |
|------|---------------|---------------|------------------------|
| Outcome | **26–2**, won t25 | **26–2**, won t24 | **14–2**, turn limit |
| ms-outpost / ms-supply | t10 / t25 | t17 / t24 | t12 / — (incomplete) |
| Rejected orders | 0 | 0 | 0 |
| Cooperation v1 | 77 | 50 | 69 |
| — message_utility | 0.89 (33/37) | 0.12 (2/17) | 0.68 (23/34) |
| — plan_fidelity | 1.00 (25/25) | 0.79 (19/24) | 0.93 (28/30) |
| Raw latency, median | 64,740 ms | 57,906 ms | **73,074 ms** |
| Raw latency, p95 | 124,293 ms | 124,856 ms | 301,897 ms |
| Converted tempo (t0) | 31 (baseline 20 s) | 35 (baseline 20 s) | **274** (baseline 200 s) |

## Findings

1. **The conversion mechanism works; the seed baselines don't.** The local
   mind has the *slowest* raw median of the three yet the *highest* converted
   tempo by ~8×, because `DEFAULT_CALIBRATION`'s illustrative local baseline
   (200 s) flatters a 73 s reality. This is the exact failure mode
   [`docs/tempo-methodology.md`](../../tempo-methodology.md) declares
   ("baselines are declared, not measured") — now demonstrated on real data,
   caught only because raw sits beside converted (h4 doing its job). The
   rationale-survives-its-own-test condition (spec h8) is hereby exercised:
   **the conversion as seeded misleads; a measured calibration run must
   replace the illustrative constants before converted tempo is used for
   cross-substrate ranking.** Until then, same-substrate comparison (Sonnet vs
   Haiku: 31 vs 35 on identical baselines) is the only honest converted read.
2. **Outcome separates the local mind; cooperation separates the cloud ones.**
   Sonnet and Haiku are indistinguishable on outcome (26–2 on the same board)
   but 27 points apart on cooperation v1 — Haiku writes terse, unverifiable
   coordination notes (2/17 messages carry a checkable referent vs Sonnet's
   33/37). Colleague sits between them on cooperation (69, with genuinely
   referent-rich messages) but paid an outcome price: its median turn is ~13%
   slower than Sonnet's and it banked only 4 of 6 deliveries before the
   turn-30 ceiling. Tempo is not cosmetic — on this board it is worth 12
   outcome points.
3. **Load condition, declared:** the colleague measurements were taken while a
   second colleague match (the cooperative run) shared the same vLLM instance
   and machine; its p95 (302 s) includes that contention. Raw numbers are
   published as measured under that condition. The cloud runs were also
   partially concurrent with each other and with local inference on this
   machine.
4. Every number above reconstructs from the committed logs alone:
   `league match score <id> --cooperation-version v1 --substrate solo=<cloud|local> --substrate house=bot --json`
   (haiku/colleague configs committed beside the logs; the sonnet run was
   preset-launched).

## What this feeds

- The measured-calibration run is the natural cycle-6+ follow-up (the
  methodology doc's own "until a real calibration run exists" caveat).
- The same-mind-two-substrates row (spec h4's strongest form) stays open until
  a mind actually runs on two substrates — the closest available pair today is
  Qwen-on-lobes vs Qwen-on-cloud, not yet fielded.
