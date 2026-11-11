"""killpg EPERM while the lone leader is inside exit: wait for SZOMB, else fail closed.

Measured on macOS 27 arm64: the leader reads p_stat 2 (SRUN) with killpg EPERM
for about a millisecond before p_stat 5 (SZOMB). Synthetic records here; the
native race is test_foreground_commands.test_native_cancel_and_leader_exit_race.
"""

from __future__ import annotations

import errno
import os
import signal
from typing import NamedTuple

import pytest

from binnacle.platform.contracts.capability_contracts import AuthorityUnknown
from binnacle.platform.darwin import process_authority, process_exit_settle
from binnacle.platform.darwin.process_exit_settle import lone_leader_became_zombie
from tests.platform.darwin.test_process_authority import (
    simulated_owner,  # noqa: F401 - the synthetic owner fixture
)


class Record(NamedTuple):
    pid: int
    state: int


def _leader(states):
    reads = iter(states)
    last = [states[0] if states else 2]

    def read():
        last[0] = next(reads, last[0])
        return Record(7, last[0])

    return read, last


def test_lone_leader_that_reaches_szomb_is_proven():
    read, last = _leader([2, 2, 2, 5])
    assert lone_leader_became_zombie(7, read, lambda: [Record(7, last[0])])


def test_leader_state_changing_between_the_two_reads_keeps_waiting():
    # The leader reads SRUN, then the group read already sees SZOMB.
    read, _ = _leader([2, 5])
    states = iter([5, 5])
    assert lone_leader_became_zombie(7, read, lambda: [Record(7, next(states))])


def test_no_szomb_within_the_bound_fails_closed():
    read, last = _leader([2])
    group = lambda: [Record(7, last[0])]
    assert not lone_leader_became_zombie(7, read, group, settle_s=0.01)


def test_another_member_fails_closed_without_waiting(monkeypatch):
    monkeypatch.setattr(process_exit_settle.time, "sleep", lambda s: pytest.fail())
    read, _ = _leader([2])
    group = lambda: [Record(7, 2), Record(8, 2)]
    assert not lone_leader_became_zombie(7, read, group, settle_s=60)


def test_unreadable_group_fails_closed():
    def broken():
        raise OSError(errno.EIO, "sysctl")

    read, _ = _leader([5])
    assert not lone_leader_became_zombie(7, read, broken)


def test_owner_signal_succeeds_once_the_exiting_leader_is_a_zombie(
    simulated_owner,  # noqa: F811
    monkeypatch,
):
    """Through _ForegroundOwner: the CI failure mode, now a completed exit."""
    states = iter([2, 2, 2, 5])
    current = [2]

    def records(kind, identifier):
        if kind == 1:
            current[0] = next(states, current[0])
        return [
            process_authority._ProcessRecord(
                12345, os.getpid(), 12345, current[0], (1, 0)
            )
        ]

    def refused(pid, sig):
        raise OSError(errno.EPERM, "every member is inside exit")

    kills = []
    monkeypatch.setattr(process_authority, "_process_records", records)
    monkeypatch.setattr(os, "killpg", refused)
    monkeypatch.setattr(os, "kill", lambda pid, sig: kills.append(sig))
    simulated_owner._signal_locked(signal.SIGTERM)
    assert kills == []  # a zombie needs no direct signal


def test_owner_signal_without_szomb_stays_unverified(
    simulated_owner,  # noqa: F811
    monkeypatch,
):
    monkeypatch.setattr(process_exit_settle, "SETTLE_S", 0.01)
    record = process_authority._ProcessRecord(12345, os.getpid(), 12345, 2, (1, 0))
    monkeypatch.setattr(process_authority, "_process_records", lambda *a: [record])

    def refused(pid, sig):
        raise OSError(errno.EPERM, "every member is inside exit")

    monkeypatch.setattr(os, "killpg", refused)
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)
    with pytest.raises(AuthorityUnknown, match="darwin_foreground_signal_unverified"):
        simulated_owner._signal_locked(signal.SIGTERM)
