"""The stable owner survives independently constructed, short-lived MCP workers."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.integration.job_reload_support import MANAGER, reload_scenario, source_env


def test_separate_workers_share_manager_cursor_and_idempotent_stop(tmp_path):
    source = Path(__file__).resolve().parents[2] / "src"
    reload_scenario(tmp_path, source, source)


@pytest.mark.parametrize("legacy", [True, False])
def test_manager_fixture_supports_both_cgroup_layouts(tmp_path, legacy):
    pkg = tmp_path / "binnacle"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "features").mkdir()
    (pkg / "features" / "__init__.py").write_text("")
    commands = pkg / "features" / "commands"
    commands.mkdir()
    (commands / "__init__.py").write_text("")
    (commands / "jobs.py").write_text("JOBS_DIR = None\n")
    (commands / "job_manager.py").write_text(
        "def _notify_systemd_ready(): pass\n"
        "class JobManager:\n"
        "    def __init__(self, *args, **kwargs): pass\n"
        "    def serve_forever(self): _notify_systemd_ready()\n"
    )
    module_dir = pkg if legacy else pkg / "platform" / "linux"
    module_dir.mkdir(parents=True, exist_ok=True)
    if not legacy:
        (pkg / "platform" / "__init__.py").write_text("")
        (module_dir / "__init__.py").write_text("")
    (module_dir / "job_cgroup.py").write_text("")

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            MANAGER,
            str(tmp_path),
            str(tmp_path / "spool"),
            str(tmp_path / "manager.sock"),
        ],
        env=source_env(tmp_path),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip())["source"] == str(commands / "jobs.py")
