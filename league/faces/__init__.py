"""``league.faces`` — audience-typed projections of the match fold, on agentfront.

This package is where league adopts **agentfront** as a runtime dependency
(user decision c17, cycle 3): the org's one-registry runtime — formerly teken,
already this repo's dev-only rubric gate — becomes the substrate the faces are
declared on. Agents read markdown; ``league match brief`` is the markdown
face, and its ``--json`` twin is the same facts, because both come from ONE
declaration in the registry built here.

What of agentfront is actually used, and why
--------------------------------------------

* ``agentfront.App`` — as the **faces registry**, not as the CLI. League's
  argparse CLI stays exactly as it is this cycle (risk r2: an honest, minimal
  integration, not a big-bang migration). :func:`faces_app` builds an ``App``
  and registers the brief projection once with ``@app.tool`` under the path
  ``("match", "brief")``; the ``league match brief`` verb *resolves that
  registry entry* (``app.get_by_path``) and serves it — markdown via
  :func:`render_brief_markdown`, facts via ``--json``. The registry is the
  single source of truth: a projection not registered here cannot appear on
  any face, and the face-agreement tests (``tests/test_faces.py``) prove the
  two renderings are fact-for-fact one fold.
* ``agentfront.testing.assert_surfaces_agree`` — in the test suite, agentfront's
  own cross-surface gate runs against :func:`faces_app`, so the registry/CLI/
  MCP/HTTP inventories of the faces app provably cannot drift (h1).

Growth path (deliberately NOT shipped this cycle, spec boundary c15: no
server/daemon lands): because the projection is a registered agentfront tool,
``faces_app().http_app()`` (WSGI markdown site) and ``faces_app().mcp_server()``
(MCP tools, needs the ``agentfront[mcp]`` extra) already derive the same brief
from the same registry for free — turning them on is a one-line surface call
when a future cycle picks live spectating up.

Isolation: this package is the ONLY league code that imports agentfront. The
engine (``league/engine/``) stays dependency-free and deterministic — enforced
by ``tests/test_faces.py::test_agentfront_is_imported_only_by_the_faces_layer``
alongside the engine's own AST import ban. agentfront's CLI/HTTP surfaces are
stdlib-pure, so the runtime install gains no transitive third-party deps.
"""

from __future__ import annotations

from typing import Any

from agentfront import App

from league import __version__
from league.faces.brief import brief_facts, render_brief_markdown
from league.store import Store

__all__ = ["brief_facts", "faces_app", "render_brief_markdown"]

_FACES_DOC = """\
# league faces

Audience-typed projections of one match fold: markdown for agents (the
`league match brief` verb), JSON for coded bots (`--json` — the same facts),
HTML for humans (`league match replay`). The brief projection is declared once
in this registry; every face renders that declaration, so faces cannot drift.

## match brief

    league match brief <match-id>            # markdown, full board
    league match brief <match-id> --team X   # markdown, fogged: what X knows
    league match brief <match-id> --json     # the same facts as JSON

The fogged variant renders the per-team knowledge fold (seen/told facts from
`league.engine.knowledge`), never ground truth, and never scores or opponent
resources.
"""


def faces_app(store: Store | None = None) -> App:
    """Build the faces registry: one ``App``, the brief projection declared once.

    ``store`` defaults to the CWD arena store (matching every other league
    verb); tests may inject their own.
    """
    app = App(
        name="league-faces",
        version=__version__,
        description="Audience-typed projections of the league match fold.",
    )
    app.add_doc(slug="faces", title="league faces", text=_FACES_DOC)

    @app.tool(
        group=("match",),
        name="brief",
        description=(
            "One-fold match briefing: facts for a match id (fogged to one team's "
            "knowledge when team is given). The markdown face is "
            "render_brief_markdown(facts); --json is the facts themselves."
        ),
    )
    def brief(match_id: str, team: str = "") -> dict[str, Any]:
        """Project a match log to briefing facts (fogged when ``team`` is given)."""
        arena = store if store is not None else Store()
        return brief_facts(arena.load_match(match_id), team=team or None)

    return app
