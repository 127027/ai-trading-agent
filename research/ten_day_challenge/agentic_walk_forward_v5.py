"""Current V5 entrypoint for contextual-signal ten-day research.

Implementation remains in the compatibility module agentic_walk_forward_v4 until
a later cleanup can remove the old filename without disturbing persisted results.
The active workflow must call this V5 entrypoint.
"""

from __future__ import annotations

from agentic_walk_forward_v4 import execute_one_run, main

__all__ = ["execute_one_run", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
