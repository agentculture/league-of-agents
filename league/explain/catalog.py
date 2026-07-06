"""Markdown catalog for ``league-of-agents explain <path>``.

Each entry is verbatim markdown. Keys are command-path tuples. The empty tuple
and ``("league-of-agents",)`` both resolve to the root entry.

Keep bodies self-contained: an agent reading one entry should get enough
context without chaining reads.
"""

from __future__ import annotations

_ROOT = """\
# league-of-agents

A clonable template for AgentCulture mesh agents. It carries an agent-first CLI
(cited from the teken `python-cli` reference), a mesh identity (`culture.yaml` +
`CLAUDE.md`), the canonical guildmaster skill kit under `.claude/skills/`, and a
buildable/deployable package baseline. Clone it, rename the package, edit
`culture.yaml`, and you have a new agent.

## Verbs

- `league-of-agents whoami` — identity probe from `culture.yaml`.
- `league-of-agents learn` — structured self-teaching prompt.
- `league-of-agents explain <path>` — markdown docs for any noun/verb.
- `league-of-agents overview` — descriptive snapshot of the agent.
- `league-of-agents doctor` — check the agent-identity invariants.
- `league-of-agents cli overview` — describe the CLI surface.

## Exit-code policy

- `0` success
- `1` user-input error
- `2` environment / setup error
- `3+` reserved

## See also

- `league-of-agents explain whoami`
- `league-of-agents explain doctor`
"""

_WHOAMI = """\
# league-of-agents whoami

Reports the agent's identity from `culture.yaml`: nick (`suffix`), backend,
served model, and the package version. Read-only.

## Usage

    league-of-agents whoami
    league-of-agents whoami --json
"""

_LEARN = """\
# league-of-agents learn

Prints a structured self-teaching prompt covering purpose, command map,
exit-code policy, `--json` support, and the `explain` pointer.

## Usage

    league-of-agents learn
    league-of-agents learn --json
"""

_EXPLAIN = """\
# league-of-agents explain <path>

Prints markdown documentation for any noun/verb path. Unlike `--help` (terse,
positional), `explain` is global and addressable by path.

## Usage

    league-of-agents explain league-of-agents
    league-of-agents explain whoami
    league-of-agents explain --json <path>
"""

_OVERVIEW = """\
# league-of-agents overview

Read-only descriptive snapshot of the agent: identity (from `culture.yaml`), the
verb surface, and the sibling-pattern artifacts the template carries. Accepts an
ignored `target` so a stray path never hard-fails.

## Usage

    league-of-agents overview
    league-of-agents overview --json
"""

_DOCTOR = """\
# league-of-agents doctor

Checks the agent-identity invariants `steward doctor` verifies:
prompt-file-present and backend-consistency (`colleague` → `AGENTS.colleague.md`), plus a
skills-present check. Exits 1 when unhealthy.

## Usage

    league-of-agents doctor
    league-of-agents doctor --json
"""

_CLI = """\
# league-of-agents cli

Noun group for CLI-surface introspection. `cli overview` describes the CLI
itself (distinct from the global `overview`, which describes the agent).

## Usage

    league-of-agents cli overview
    league-of-agents cli overview --json
"""


ENTRIES: dict[tuple[str, ...], str] = {
    (): _ROOT,
    # Both the console command (`league`) and the distribution/display name
    # (`league-of-agents`) resolve to the root entry, so `explain <self>` works
    # whichever name a caller reaches for. The rubric gate derives <self> from
    # `[project.scripts]` (= `league`) and checks `explain league` specifically.
    ("league",): _ROOT,
    ("league-of-agents",): _ROOT,
    ("whoami",): _WHOAMI,
    ("learn",): _LEARN,
    ("explain",): _EXPLAIN,
    ("overview",): _OVERVIEW,
    ("doctor",): _DOCTOR,
    ("cli",): _CLI,
    ("cli", "overview"): _CLI,
}
