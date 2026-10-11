"""Verified signalling for test teardown (RULE-NO-PKILL, J2t).

Tests run as the same UID beside other lanes and production, so a recorded
pid or pgid may have exited and been recycled. A raw signal is sent only
after the target is re-observed with the recorded birth (and, optionally,
the expected parent); otherwise the signal is skipped and reported.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys

from binnacle.platform.darwin.process_authority import _process_records

SKIPPED: list[str] = []  # every refused signal, for assertions and reports


def observe(pid: int):
    """The current (pid, parent, group, state, birth) record, or None."""
    try:
        records = _process_records(1, pid)
    except OSError:
        return None
    return next((r for r in records if r.pid == pid), None)


def command_of(pid: int) -> str:
    """The pid's command line via ps(1), or "" when it is gone."""
    ps = ["ps", "-p", str(pid), "-o", "command="]
    return subprocess.run(
        ps, capture_output=True, text=True, check=False
    ).stdout.strip()


def _skip(why: str) -> bool:
    SKIPPED.append(why)
    sys.stderr.write(f"signal skipped (no silent kill): {why}\n")
    return False


def signal_verified(
    pid: int,
    number: int,
    birth: tuple[int, int],
    *,
    group: bool = False,
    parent: int | None = None,
) -> bool:
    """Signal ``pid`` (or its group, as leader) only if birth/parent still match."""
    record = observe(pid)
    if record is None:
        return _skip(f"pid {pid} no longer exists")
    if record.birth != birth:
        return _skip(f"pid {pid} birth {record.birth} != recorded {birth} (reused)")
    if parent is not None and record.parent != parent:
        return _skip(f"pid {pid} parent {record.parent} != expected {parent}")
    if group and record.group != pid:
        return _skip(f"pid {pid} is not the leader of its group ({record.group})")
    try:
        (os.killpg if group else os.kill)(pid, number)
    except ProcessLookupError:
        return _skip(f"pid {pid} exited before the signal")
    return True


def kill_verified(pid: int, birth: tuple[int, int], **kw) -> bool:
    return signal_verified(pid, signal.SIGKILL, birth, **kw)
