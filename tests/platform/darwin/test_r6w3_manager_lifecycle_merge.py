"""R6 W3 merger: preserve both bounded-retry and exactly-once job logs.

These exercise the pure owner authority helpers on every host without
launchd, signals, live jobs or destructive process operations.
"""

from __future__ import annotations

import logging

import pytest

from binnacle.platform.contracts import process_contracts as pc
from binnacle.platform.darwin.job_manager_lifecycle import (
    quiet_kill_owned,
    release_owned_exit,
)

LOG = logging.getLogger("binnacle.job_manager")


class OnlyOwned:
    def __init__(self, problem=None):
        self.calls = []
        self.problem = problem

    def signal_owned_group(self, job_id, intent):
        self.calls.append(("signal", job_id, intent))
        if self.problem is not None:
            raise self.problem

    def release(self, job_id):
        self.calls.append(("release", job_id))
        if self.problem is not None:
            raise self.problem


def test_quiet_cleanup_signals_only_through_owned_authority(caplog):
    owner = OnlyOwned()
    with caplog.at_level(logging.WARNING, logger="binnacle.job_manager"):
        assert quiet_kill_owned(owner, "job-7", LOG) is None
    assert owner.calls == [("signal", "job-7", "kill")]
    assert "job_start_cleanup_unverified" not in caplog.text


@pytest.mark.parametrize(
    "problem",
    [
        pc.UnverifiedJobProcess("unknown process"),
        pc.JobSignalDeliveryError("verified signal partial"),
        OSError("operation denied"),
    ],
)
def test_quiet_cleanup_refuses_unverified_or_partial_delivery(problem, caplog):
    owner = OnlyOwned(problem)
    with caplog.at_level(logging.WARNING, logger="binnacle.job_manager"):
        assert quiet_kill_owned(owner, "job-7", LOG) is None
    assert owner.calls == [("signal", "job-7", "kill")]
    assert "event=job_start_cleanup_unverified job_id=job-7" in caplog.text
    assert str(problem) not in caplog.text


def test_release_acknowledges_the_previously_durable_exit(caplog):
    owner = OnlyOwned()
    with caplog.at_level(logging.WARNING, logger="binnacle.job_manager"):
        assert release_owned_exit(owner, "job-8", LOG) is None
    assert owner.calls == [("release", "job-8")]
    assert "job_release_refused" not in caplog.text


@pytest.mark.parametrize(
    "problem",
    [
        pc.UnverifiedJobProcess("unowned process"),
        pc.JobOwnerLost("old incarnation"),
        ValueError("malformed job identifier"),
    ],
)
def test_release_ignores_race_after_first_durable_exit(problem, caplog):
    owner = OnlyOwned(problem)
    with caplog.at_level(logging.WARNING, logger="binnacle.job_manager"):
        assert release_owned_exit(owner, "job-8", LOG) is None
    assert owner.calls == [("release", "job-8")]
    assert "event=job_release_refused job_id=job-8" in caplog.text
    assert str(problem) not in caplog.text


def test_unexpected_owner_exception_is_not_swallowed():
    owner = OnlyOwned(RuntimeError("unexpected owner failure"))
    with pytest.raises(RuntimeError, match="unexpected owner failure"):
        release_owned_exit(owner, "job-8", LOG)
    with pytest.raises(RuntimeError, match="unexpected owner failure"):
        quiet_kill_owned(owner, "job-8", LOG)
