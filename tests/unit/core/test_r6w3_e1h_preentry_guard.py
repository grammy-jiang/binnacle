"""R6W3-01: source import faults must be guarded at the real process entry.

Each test uses a new isolated subprocess and a deliberately failing import
finder. No real MCP port, manager IPC socket, production service, or worktree
is started. A raw pre-guard exception fails the test.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest

ROOT = Path.home() / ".local/state/bt/e1h"
DRIVER = textwrap.dedent(
    """
    import importlib.abc, os, runpy, sys

    entry, target = sys.argv[1:]
    class BrokenRequiredModule(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == REQUIRED:
                raise SyntaxError("sensitive_external_text")
            return None

    REQUIRED = target
    sys.meta_path.insert(0, BrokenRequiredModule())
    sys.argv = ["guarded-entry"]
    if entry == "server":
        from binnacle.startup_imports import serving_entry
        with serving_entry():
            import binnacle.server
    elif entry == "server-console":
        sys.argv = ["binnacle", "serve"]
        from binnacle.entrypoint import main
        main()
    elif entry == "linux-console":
        from binnacle.job_manager_cli import main
        main()
    elif entry == "darwin-module":
        runpy.run_module(
            "binnacle.platform.darwin.job_manager_service",
            run_name="__main__", alter_sys=True,
        )
    elif entry == "linux-module":
        runpy.run_module(
            "binnacle.features.commands.job_manager",
            run_name="__main__", alter_sys=True,
        )
    else:
        raise AssertionError("unknown test entry")
    raise AssertionError("required import error did not abort before entry")
    """
)
CASES = (
    ("server", "binnacle.features.commands.commands_server", "mcp-server"),
    ("server-console", "binnacle.features.commands.commands_server", "mcp-server"),
    ("server-console", "binnacle.cli", "mcp-server"),
    ("linux-console", "binnacle.features.commands.job_store", "job-manager"),
    ("linux-module", "binnacle.features.commands.job_store", "job-manager"),
    ("darwin-module", "binnacle.platform.darwin.job_manager_records", "job-manager"),
)


@pytest.mark.parametrize(("entry", "missing", "process"), CASES)
def test_real_entry_guards_initial_required_imports(entry, missing, process):
    if entry == "linux-module" and sys.platform != "linux":
        pytest.skip("Linux-only -m entry (Darwin uses a separate service)")
    if entry == "darwin-module" and sys.platform != "darwin":
        pytest.skip("Darwin service launch entry")
    state = ROOT / f"p-{uuid.uuid4().hex[:14]}"
    state.mkdir(parents=True, mode=0o700)
    try:
        config = state / "config.toml"
        config.write_text(
            f'[jobs]\ndir = "{state / "jobs"}"\n'
            f'socket_path = "{state / "manager.sock"}"\nowner = "embedded"\n',
            encoding="utf-8",
        )
        env = {k: v for k, v in os.environ.items() if not k.startswith("BINNACLE_")}
        env.update(BINNACLE_CONFIG_FILE=str(config), XDG_STATE_HOME=str(state / "xdg"))
        child = subprocess.run(
            [sys.executable, "-c", DRIVER, entry, missing],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        output = child.stdout + child.stderr
        assert child.returncode == 70, output[-1500:]
        assert "event=startup_import_failed" in output, output[-1500:]
        assert "error_class=SyntaxError" in output, output[-1500:]
        assert "sensitive_external_text" not in output
        assert "Traceback" not in output
        record = state / "startup-import" / f"{process}.json"
        assert record.is_file(), f"missing configured failure receipt; {output[-1500:]}"
        data = json.loads(record.read_text(encoding="utf-8"))
        assert data["process"] == process
        assert data["error_class"] == "SyntaxError"
        assert data["module"].startswith("binnacle.")
    finally:
        # Only the test-owned fixture is removed, never a parent state root.
        import shutil

        shutil.rmtree(state)


def test_console_script_import_is_bootstrapped():
    import re

    project = Path(__file__).resolve().parents[3] / "pyproject.toml"
    source = project.read_text(encoding="utf-8")
    assert re.search(
        r'^binnacle-jobs = "binnacle.job_manager_cli:main"$',
        source,
        flags=re.MULTILINE,
    )
    assert re.search(
        r'^binnacle = "binnacle.entrypoint:main"$',
        source,
        flags=re.MULTILINE,
    )
