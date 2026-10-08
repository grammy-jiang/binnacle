"""Bounded log-tail reads shared by core and companion diagnostics."""

import os
from pathlib import Path


def _tail_lines(path: Path, max_bytes: int = 512 * 1024) -> list[str]:
    """Last lines of a file, without reading all of it.

    The tunnel log runs to megabytes within a day; only the tail says
    anything about the poller's current state.
    """
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            raw = fh.read()
    except OSError:
        return []
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    # A partial first line is likely when we seek into the middle.
    return lines[1:] if size > max_bytes and lines else lines
