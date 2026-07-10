#!/usr/bin/env python3
"""DEPRECATED thin wrapper -- use ``league cmatch run`` instead (issue #28).

The continuous lane shipped as a library-only call for cycle 7
(``league.charness.run_cmatch``): this script was the only operator entry
that reached it from a shell, since the CLI noun group was deliberately
deferred. That gap is closed -- ``league cmatch run --config <file> --apply``
is now a real published verb (part of the wheel, unlike this script), with
siblings (``cmatch new``/``show``/``act``/``tick``) for driving a match
one decision at a time instead of only ever running it start-to-finish in one
call. This script is kept only so an existing ``python3 scripts/run_cmatch.py
<config.json>`` invocation keeps working; it now does nothing but call the
CLI and print its JSON result.

Usage:  python3 scripts/run_cmatch.py <config.json>
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from league.cli import main as _cli_main  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: run_cmatch.py <config.json>", file=sys.stderr)
        return 1
    print(
        "scripts/run_cmatch.py is deprecated -- use "
        "'league cmatch run --config <file> --apply --json' directly",
        file=sys.stderr,
    )
    return _cli_main(["cmatch", "run", "--config", sys.argv[1], "--apply", "--json"])


if __name__ == "__main__":
    raise SystemExit(main())
