"""Entry point for ``python -m league``."""

from __future__ import annotations

import sys

from league.cli import main

if __name__ == "__main__":
    sys.exit(main())
