"""One private 0700 test home under a shared ~/.local/state/bt/<name> root.

Several test modules share a root and each removes it once it is empty. Under
pytest-xdist another worker can remove the empty root between this worker's
root mkdir and child mkdir; recreate the root and try again.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path


def make_private_home(root: Path, prefix: str) -> Path:
    """Create and return ``root/<prefix>-<12 hex>`` (0700), the root 0700 too."""
    path = root / f"{prefix}-{uuid.uuid4().hex[:12]}"
    for _ in range(100):
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            path.mkdir(mode=0o700)
        except FileNotFoundError:
            continue  # another worker removed the empty root just now
        os.chmod(root, 0o700)
        return path
    raise RuntimeError(f"could not create a private test home under {root}")
