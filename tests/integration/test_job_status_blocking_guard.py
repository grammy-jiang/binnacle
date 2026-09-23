"""Integration coverage for the job_status blocking-wall guard."""

from types import SimpleNamespace

import pytest
from fastmcp.exceptions import ToolError

from binnacle.blocking_wall_guard import BlockingWallTracker
from binnacle.callctx import current_client, current_turn
from binnacle.tools import job_status as js


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class BudgetSettings:
    def __init__(self, budgets: dict[str, int]) -> None:
        self._budgets = budgets

    def blocking_wall_budget_for_client(self, client: str | None) -> int | None:
        if client is None:
            return None
        matches = (prefix for prefix in self._budgets if client.startswith(prefix))
        prefix = max(matches, key=len, default=None)
        return self._budgets[prefix] if prefix is not None else None


def _state(*, state: str = "running") -> dict:
    return {
        "job_id": "job-1",
        "state": state,
        "exit_code": 0 if state == "exited" else None,
        "signal": None,
        "command": "sleep 30",
        "workdir": "/tmp",
        "pid": 123,
        "pgid": 123,
        "started_at": 1.0,
        "ended_at": 2.0 if state == "exited" else None,
        "runtime_s": 5.0,
        "last_output_age_s": 1.0,
        "log_bytes": 0,
        "log_path": "/tmp/out.log",
    }


@pytest.fixture
def status_env(monkeypatch):
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
    return state, clock, tracker


def _call_with_context(*, client: str | None, turn: str | None, wait_seconds: int):
    client_token = current_client.set(client)
    turn_token = current_turn.set(turn)
    try:
        return js.job_status_impl("job-1", 10, wait_seconds)
    finally:
        current_turn.reset(turn_token)
        current_client.reset(client_token)


def test_matching_client_and_turn_reduce_later_positive_wait(status_env, monkeypatch):
    state, clock, tracker = status_env
    waits: list[int] = []

    def fake_wait(job_id: str, wait_seconds: int):
        waits.append(wait_seconds)
        if len(waits) == 1:
            clock.advance(2.0)
        return state, float(wait_seconds)

    monkeypatch.setattr(js, "_wait_for_exit", fake_wait)

    first = _call_with_context(client="openai-mcp/1", turn="turn-a", wait_seconds=50)
    second = _call_with_context(client="openai-mcp/1", turn="turn-a", wait_seconds=50)

    assert waits == [5, 3]
    assert first.structured_content["waited_s"] == 5.0
    assert second.structured_content["waited_s"] == 3.0
    tracked = tracker._states[("openai-mcp/1", "turn-a")]
    assert tracked.spent_s == pytest.approx(2.0)


def test_no_policy_preserves_ordinary_bounded_wait(monkeypatch, status_env):
    state, _, tracker = status_env
    monkeypatch.setattr(
        js,
        "get_settings",
        lambda: SimpleNamespace(jobs=BudgetSettings({})),
    )
    waits: list[int] = []

    def fake_wait(job_id: str, wait_seconds: int):
        waits.append(wait_seconds)
        return state, 0.25

    monkeypatch.setattr(js, "_wait_for_exit", fake_wait)

    result = _call_with_context(client="openai-mcp/1", turn="turn-a", wait_seconds=50)

    assert waits == [50]
    assert result.structured_content["waited_s"] == 0.25
    assert tracker._states == {}


def test_no_turn_preserves_ordinary_bounded_wait(status_env, monkeypatch):
    state, _, tracker = status_env
    waits: list[int] = []

    def fake_wait(job_id: str, wait_seconds: int):
        waits.append(wait_seconds)
        return state, 0.25

    monkeypatch.setattr(js, "_wait_for_exit", fake_wait)

    _call_with_context(client="openai-mcp/1", turn=None, wait_seconds=50)

    assert waits == [50]
    assert tracker._states == {}


def test_capacity_fallback_preserves_ordinary_bounded_wait(status_env, monkeypatch):
    state, clock, _ = status_env
    tracker = BlockingWallTracker(clock=clock, capacity=1)
    active = tracker.acquire(
        client="openai-mcp/1",
        turn="active-turn",
        requested_wait_s=50,
        bounded_wait_s=50,
        budget_s=5,
    )
    monkeypatch.setattr(js, "blocking_wall_tracker", tracker)
    waits: list[int] = []

    def fake_wait(job_id: str, wait_seconds: int):
        waits.append(wait_seconds)
        return state, 0.25

    monkeypatch.setattr(js, "_wait_for_exit", fake_wait)

    try:
        _call_with_context(client="openai-mcp/1", turn="new-turn", wait_seconds=50)
    finally:
        active.release()

    assert waits == [50]
    assert {key[1] for key in tracker._states} == {"active-turn"}


def test_budget_exhaustion_becomes_nonblocking_without_stopping_job(
    status_env, monkeypatch
):
    state, clock, tracker = status_env
    monkeypatch.setattr(
        js,
        "get_settings",
        lambda: SimpleNamespace(jobs=BudgetSettings({"openai-mcp": 1})),
    )
    waits: list[int] = []
    job_state_calls = 0

    def job_state(job_id: str):
        nonlocal job_state_calls
        job_state_calls += 1
        return state

    def fake_wait(job_id: str, wait_seconds: int):
        waits.append(wait_seconds)
        clock.advance(1.0)
        return state, 1.0

    monkeypatch.setattr(js.jobs, "job_state", job_state)
    monkeypatch.setattr(js, "_wait_for_exit", fake_wait)

    first = _call_with_context(client="openai-mcp/1", turn="turn-a", wait_seconds=50)
    second = _call_with_context(client="openai-mcp/1", turn="turn-a", wait_seconds=50)

    assert waits == [1]
    assert first.structured_content["state"] == "running"
    assert second.structured_content["state"] == "running"
    assert second.structured_content["waited_s"] == 0.0
    assert job_state_calls == 3
    assert tracker._states[("openai-mcp/1", "turn-a")].spent_s == pytest.approx(1.0)


def test_unknown_job_is_rejected_before_policy_resolution(monkeypatch):
    tracker = BlockingWallTracker()
    monkeypatch.setattr(js, "blocking_wall_tracker", tracker)
    monkeypatch.setattr(js.jobs, "job_state", lambda job_id: None)

    def unexpected_settings():
        raise AssertionError("settings must not be resolved for an unknown job")

    monkeypatch.setattr(js, "get_settings", unexpected_settings)

    with pytest.raises(ToolError, match="No job with id"):
        _call_with_context(client="openai-mcp/1", turn="turn-a", wait_seconds=50)

    assert tracker._states == {}


def test_zero_wait_does_not_acquire_policy(status_env):
    _, _, tracker = status_env

    result = _call_with_context(client="openai-mcp/1", turn="turn-a", wait_seconds=0)

    assert "waited_s" not in result.structured_content
    assert tracker._states == {}


def test_wait_exception_releases_active_lease(status_env, monkeypatch):
    _, clock, tracker = status_env

    def failing_wait(job_id: str, wait_seconds: int):
        clock.advance(2.0)
        raise RuntimeError("wait failed")

    monkeypatch.setattr(js, "_wait_for_exit", failing_wait)

    with pytest.raises(RuntimeError, match="wait failed"):
        _call_with_context(client="openai-mcp/1", turn="turn-a", wait_seconds=50)

    tracked = tracker._states[("openai-mcp/1", "turn-a")]
    assert tracked.active_count == 0
    assert tracked.spent_s == pytest.approx(2.0)
