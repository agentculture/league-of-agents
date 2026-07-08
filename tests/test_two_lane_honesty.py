"""Two-lane honesty — compat sweep, AST-ban coverage, scoring boundary
(plan task C7-t8, spec c10/h10/c11/h11).

The continuous lane lands *beside* the grid engine, not over it (spec c10):
every committed grid log still folds, the grid determinism gate is untouched,
and the extended AST import ban actually reaches the new package. None of
that is safe to claim from "no violation today" alone — a future re-layout
(continuous/ moved out from under league/engine/, or a new grid-only module
added beside scoring.py) could silently drop coverage or blur the boundary
without any existing test going red. This module makes each of those claims
an explicit, checkable assertion instead of an implicit one:

* :func:`test_ast_ban_walk_covers_the_continuous_package` proves the walk
  ``tests/test_engine_state.py::test_engine_never_imports_time_or_random``
  performs actually visits every continuous-package module by name — not
  just that today's continuous code happens to pass the ban.
* :func:`test_grid_scoring_axes_do_not_import_the_continuous_package` and
  :func:`test_continuous_package_does_not_import_grid_scoring_axes` are the
  two-lane boundary itself, enforced the same AST way the import ban already
  is: cooperation v1 (``scoring.py``), tempo t0 (``tempo.py``), and span
  probe p0 (``probe.py``) are grid-only and must never reach into
  ``league.engine.continuous``; the continuous resolver ports its own
  ``outcome_points``/``CP_POINTS`` (see ``league/engine/continuous/
  resolve.py``) rather than depending on the grid's scoring axes, and must
  never start doing so by accident.
* :func:`test_grid_determinism_fixture_is_untouched` and
  :func:`test_continuous_determinism_fixture_is_untouched` pin both committed
  hash fixtures to their exact recorded content, as a low-tech fence: this
  task's whole job is proving these are untouched, so a diff that touches
  either committed hash without a deliberate, documented regeneration (the
  same discipline ``tests/test_determinism_gate.py`` and
  ``tests/test_determinism_gate_continuous.py`` already document) shows up
  here as a failing test, not just a `git diff` a reviewer might miss.

The committed-log compat sweep itself already lives in
``tests/test_committed_logs_compat.py`` (cycle-6 t11) and needs no
duplication — it discovers every ``docs/playtests/**/*.log.jsonl`` by glob and
is part of the same green suite this task's acceptance criteria point at.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.test_engine_state import _BANNED_MODULES, ENGINE_DIR

CONTINUOUS_DIR = ENGINE_DIR / "continuous"

# The continuous package's own modules (plan tasks C7-t1..t7), named
# explicitly rather than discovered, so this list IS the coverage claim: if a
# future re-layout renames or moves any of these, this test fails loudly
# instead of silently shrinking the set the ban walks.
_EXPECTED_CONTINUOUS_MODULES = {
    "__init__.py",
    "space.py",
    "state.py",
    "events.py",
    "timeline.py",
    "roles.py",
    "legal.py",
    "resolve.py",
    "scenario.py",
}

# Grid-only scoring-axis modules (spec c11/h11): cooperation v1, tempo t0,
# span probe p0. None of them may reach into the continuous package.
_GRID_SCORING_MODULES = ("scoring.py", "tempo.py", "probe.py")

# The exact committed content of both determinism hash fixtures, recorded at
# the start of this task (verified byte-identical to HEAD via `git diff
# --stat` before this file was written). These two lines ARE the "do not
# touch" fence from the task brief: task C7-t8 must not regenerate either
# fixture, and if a later task legitimately needs to, both the fixture file
# AND this constant must change together in the same, documented commit —
# exactly the visibility the grid gate's own docstring already asks for.
#
# Cycle-8 t10 is exactly that later task: the grid scout's can_capture flips
# to False (docs/roles.md's Decision section), skirmish-1's canonical script
# in tests/test_determinism_gate.py genuinely resolves differently (blue's
# scout no longer captures cp-east; blue's defender captures cp-center
# instead once red's scout stops contesting it), so both the fixture and this
# constant move together here, in the same documented commit.
_GRID_DETERMINISM_HASH = "a4b2628bf5199db02ecdec88c80791d4fd9de93c1c808dc48c50c3ad58a92bca"
_CONTINUOUS_DETERMINISM_HASH = "96ae89c58d865b5973d1f15143114e221384880fce7c5356fd7d59d44312627d"


def _imported_module_roots(path: Path) -> set[str]:
    """Top-level module names a file imports, AST-parsed (no execution).

    Mirrors ``tests/test_engine_state.py::test_engine_never_imports_time_or_
    random``'s technique exactly: walk ``Import``/``ImportFrom`` nodes and
    take the first dotted component, so ``import league.engine.continuous``
    and ``from league.engine.continuous import Pos`` are both caught the
    same way regardless of import style.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
    return roots


def _imported_dotted_modules(path: Path) -> set[str]:
    """Every full dotted module path a file imports or imports *from*.

    Unlike :func:`_imported_module_roots` (which only needs the first
    component to check the engine-wide time/random ban), the two-lane
    boundary needs the FULL path — ``league.engine.scoring`` must be
    distinguished from ``league.engine`` itself, and ``league.engine.
    continuous`` from ``league.engine.continuous.legal``.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
                # `from league.engine import scoring` names the submodule as
                # an imported NAME, not as part of `node.module` — record
                # `<module>.<name>` too so that form is caught as well.
                modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_ast_ban_walk_covers_the_continuous_package() -> None:
    """The engine-wide import ban's walk actually visits every continuous
    module by name — proving coverage, not just today's clean result.

    ``tests/test_engine_state.py::test_engine_never_imports_time_or_random``
    scans ``ENGINE_DIR.rglob("*.py")``. This asserts that walk's discovered
    file set contains every module named in ``_EXPECTED_CONTINUOUS_MODULES``
    — so a future re-layout that moved ``continuous/`` out from under
    ``league/engine/`` (or excluded it some other way) would fail HERE,
    loudly, rather than the ban silently scanning fewer files than it claims
    to and reporting a false "no offenders".
    """
    assert CONTINUOUS_DIR.is_dir(), f"expected {CONTINUOUS_DIR} to exist as a subpackage"

    discovered = {p.relative_to(ENGINE_DIR) for p in ENGINE_DIR.rglob("*.py")}
    expected = {Path("continuous") / name for name in _EXPECTED_CONTINUOUS_MODULES}

    missing = expected - discovered
    assert not missing, (
        f"the AST ban's rglob walk over {ENGINE_DIR} no longer finds {sorted(map(str, missing))} "
        "— the continuous lane has silently fallen out of the determinism import-ban coverage"
    )


def test_grid_scoring_axes_do_not_import_the_continuous_package() -> None:
    """Cooperation v1 / tempo t0 / span probe p0 stay grid-only (spec c11/h11).

    These three modules score grid ``MatchLog``s only this cycle (the pinned
    decision in ``docs/continuous-contract.md``'s "Scoring: the two-lane
    decision" section). None may import ``league.engine.continuous`` or any
    of its submodules — if one starts to, that is silent scope creep into a
    lane whose adaptation was deliberately deferred, not a code review nit.
    """
    offenders: list[str] = []
    for name in _GRID_SCORING_MODULES:
        path = ENGINE_DIR / name
        for module in _imported_dotted_modules(path):
            if module == "league.engine.continuous" or module.startswith(
                "league.engine.continuous."
            ):
                offenders.append(f"{name}: {module}")
    assert not offenders, (
        f"grid-only scoring axis(es) reach into the continuous package: {offenders} — "
        "cooperation v1/tempo t0/probe p0 are pinned grid-only this cycle"
    )


def test_continuous_package_does_not_import_grid_scoring_axes() -> None:
    """The continuous resolver never depends on the grid's scoring axes.

    ``league/engine/continuous/resolve.py`` ports its own ``CP_POINTS``/
    ``outcome_points`` rather than importing the grid's — this asserts that
    independence holds for the whole package, not just resolve.py, and that
    it never imports ``scoring``/``tempo``/``probe`` via any import spelling
    (``import league.engine.scoring``, ``from league.engine import
    scoring``, or ``from league.engine.scoring import ...``).
    """
    grid_axis_stems = {name[: -len(".py")] for name in _GRID_SCORING_MODULES}
    offenders: list[str] = []
    for module_path in sorted(CONTINUOUS_DIR.rglob("*.py")):
        for module in _imported_dotted_modules(module_path):
            parts = module.split(".")
            if module in ("league.engine.scoring", "league.engine.tempo", "league.engine.probe"):
                offenders.append(f"{module_path.name}: {module}")
            elif (
                parts[:2] == ["league", "engine"]
                and len(parts) >= 3
                and parts[2] in grid_axis_stems
            ):
                offenders.append(f"{module_path.name}: {module}")
    assert not offenders, (
        f"the continuous package imports a grid-only scoring axis: {offenders} — "
        "league/engine/continuous/resolve.py ports its own outcome tally instead; "
        "it must stay that way (spec c11/h11 two-lane boundary)"
    )


def test_engine_time_random_ban_still_holds_over_the_whole_package() -> None:
    """Sanity companion to the coverage test above: re-run the same ban this
    module proved reaches the continuous package, directly over it.

    ``tests/test_engine_state.py`` already asserts this package-wide; this
    is a narrower, continuous-only re-statement so a reader of THIS file
    (about the continuous lane's honesty specifically) does not have to trust
    a different module's assertion to know the ban actually holds here.
    """
    offenders: list[str] = []
    for module in sorted(CONTINUOUS_DIR.rglob("*.py")):
        for name in _imported_module_roots(module):
            if name in _BANNED_MODULES:
                offenders.append(f"{module.name}: {name}")
    assert (
        not offenders
    ), f"banned nondeterministic imports in league/engine/continuous: {offenders}"


def test_grid_determinism_fixture_is_untouched() -> None:
    """The committed grid determinism hash is byte-identical to what this
    task started with — this task's whole acceptance criterion is that it
    stays that way.

    If this assertion ever needs to change, the grid engine's resolution
    rules changed on purpose (see ``tests/test_determinism_gate.py``'s own
    regeneration instructions) — that must be a deliberate, documented
    commit that updates the fixture AND this constant together, never a
    silent side effect of unrelated continuous-lane work.
    """
    fixture = Path(__file__).parent / "fixtures" / "determinism.hash"
    assert fixture.read_text(encoding="utf-8").strip() == _GRID_DETERMINISM_HASH, (
        "tests/fixtures/determinism.hash no longer matches the content this task started "
        "with — the grid determinism gate must stay untouched by the continuous lane's "
        "two-lane-honesty task"
    )


def test_continuous_determinism_fixture_is_untouched() -> None:
    """The committed continuous determinism hash (already pinned by C7-t6,
    and re-pinned after the scout amendment) is untouched by this task too.

    See ``tests/test_determinism_gate_continuous.py`` for the one deliberate,
    documented regeneration already on record (the scout eyes-only
    amendment). This task adds no new one.
    """
    fixture = Path(__file__).parent / "fixtures" / "determinism_continuous.hash"
    assert fixture.read_text(encoding="utf-8").strip() == _CONTINUOUS_DETERMINISM_HASH, (
        "tests/fixtures/determinism_continuous.hash no longer matches the content this task "
        "started with — task C7-t8 does not touch the continuous determinism gate"
    )
