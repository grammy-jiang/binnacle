"""Error-path coverage for the job_status blocking-wall guard."""

from types import SimpleNamespace

import pytest

from binnacle.blocking_wall_guard import BlockingWallTracker
from tests.integration.test_job_status_blocking_guard import (
    BudgetSettings,
    FakeClock,
    _call_with_context,
    _state,
    js,
)


@pytest.fixture
def error_status_env(monkeypatch):
    state = _state()
    monkeypatch.setattr(js.jobs, "job_state", lambda job_id: state)
    monkeypatch.setattr(js.jobs, "read_log", lambda job_id: b"")
    monkeypatch.setattr(js.jobs, "job_processes", lambda pgid: [])
    monkeypatch.setattr(
        js,
        "get_settings",
        lambda: SimpleNamespace(jobs=BudgetSettings({"openai-mcp": 5})),
    )
    clock = FakeClock()
    tracker = BlockingWallTracker(clock=clock)
    monkeypatch.setattr(js, "blocking_wall_tracker", tracker)
    return clock, tracker


def test_wait_exception_logs_policy_timing(error_status_env, monkeypatch, caplog):
    clock, tracker = error_status_env

    def failing_wait(job_id: str, wait_seconds: int):
        clock.advance(2.0)
        raise RuntimeError("wait failed")

    monkeypatch.setattr(js, "_PERF_COUNTER", clock)
    monkeypatch.setattr(js, "_wait_for_exit", failing_wait)

    with (
        caplog.at_level("INFO", logger="binnacle.job_status"),
        pytest.raises(RuntimeError, match="wait failed"),
    ):
        _call_with_context(client="openai-mcp/1", turn="turn-a", wait_seconds=50)

    messages = [record.getMessage() for record in caplog.records]
    closed = next(
        message for message in messages if "event=blocking_window_closed" in message
    )
    assert "blocking_window_wall_s=2.0" in closed
    assert "blocking_spent_after_s=2.0" in closed
    timing = next(
        message for message in messages if "event=job_status_timing" in message
    )
    assert (
        "wait_requested_s=50 wait_bounded_s=50 wait_effective_s=5 waited_s=2.0"
        in timing
    )
    assert (
        "blocking_budget_s=5 blocking_spent_before_s=0.0 blocking_remaining_before_s=5.0"
        in timing
    )
    assert (
        "blocking_active_before=0 blocking_policy=tracked blocking_budget_exhausted=false"
        in timing
    )
    assert "turn=turn-a client=openai-mcp/1" in timing
    assert (
        "read_log_ms=na process_scan_ms=na" in timing
        and "state=error processes=na" in timing
    )

    tracked = tracker._states[("openai-mcp/1", "turn-a")]
    assert tracked.active_count == 0 and tracked.spent_s == pytest.approx(2.0)
