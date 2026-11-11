"""Disposable systemd unit primitives for the explicit D1 systemd rehearsal.

Split from manager_systemd_test_support.py (the rehearsal checks) to keep both
modules inside the size ratchet. Same rules: NOT a pytest test, imported only
after the rehearsal's opt-in, and temporary unit names are checked before any
`systemctl stop`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from binnacle.features.commands import job_client
from tests.integration.test_job_manager_v2 import _pinned_fd, _request, _send
from tests.integration.test_job_manager_v2_lifecycle import _WORKER


def _expect(condition: object, message: object = "rehearsal check failed") -> None:
    """Fail like ``assert``, but also under ``python -O`` (bandit B101)."""
    if not condition:
        raise AssertionError(message)


def _systemctl(*args: str, timeout: float = 8) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _unit_setting(unit: str, key: str) -> str:
    result = _systemctl("show", "--property", key, "--value", unit)
    _expect(result.returncode == 0, result.stderr)
    return result.stdout.strip()


def _process_state(pid: int) -> str | None:
    try:
        data = Path(f"/proc/{pid}/stat").read_text()
        return data.rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        return None


def _wait_for(predicate, timeout: float = 8) -> bool:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if predicate():
            return True
        time.sleep(0.05)
    return False


_LEGACY_WORKER = r"""
import signal, sys, threading
from pathlib import Path
from binnacle.features.commands import jobs
from binnacle.features.commands.job_manager import JobManager
root, run, store = map(Path, sys.argv[1:])
jobs.JOBS_DIR = store
manager = JobManager(run / 'legacy.sock', owner_instance_id='isolated-v1-owner',
    boot_id=jobs._PROCESS_BACKEND.boot_id())
def shutdown(_sig, _frame):
    threading.Thread(target=manager.shutdown, daemon=True).start()
signal.signal(signal.SIGTERM, shutdown)
manager.serve_forever()
"""


def _start_disposable_manager_unit(
    *,
    unit: str,
    root: Path,
    run: Path,
    store: Path,
    source: Path,
    v2_enabled: bool = True,
) -> None:
    _expect(
        unit.startswith("binnacle-d1c-isolated-") and unit.endswith(".service"),
        'unit.startswith("binnacle-d1c-isolated-") and unit.endswith(".service")',
    )
    _expect(
        _unit_setting(unit, "LoadState") == "not-found",
        '_unit_setting(unit, "LoadState") == "not-found"',
    )
    _expect(
        shutil.which("systemd-run") is not None,
        'shutil.which("systemd-run") is not None',
    )
    properties = (
        # Match the production Manager's notify readiness and cgroup
        # lifecycle, while disabling automatic *test* service restart.
        "Type=notify",
        "NotifyAccess=main",
        "TimeoutStartSec=30s",
        "Restart=no",
        "KillMode=control-group",
        "Delegate=cpu memory pids",
        "DelegateSubgroup=binnacle-manager",
        "TimeoutStopSec=10s",
        "UMask=0077",
        f"WorkingDirectory={root}",
    )
    command = ["systemd-run", "--user", "--collect", "--unit", unit]
    command.extend(f"--property={p}" for p in properties)
    command.extend(
        [
            f"--setenv=PYTHONPATH={source}",
            "--setenv=PYTHONDONTWRITEBYTECODE=1",
            sys.executable,
            "-c",
            _WORKER if v2_enabled else _LEGACY_WORKER,
            str(root),
            str(run),
            str(store),
        ]
    )
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=8, check=False
    )
    _expect(result.returncode == 0, result.stderr)
    _expect(
        _wait_for(
            lambda: (
                (run / "start-v2.sock").exists() == v2_enabled
                and (run / "legacy.sock").exists()
                and _unit_setting(unit, "ActiveState") == "active"
            ),
            timeout=9,
        ),
        f"disposable Manager failed to bind, systemd: {_systemctl('status', unit).stdout[-700:]}",
    )
    _expect(
        _unit_setting(unit, "KillMode") == "control-group",
        '_unit_setting(unit, "KillMode") == "control-group"',
    )
    _expect(
        _unit_setting(unit, "Type") == "notify",
        '_unit_setting(unit, "Type") == "notify"',
    )
    _expect(
        _unit_setting(unit, "DelegateSubgroup") == "binnacle-manager",
        '_unit_setting(unit, "DelegateSubgroup") == "binnacle-manager"',
    )
    cgroup = _unit_setting(unit, "ControlGroup")
    _expect(unit in cgroup and "binnacle-jobs.service" not in cgroup, cgroup)
    _expect(
        job_client.ping(run / "legacy.sock")["version"] == 1,
        'job_client.ping(run / "legacy.sock")["version"] == 1',
    )


def _fixture(tmp_path: Path):
    root = tmp_path / "allowed"
    root.mkdir()
    (root / "marker").write_text("ISOLATED-CGROUP-ONLY\n")
    run = tmp_path / "private-run"
    run.mkdir(mode=0o700)
    run.chmod(0o700)
    store = tmp_path / "job-store"
    source = Path(__file__).resolve().parents[1] / "src"
    _expect(
        source.joinpath("binnacle/features/commands/job_manager_v2.py").is_file(),
        'source.joinpath("binnacle/features/commands/job_manager_v2.py").is_file()',
    )
    unit = f"binnacle-d1c-isolated-{uuid.uuid4().hex[:12]}.service"
    return unit, root, run, store, source


def _start_job(root: Path, run: Path, command: str, call_id: str) -> dict:
    fd = _pinned_fd(root)
    try:
        response = _send(
            run / "start-v2.sock",
            _request(root, command=command, wait_seconds=0.0, call_id=call_id),
            (fd,),
        )
    finally:
        os.close(fd)
    _expect(response["ok"] is True, response)
    return response


def _cleanup_own_unit(unit: str) -> None:
    _expect(
        unit.startswith("binnacle-d1c-isolated-") and unit.endswith(".service"),
        'unit.startswith("binnacle-d1c-isolated-") and unit.endswith(".service")',
    )
    try:
        result = _systemctl("stop", unit, timeout=15)
        _expect(
            result.returncode == 0 or "not loaded" in result.stderr.lower(),
            result.stderr,
        )
    finally:
        # Unique test-only unit: never call systemctl on production service.
        _expect(
            "binnacle-jobs.service" not in unit, '"binnacle-jobs.service" not in unit'
        )
