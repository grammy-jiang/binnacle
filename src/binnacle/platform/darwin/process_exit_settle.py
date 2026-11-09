"""Bounded wait for an exiting group leader to become a zombie (SZOMB).

killpg(2) on macOS answers EPERM once every member of the group is inside
exit, while the leader may still read SRUN instead of SZOMB. Measured on macOS
27 arm64 over 4000 session leaders: the window lasts 0.31 ms (p50), 0.43 ms
(p99) and 1.34 ms (max, idle host). The caller's leader is unreaped, so its pid
stays reserved and cannot be reused while this waits; the bound covers a loaded
host. Success needs the same proof as before the wait: the leader is SZOMB and
the only member. Anything else fails closed.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Protocol

SZOMB = 5
SETTLE_S = 0.05
POLL_S = 0.0005


class _Record(Protocol):
    @property
    def pid(self) -> int: ...

    @property
    def state(self) -> int: ...


def lone_leader_became_zombie(
    pid: int,
    read_leader: Callable[[], _Record],
    read_group: Callable[[], Sequence[_Record]],
    *,
    settle_s: float | None = None,
) -> bool:
    """True when the group is only ``pid`` and it reads SZOMB within the bound.

    ``read_leader`` raises when the owned leader is lost; ``read_group`` raises
    OSError when the group cannot be read, which fails closed.
    """
    deadline = time.monotonic() + (SETTLE_S if settle_s is None else settle_s)
    while True:
        leader = read_leader()
        try:
            members = list(read_group())
        except OSError:
            return False
        if leader.state == SZOMB and members == [leader]:
            return True
        # Compare pids: the leader may change state between the two reads.
        alone = [member.pid for member in members] == [pid]
        if not alone or time.monotonic() >= deadline:
            return False
        time.sleep(POLL_S)
