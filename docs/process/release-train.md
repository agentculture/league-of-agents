# The release train — stacked PRs, and the lessons they cost

League of Agents ships every merge to `main` as a real version (spec
requirement c9/h5): no batching, no "release later." That works cleanly for a
single PR opened against `main`. It gets expensive when PRs are **stacked** —
branch B forked from branch A before A merged — because the whole point of a
stack is to build on code that does not exist on `main` yet. This document
records what actually happened the one time this repo ran a long stack, not
idealized advice: the 2026-07-07 cycle-2/3/4 train, PRs #4 through #10. Every
claim below is checked against `git log`/`gh pr view` on this repo; where a
detail could not be reproduced from the log, it is left out rather than
guessed at.

## The train (2026-07-07, all same-day merges)

| Order | PR | Branch | Merged (UTC) | Version landed | Forked from |
|-------|----|--------|--------------|-----------------|-------------|
| 1 | [#4](https://github.com/agentculture/league-of-agents/pull/4) | `spec/arena-season-0` | 09:05:56 | 0.5.0 | `main` |
| 2 | [#5](https://github.com/agentculture/league-of-agents/pull/5) | `feat/season-0-arena` | 09:08:19 | 0.6.0 | #4 |
| 3 | [#9](https://github.com/agentculture/league-of-agents/pull/9) | `feat/season-0-playtests` | 09:18:12 | 0.7.0 | #5 |
| 4 | [#6](https://github.com/agentculture/league-of-agents/pull/6) | `spec/resident-minds` | 09:20:59 | 0.7.0 → **0.7.1** (collision) | #9 |
| 5 | [#7](https://github.com/agentculture/league-of-agents/pull/7) | `spec/fog-agentfront-draft` | 09:23:49 | **0.7.2** (folded, see below) | #6 |
| 6 | [#8](https://github.com/agentculture/league-of-agents/pull/8) | `spec/single-player-tempo` | 09:25:36 | 0.7.3 | #7 |
| 7 | [#10](https://github.com/agentculture/league-of-agents/pull/10) | `feat/resident-minds-fog` | 09:31:20 | 0.8.0 | #7 (parallel to #8, not chained after it) |

Each PR's own description says what it forked from (`gh pr view <n> --json
body`) — that is how the chain above is reconstructed, not guesswork. Notably,
PR #10, the workforce implementation PR for cycles 2+3, forked from #7's
branch **in parallel with #8**, not after it — its restack (below) is the
messiest of the seven because of that.

## Failure mode 1 — squash merge destroys shared history

Every PR here merges via **squash**: the whole branch collapses into one new
commit on `main`. That is fine for the PR that just merged. It is not fine for
every PR still stacked behind it — their branch history still contains the
*original*, unsquashed commits of the PR that just landed, and those commits
are no longer reachable from `main` at all. GitHub reports the downstream PRs
as `CONFLICTING` (add/add conflicts on files both sides technically "added,"
since neither side has a common ancestor for that content anymore).

The remedy used every time: merge `main` into the downstream branch, resolve
by hand, push. The push matters for a second reason beyond fixing
mergeability — it fires a new `synchronize` event, which is what re-runs CI on
the PR. `.github/workflows/tests.yml` triggers on `pull_request: branches:
[main]`, a filter every PR here already satisfies; the restack push is what
gets a green run against the *post-squash* diff rather than a stale one.

## Failure mode 2 — two PRs claim the same version

PRs #9 and #6 both forked before the other had bumped, so both independently
bumped `pyproject.toml` to `0.7.0`. PR #9 merged first and became the real
`0.7.0`. When #6 restacked (`merge main (squashed #4+#5+#9) — restack
resident-minds spec onto main`), CI's version-check compared #6's branch
against the new `main` and failed: same version, already taken. The fix was a
dedicated commit — `chore: re-bump 0.7.0 -> 0.7.1 (version collision with #9
as the train advances) + regenerate uv.lock` — landing #6 as `0.7.1` instead.
PR #9's own description had already flagged the risk in advance — its body
notes: *"stacked spec PRs #6–#8 will need version re-bumps as bases merge (CI
version-check compares against main)"* — the prediction held.

**Lesson:** in a stack, a version number is only real once its PR has merged.
Bumping independently in every stacked branch guarantees a collision the
moment two branches fork from the same unbumped base.

## Failure mode 3 — duplicate CHANGELOG entries for the same version number

This is failure mode 2's sibling, one layer down. PR #7's branch, forked from
PR #6 *before* PR #6's own restack/re-bump, carried its own `## [0.7.1]` entry
("Parked cycle-3 spec draft: ...") with a differently-worded `0.7.1` Cycle-2
entry underneath it (`"one persistent **cultureagent-anchored** session per seat"`)
inherited from before PR #6 rewrote its own entry. By the time PR #7 restacked
against real `main`, `main` already had its own, differently worded, canonical
`## [0.7.1]` (`"one persistent session per seat"`, from the merged PR #6). Two
entries, same version number, different prose — an unresolvable change
conflict, not a mechanical one. The resolution
(`merge main (train through #6) — restack fog-agentfront spec onto main`)
kept main's real `0.7.1` untouched and turned PR #7's own parked-then-converged
content into the next version instead: `## [0.7.2]`, heading changed from
`### Changed` to `### Added`, wording rewritten from the draft/parked framing
to the converged one. The published 0.7.2 entry is that reconciliation, not
the original draft text.

**Lesson:** one CHANGELOG entry per version, decided once, at the point the
version is confirmed as landing — not drafted independently in every branch
that happens to touch that version number.

## Failure mode 4 — uv.lock drift on every bump

Every version bump edits `pyproject.toml`'s `version` field but leaves
`uv.lock`'s embedded package-version entry stale unless `uv lock` is run
afterward. This actually surfaced as **Qodo review findings on both PR #6 and
PR #7** (`uv.lock still records the editable root package` at the old
version), each fixed by a dedicated commit
(`chore: re-bump 0.7.0 -> 0.7.1 ... + regenerate uv.lock` on PR #6;
`chore: regenerate uv.lock after restack (embedded version -> 0.7.2)` on
PR #7). `uv.lock` also shows up in the conflict list of every single restack
merge in this train (PR #6, #7, #8, #10) — a version bump plus a
restack is two independent reasons for `uv.lock` to need regenerating, and
missing either one leaves the lockfile internally inconsistent with
`pyproject.toml` (CI's `uv sync` reads the lock, not the toml).

**Lesson:** treat `uv lock` as mandatory after *both* a version bump and a
restack merge, not just the bump — check `uv.lock`'s own diff, not only
`pyproject.toml`'s.

## Techniques that made the restacks tractable

- **Fork-point superset proof.** When a restack's conflict list is long but
  the branch already contains everything `main` has (because an earlier
  restack already merged it in), most of those "conflicts" resolve to no
  actual change. #10's final restack
  (`merge main (train through #8) — restack resident-minds-fog onto main`)
  listed seven conflicting paths (`CHANGELOG.md`, `CLAUDE.md`,
  `league/harness.py`, `league/replay/html.py`, `pyproject.toml`,
  `tests/test_replay_html.py`, `uv.lock`) but its actual net diff touched only
  two: `CHANGELOG.md` and `uv.lock`. The other five were already identical to
  `main` on that branch — proof that accepting the branch's own side (or
  `origin/main`'s, whichever already matches) was safe for them, rather than
  hand-resolving five files that had no real divergence left.
- **Two-step restack for a branch that diverged before any squash.** #10 was
  the hard case: its branch was forked before *any* PR in the train had
  squash-merged, so by the time it was ready, its own git history still had
  the raw, unsquashed commits of #4/#5/#9 baked in — a real 3-way merge, not a
  mechanical one. The fix was two separate merges rather than one: first
  `merge playtests tip 248dd6f — port PR #9 review fixes (bfcb4d8) into
  resident-minds-fog` (reconciling against the *actual pre-squash* tip of the
  season-0-playtests branch, which gave git a genuine common ancestor and
  pulled in real content: harness/replay/driver fixes, the playtest reports),
  and only then `merge main (train through #8)` (which, per the fork-point
  proof above, mostly resolved to metadata). Reconciling against the real
  pre-squash branch tip first, before reconciling against the squashed `main`,
  turned an intractable diff into two ordinary ones.

## The rule going forward: one version bump, at the train's front

The train worked despite these failures, but the fixes were all reactive. The
rule this earns: **if PRs are going to be stacked, bump the version exactly
once, in the first PR of the stack** — not independently in every PR that
happens to touch `pyproject.toml`/`CHANGELOG.md`. Every PR behind the front
inherits that bump through its restack merge, the same way it inherits any
other change on `main`. Bumping independently in every stacked branch is what
produced both the version collision (failure mode 2) and the duplicate
CHANGELOG entry (failure mode 3) — both are the same root cause wearing
different clothes.

If a stacked PR *does* need its own bump (because the train's front already
landed and this branch is genuinely the next version), expect to re-bump at
every restack until the branch actually merges — the version this branch
"is" keeps changing until it lands.

## The alternative: don't stack unless the work genuinely depends on it

The cleanest PR in this whole story is [#11](https://github.com/agentculture/league-of-agents/pull/11)
(cycle-5 spec + build plans for cycles 4 and 5, `0.8.1`) — branched directly
from `main` after the train had fully landed, two commits, one version bump,
no restack, no collision. That is the default this repo should reach for:
branch each PR from `main` and merge serially. Stack only when a task
genuinely cannot be built without code that is sitting in another PR that
has not merged yet (as with #10's workforce implementation needing #6/#7's
converged specs to build against) — and even then, expect the restack tax
this document describes.

## The confirmed decision: publish cadence stays per-merge

This is the standing decision the process above operates under, not something
this document is proposing: **every merge to `main` that touches
`pyproject.toml` or `league/**` auto-publishes to PyPI via Trusted Publishing**
(`.github/workflows/publish.yml`). User decision, 2026-07-07 (spec suggestion
5b, resolved) — continuous releases match the recursive spec → plan →
implement → live-test cycle, and each version is a green-CI snapshot rather
than a batched release. No workflow change follows from this document; the
failure modes above are about the *mechanics* of landing a stacked train
under that cadence, not about whether the cadence itself should change.

## See also

- [`docs/process/cycle.md`](cycle.md) — the spec → plan → implement →
  live-test loop this train's PRs were implementing (waves 0-5 across
  cycles 2 and 3, plus the cycle-4/5 specs).
- `docs/specs/2026-07-07-league-of-agents-hardens-the-arena-the-pending-liv.md`
  (requirement c9, honesty h5) — the spec this document fulfills.
