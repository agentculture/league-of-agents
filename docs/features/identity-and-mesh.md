# Identity & mesh

League of Agents is also a **live AgentCulture mesh agent**. Its identity is
declared once in [`culture.yaml`](../../culture.yaml) and checked by invariants,
so "who is this agent?" always has one authoritative answer.

## `culture.yaml` declares the agent

The file declares this agent to the AgentCulture IRC mesh: a `suffix`
(`league-of-agents`, the mesh nick), a `backend` (`colleague`), and a pinned
`model`. Because the backend is **`colleague`, not `claude`**, the resident mesh
prompt the daemon reads is **`AGENTS.colleague.md`** — `CLAUDE.md` is for Claude
Code operating the repo interactively, not for the mesh daemon. This
backend → prompt-file mapping is load-bearing and must stay in sync.

## Identity is always *this* agent's own

`league/cli/_commands/whoami.py` parses `culture.yaml` **without a YAML
dependency** (a hand-rolled scan of the first agent block) and locates the file by
walking up from `__file__` — so identity is always this agent's own, never
whatever `culture.yaml` happens to sit in the caller's working directory. A wheel
install with no bundled `culture.yaml` falls back to literal defaults.

```bash
league whoami          # nick, backend, served model, package version
league whoami --json
```

## The `doctor` invariants

`league doctor` mirrors the invariants `steward doctor` checks across the mesh:

- **prompt-file-present** — the declared backend's prompt file exists.
- **backend-consistency** — `colleague` maps to `AGENTS.colleague.md`; change the
  declared backend and you must teach `doctor` the matching prompt file.
- **skills-present** — the vendored skill kit is in place.

It exits non-zero when unhealthy, so CI and operators get a single health signal.

## The skill kit (cite-don't-import)

`.claude/skills/` carries a vendored, **cite-don't-import** skill kit — copies the
repo owns, not a dependency. Most skills come from *guildmaster*; a few originate
in *devague*, *colleague*, and *eidetic-cli*. Every vendored `SKILL.md` must carry
`type: command` in its frontmatter or the culture backend silently skips it.
Provenance and the re-sync procedure are in
[`docs/skill-sources.md`](../skill-sources.md).

## See also

- [Agent-first CLI](agent-first-cli.md) — `whoami`/`doctor` are introspection
  verbs on the same surface.
