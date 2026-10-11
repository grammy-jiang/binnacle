"""r6 W2 M1 step 3 (D3): Darwin minors from DARWIN-FOLLOWUP-j1g-minor.

PRE-J1g-F5: a fork-heavy group can race the KERN_PROC_PGRP size + read pair
(ENOMEM). ``group_listing`` retries the pair a bounded number of times before
it returns the unchanged empty listing.
"""

from __future__ import annotations

import errno
import os
import sys

import pytest

from binnacle.platform.darwin import job_manager_entry as entry

NATIVE = pytest.mark.skipif(sys.platform != "darwin", reason="Darwin KERN_PROC_PGRP")


def flaky_sysctl(monkeypatch, failures: int) -> list[tuple[int, ...]]:
    calls: list[tuple[int, ...]] = []
    real = entry._sysctl

    def sysctl(mib, limit):
        calls.append(tuple(mib))
        if len(calls) <= failures:
            raise OSError(errno.ENOMEM, "sysctl read failed")
        return real(mib, limit)

    monkeypatch.setattr(entry, "_sysctl", sysctl)
    return calls


@NATIVE
def test_a_persistent_size_race_returns_the_empty_listing_after_bounded_tries(
    monkeypatch,
):
    calls = flaky_sysctl(monkeypatch, failures=99)
    assert entry.group_listing(os.getpgrp(), 200) == []
    assert len(calls) == entry.GROUP_LISTING_ATTEMPTS == 3


@NATIVE
def test_a_transient_size_race_is_retried_and_lists_the_group(monkeypatch):
    calls = flaky_sysctl(monkeypatch, failures=entry.GROUP_LISTING_ATTEMPTS - 1)
    listing = entry.group_listing(os.getpgrp(), 200)
    pgrp_calls = [c for c in calls if c[:3] == (1, 14, 2)]
    assert len(pgrp_calls) == entry.GROUP_LISTING_ATTEMPTS
    if os.getpgrp() == os.getpid():  # we lead our group: we must be listed
        assert os.getpid() in [item["pid"] for item in listing]
    assert all(set(item) == {"pid", "state", "etime_s", "cmd"} for item in listing)
