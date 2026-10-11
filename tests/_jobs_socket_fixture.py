"""Test-owned jobs-socket default for hosts whose composition leaves it unset.

Host composition resolves ``jobs.socket_path`` on Linux only; elsewhere
``binnacle.features.commands.jobs`` refuses to import without one. Collection
imports that module (via test modules) before any fixture runs, so the default
has to exist before the settings are first composed. It is a per-session
temporary path, never a production runtime location, and an explicit
``BINNACLE_JOBS__SOCKET_PATH`` always wins.
"""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

_ENV = "BINNACLE_JOBS__SOCKET_PATH"
_ROOT: Path | None = None


def session_socket_root() -> Path | None:
    """Return the temp dir holding the test-owned socket, if one was created."""
    return _ROOT


def ensure_test_jobs_socket() -> None:
    """Point unresolved jobs-socket settings at a session temp path on Darwin."""
    global _ROOT
    if sys.platform != "darwin" or os.environ.get(_ENV) or _ROOT is not None:
        return
    # AF_UNIX paths are short on macOS; keep it directly under the temp root.
    _ROOT = Path(tempfile.mkdtemp(prefix="r4-it-")).resolve()
    atexit.register(shutil.rmtree, _ROOT, ignore_errors=True)
    os.environ[_ENV] = str(_ROOT / "jobs.sock")
