"""Thin Darwin manager entry: no business import at module load.

The launchd -m source entry guards the full pinned module import set BEFORE
service classes load, then calls this main after verified imports complete.
"""

from __future__ import annotations

from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Enter the real Darwin manager after the early import guard."""
    from binnacle.platform.darwin.job_manager_entry import main as serve_main

    return serve_main(argv)
