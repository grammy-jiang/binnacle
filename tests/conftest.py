"""Test-suite safety net (2026-09-14).

On 2026-09-13 23:49 three watchdog tests that ran the loop without a fake
`run` re-activated the host's real Wi-Fi profiles (NetworkManager's audit
log named the pytest process), and the primary radio spent five minutes
re-associating. No test may change the host: every `subprocess.run` is
wrapped, a mutating command is refused with exit 1, and the test that
tried it fails. Read-only commands (nmcli show/status, ip route show, iw
link, systemctl is-active, `sudo -n true`) still run.
"""

import subprocess

import pytest

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
