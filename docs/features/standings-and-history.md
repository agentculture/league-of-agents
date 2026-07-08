# Standings & history

Two read-only trend verbs turn the pile of recorded matches into a record you can
read at a glance. Both are computed **straight from the match logs** (the
queryable store, `league/store.py` + `league/track.py`), so they can never
disagree with what actually happened.

```bash
league standings          # per-team and per-agent trends
league standings --json
league history            # finished matches with both scores per team
league history --json
```

## `standings`

- **Per team** — win/loss/draw, outcome totals, cooperation averages, and trend.
- **Per agent** — matches played, wins, cooperation average, and orders
  declared vs rejected. This is where an individual agent's improvement over time
  shows up.

## `history`

Every finished match in id order, with both scores (outcome and cooperation) for
each team — the flat ledger behind the aggregates.

## Where aggregation lives (and doesn't)

Standings is deliberately the **only** place cross-match aggregation happens, and
it only ever aggregates *recorded results*. Single-match grading
([Scoring & grades](scoring-and-grades.md)) names an MVP/LVP per match and stops
there — there is no ELO or ranking system anywhere in the CLI. Trends come from
the record, not from a rating model.

## See also

- [Scoring & grades](scoring-and-grades.md) — the per-match axes these trends
  average.
- [Deterministic engine](deterministic-engine.md) — why log-derived trends are
  trustworthy.
