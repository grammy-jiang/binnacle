"""Test-suite safety net (2026-09-14).

On 2026-09-13 23:49 three watchdog tests that ran the loop without a fake
`run` re-activated the host's real Wi-Fi profiles (NetworkManager's audit
log named the pytest process), and the primary radio spent five minutes
re-associating. No test may change the host: every `subprocess.run` is
wrapped, a mutating command is refused with exit 1, and the test that
tried it fails. Read-only commands (nmcli show/status, ip route show, iw
link, systemctl is-active, `sudo -n true`) still run.
"""

import os
import subprocess
from pathlib import Path

import pytest

from binnacle import startup_imports
from binnacle.diagnostics import doctor_provenance
from tests._jobs_socket_fixture import ensure_test_jobs_socket

# Must run before anything composes settings (test modules import the jobs
# module at collection); a no-op on Linux and when the env var is set.
ensure_test_jobs_socket()

_NMCLI_MUTATING = (
    "connection up",
    "connection down",
    "connection modify",
    "connection add",
    "connection delete",
    "device reapply",
    "device disconnect",
    "device connect",
    "device wifi connect",
    "radio wifi on",
    "radio wifi off",
    "networking",
)


# E1-a5: the real start-up import records are production state on a deployed
# host. XDG_STATE_HOME points at a scratch dir for the whole session, any
# in-process path to the real record directory raises, and the real directory
# is compared before and after the session (a child process cannot be patched).
_REAL_RECORDS = startup_imports.record_dir(
    Path.home() / ".local" / "state" / "binnacle"
).resolve()


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    try:
        return {
            entry.name: (entry.stat().st_size, entry.stat().st_mtime_ns)
            for entry in root.iterdir()
        }
    except OSError:
        return {}


@pytest.fixture(autouse=True, scope="session")
def isolated_state_home(tmp_path_factory):
    before = _snapshot(_REAL_RECORDS)
    saved = os.environ.get("XDG_STATE_HOME")
    os.environ["XDG_STATE_HOME"] = str(tmp_path_factory.mktemp("xdg-state"))
    yield
    if saved is None:
        os.environ.pop("XDG_STATE_HOME", None)
    else:
        os.environ["XDG_STATE_HOME"] = saved
    after = _snapshot(_REAL_RECORDS)
    assert after == before, f"the suite touched {_REAL_RECORDS}: {before} -> {after}"


@pytest.fixture(autouse=True)
def no_real_startup_record(monkeypatch):
    original = startup_imports.record_dir

    def guarded(state_root):
        path = original(state_root)
        if path.resolve() == _REAL_RECORDS:
            raise AssertionError(f"a test reached the real {_REAL_RECORDS}")
        return path

    monkeypatch.setattr(startup_imports, "record_dir", guarded)
    monkeypatch.setattr(doctor_provenance, "record_dir", guarded)


def _is_mutating(argv: list[str]) -> bool:
    if not argv:
        return False
    # uplink.sudo_timeout_argv inserts `timeout <n>` after sudo's flags so the
    # timeout reaches the real command. Strip it here, or this guard would
    # judge the wrapper instead of what is actually being run -- and
    # `sudo -n timeout 30 true`, the harmless privilege probe, would start
    # tripping it.
    if len(argv) > 3 and argv[0] == "sudo":
        i = 1
        while i < len(argv) and argv[i].startswith("-"):
            i += 1
        if i + 1 < len(argv) and argv[i] == "timeout" and argv[i + 1].isdigit():
            argv = argv[:i] + argv[i + 2 :]
    head = argv[0]
    joined = " ".join(argv)
    if head == "sudo":
        return joined != "sudo -n true"
    if head == "systemctl":
        return any(
            v in argv for v in ("restart", "stop", "start", "kill", "enable", "disable")
        )
    if head in (
        "modprobe",
        "rmmod",
        "insmod",
        "iptables",
        "nft",
        "rfkill",
        "reboot",
        "shutdown",
    ):
        return True
    if head == "ip" and len(argv) > 2:
        return argv[1] in ("route", "link", "addr", "neigh") and any(
            v in argv[2:]
            for v in ("add", "del", "delete", "replace", "change", "flush", "set")
        )
    if head == "nmcli":
        return any(verb in joined for verb in _NMCLI_MUTATING)
    if head == "iw":
        return "scan" in argv and "dump" not in argv  # a trigger, not a read
    return False


@pytest.fixture(autouse=True)
def no_host_mutation(monkeypatch):
    real_run = subprocess.run
    blocked: list[str] = []

    def guarded(args, *a, **kw):
        argv = [str(x) for x in (args if isinstance(args, (list, tuple)) else [args])]
        if _is_mutating(argv):
            blocked.append(" ".join(argv))
            return subprocess.CompletedProcess(
                argv,
                1,
                stdout="",
                stderr="blocked by tests/conftest.py: tests must not change the host",
            )
        return real_run(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", guarded)
    yield
    assert not blocked, f"a test tried to change the host: {blocked}"
