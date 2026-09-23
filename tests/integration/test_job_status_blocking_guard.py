"""Integration coverage for the job_status blocking-wall guard."""

from types import SimpleNamespace

import pytest
from fastmcp.exceptions import ToolError

from binnacle import jobs as jobstore
from binnacle.blocking_wall_guard import BlockingWallTracker
from binnacle.callctx import current_client, current_turn
from binnacle.tools import job_status as js
from tests.integration.job_test_support import stop


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


def _call_with_context(
    *,
    client: str | None,
    turn: str | None,
    wait_seconds: int,
    job_id: str = "job-1",
):
    client_token = current_client.set(client)
    turn_token = current_turn.set(turn)
    try:
        return js.job_status_impl(job_id, 10, wait_seconds)
    finally:
        current_turn.reset(turn_token)
        current_client.reset(client_token)


@pytest.fixture
def real_job_env(tmp_path, monkeypatch):
    monkeypatch.setattr(jobstore, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(jobstore, "OWNER_MODE", "embedded")
    monkeypatch.setattr(
        js,
        "get_settings",
        lambda: SimpleNamespace(jobs=BudgetSettings({"phase2-real": 3})),
    )
    tracker = BlockingWallTracker()
    monkeypatch.setattr(js, "blocking_wall_tracker", tracker)
    yield tracker

    if jobstore.JOBS_DIR.exists():
        for state in jobstore.list_jobs():
            if state["state"] == "running":
                stop(state["job_id"])


def _start_real_job(command: str, workdir) -> str:
    job_id, proc = jobstore.start_job(command, workdir, None)
    jobstore.reap_in_background(job_id, proc)
    return job_id


def test_output_schema_declares_positive_wait_policy_fields():
    properties = js.OUTPUT_SCHEMA["properties"]
    assert properties["wait_requested_s"] == {"type": "integer"}
    assert properties["wait_effective_s"] == {"type": "integer"}
    assert properties["blocking_budget_s"] == {"type": ["integer", "null"]}
    assert properties["blocking_remaining_s"] == {"type": ["number", "null"]}
    assert properties["blocking_budget_exhausted"] == {"type": "boolean"}
    assert properties["blocking_policy"] == {"type": "string"}


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
        result = _call_with_context(
            client="openai-mcp/1", turn="new-turn", wait_seconds=50
        )
    finally:
        active.release()

    assert waits == [50]
    assert result.structured_content["blocking_policy"] == "capacity_untracked"
    assert result.structured_content["wait_effective_s"] == 50
    assert result.structured_content["blocking_budget_s"] is None
    assert result.structured_content["blocking_remaining_s"] is None
    assert {key[1] for key in tracker._states} == {"active-turn"}


def test_budget_exhaustion_becomes_nonblocking_without_stopping_job(
    status_env, monkeypatch, caplog
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

    with caplog.at_level("INFO", logger="binnacle.job_status"):
        first = _call_with_context(
            client="openai-mcp/1", turn="turn-a", wait_seconds=50
        )
        second = _call_with_context(
            client="openai-mcp/1", turn="turn-a", wait_seconds=50
        )

    assert waits == [1]
    assert first.structured_content["state"] == "running"
    assert first.structured_content["blocking_policy"] == "tracked"
    assert first.structured_content["wait_effective_s"] == 1
    assert first.structured_content["blocking_remaining_s"] == pytest.approx(0.0)
    assert first.structured_content["blocking_budget_exhausted"] is False
    assert (
        "Turn blocking budget exhausted; further positive waits in this turn "
        "will be non-blocking." in first.content[0].text
    )
    assert second.structured_content["state"] == "running"
    assert second.structured_content["waited_s"] == 0.0
    assert second.structured_content["wait_effective_s"] == 0
    assert second.structured_content["blocking_budget_s"] == 1
    assert second.structured_content["blocking_remaining_s"] == pytest.approx(0.0)
    assert second.structured_content["blocking_budget_exhausted"] is True
    assert second.structured_content["blocking_policy"] == "exhausted"
    assert (
        "Turn blocking budget exhausted; further positive waits in this turn "
        "will be non-blocking." in second.content[0].text
    )
    assert job_state_calls == 3
    assert tracker._states[("openai-mcp/1", "turn-a")].spent_s == pytest.approx(1.0)

    timing = [
        record.getMessage()
        for record in caplog.records
        if "event=job_status_timing" in record.getMessage()
    ]
    closed = [
        record.getMessage()
        for record in caplog.records
        if "event=blocking_window_closed" in record.getMessage()
    ]
    assert len(timing) == 2
    assert len(closed) == 1
    assert "wait_requested_s=50" in timing[0]
    assert "wait_bounded_s=50" in timing[0]
    assert "wait_effective_s=1" in timing[0]
    assert "waited_s=1.0" in timing[0]
    assert "blocking_budget_s=1" in timing[0]
    assert "blocking_spent_before_s=0.0" in timing[0]
    assert "blocking_remaining_before_s=1.0" in timing[0]
    assert "blocking_active_before=0" in timing[0]
    assert "blocking_policy=tracked" in timing[0]
    assert "blocking_budget_exhausted=false" in timing[0]
    assert "turn=turn-a" in timing[0]
    assert "client=openai-mcp/1" in timing[0]
    assert "wait_effective_s=0" in timing[1]
    assert "blocking_policy=exhausted" in timing[1]
    assert "blocking_budget_exhausted=true" in timing[1]
    assert "blocking_window_wall_s=1.0" in closed[0]
    assert "blocking_spent_after_s=1.0" in closed[0]
    assert "blocking_remaining_after_s=0.0" in closed[0]


def test_wait_exception_releases_active_lease(status_env, monkeypatch, caplog):
    _, clock, tracker = status_env

    def failing_wait(job_id: str, wait_seconds: int):
        clock.advance(2.0)
        raise RuntimeError("wait failed")

    monkeypatch.setattr(js, "_wait_for_exit", failing_wait)

    with (
        caplog.at_level("INFO", logger="binnacle.job_status"),
        pytest.raises(RuntimeError, match="wait failed"),
    ):
        _call_with_context(client="openai-mcp/1", turn="turn-a", wait_seconds=50)

    closed = [
        record.getMessage()
        for record in caplog.records
        if "event=blocking_window_closed" in record.getMessage()
    ]
    assert len(closed) == 1
    assert "blocking_window_wall_s=2.0" in closed[0]
    assert "blocking_spent_after_s=2.0" in closed[0]

    tracked = tracker._states[("openai-mcp/1", "turn-a")]
    assert tracked.active_count == 0
    assert tracked.spent_s == pytest.approx(2.0)


def test_real_job_early_exit_charges_actual_wall(real_job_env, tmp_path, caplog):
    tracker = real_job_env
    job_id = _start_real_job("sleep 0.2", tmp_path)

    with caplog.at_level("INFO", logger="binnacle.job_status"):
        result = _call_with_context(
            client="phase2-real/1",
            turn="turn-early",
            wait_seconds=2,
            job_id=job_id,
        )

    payload = result.structured_content
    assert payload["state"] == "exited"
    assert payload["exit_code"] == 0
    assert payload["blocking_policy"] == "tracked"
    assert payload["wait_effective_s"] == 2
    assert 0.0 <= payload["waited_s"] < 1.5
    assert 2.0 < payload["blocking_remaining_s"] <= 3.0
    assert payload["blocking_budget_exhausted"] is False
    assert "exited 0" in result.content[0].text

    tracked = tracker._states[("phase2-real/1", "turn-early")]
    assert tracked.active_count == 0
    assert tracked.spent_s == pytest.approx(
        3.0 - payload["blocking_remaining_s"], abs=0.05
    )
    assert abs(tracked.spent_s - payload["waited_s"]) < 0.2

    timing = [
        record.getMessage()
        for record in caplog.records
        if "event=job_status_timing" in record.getMessage()
    ]
    closed = [
        record.getMessage()
        for record in caplog.records
        if "event=blocking_window_closed" in record.getMessage()
    ]
    assert any(
        "blocking_policy=tracked" in line
        and "turn=turn-early" in line
        and "client=phase2-real/1" in line
        for line in timing
    )
    assert len(closed) == 1


def test_real_job_sequential_exhaustion_keeps_job_durable(
    real_job_env, tmp_path, caplog
):
    tracker = real_job_env
    job_id = _start_real_job("sleep 5", tmp_path)
    results = []

    with caplog.at_level("INFO", logger="binnacle.job_status"):
        for _ in range(4):
            result = _call_with_context(
                client="phase2-real/1",
                turn="turn-exhaust",
                wait_seconds=2,
                job_id=job_id,
            )
            results.append(result)
            if result.structured_content["blocking_policy"] == "exhausted":
                break

    exhausted = results[-1]
    payload = exhausted.structured_content
    assert payload["blocking_policy"] == "exhausted"
    assert payload["state"] == "running"
    assert payload["wait_effective_s"] == 0
    assert payload["waited_s"] == 0.0
    assert payload["blocking_budget_s"] == 3
    assert payload["blocking_remaining_s"] < 1.0
    assert payload["blocking_budget_exhausted"] is True
    assert (
        "Turn blocking budget exhausted; further positive waits in this turn "
        "will be non-blocking." in exhausted.content[0].text
    )

    tracked_payloads = [
        item.structured_content
        for item in results
        if item.structured_content["blocking_policy"] == "tracked"
    ]
    assert tracked_payloads
    total_waited = sum(item["waited_s"] for item in tracked_payloads)
    assert 1.5 <= total_waited <= 3.5

    state = jobstore.job_state(job_id)
    assert state is not None and state["state"] == "running"
    listing = js.job_status_impl(None, 100, 0).structured_content["jobs"]
    assert any(
        item["job_id"] == job_id and item["state"] == "running" for item in listing
    )

    tracked = tracker._states[("phase2-real/1", "turn-exhaust")]
    assert tracked.active_count == 0
    assert 1.5 <= tracked.spent_s <= 3.0

    stopped = stop(job_id)
    assert stopped["state"] == "exited"
    assert stopped["signal"] in (15, 9)

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "event=job_status_timing" in line
        and "blocking_policy=exhausted" in line
        and "turn=turn-exhaust" in line
        for line in messages
    )


def test_real_job_already_exited_positive_wait_is_prompt(real_job_env, tmp_path):
    tracker = real_job_env
    job_id = _start_real_job("true", tmp_path)
    exited = jobstore.await_exit(job_id, 2.0)
    assert exited is not None and exited["state"] == "exited"

    result = _call_with_context(
        client="phase2-real/1",
        turn="turn-exited",
        wait_seconds=2,
        job_id=job_id,
    )
    payload = result.structured_content

    assert payload["state"] == "exited"
    assert payload["blocking_policy"] == "tracked"
    assert payload["wait_effective_s"] == 2
    assert payload["waited_s"] < 0.2
    assert payload["blocking_remaining_s"] > 2.5
    tracked = tracker._states[("phase2-real/1", "turn-exited")]
    assert tracked.spent_s < 0.2


def test_real_job_zero_wait_adds_no_policy_state(real_job_env, tmp_path):
    tracker = real_job_env
    job_id = _start_real_job("sleep 5", tmp_path)

    result = _call_with_context(
        client="phase2-real/1",
        turn="turn-zero",
        wait_seconds=0,
        job_id=job_id,
    )
    payload = result.structured_content

    assert payload["state"] == "running"
    for key in (
        "waited_s",
        "wait_requested_s",
        "wait_effective_s",
        "blocking_budget_s",
        "blocking_remaining_s",
        "blocking_budget_exhausted",
        "blocking_policy",
    ):
        assert key not in payload
    assert tracker._states == {}


def test_real_job_invalid_id_does_not_acquire_tracker(real_job_env, monkeypatch):
    tracker = real_job_env

    def unexpected_settings():
        raise AssertionError("settings must not be resolved for an unknown job")

    monkeypatch.setattr(js, "get_settings", unexpected_settings)
    with pytest.raises(ToolError, match="No job with id"):
        _call_with_context(
            client="phase2-real/1",
            turn="turn-invalid",
            wait_seconds=2,
            job_id="missing-real-job",
        )
    assert tracker._states == {}


def test_real_job_no_policy_preserves_ordinary_wait(
    real_job_env, tmp_path, monkeypatch
):
    tracker = real_job_env
    monkeypatch.setattr(
        js,
        "get_settings",
        lambda: SimpleNamespace(jobs=BudgetSettings({})),
    )
    job_id = _start_real_job("sleep 0.2", tmp_path)
    result = _call_with_context(
        client="phase2-real/1", turn="turn-no-policy", wait_seconds=2, job_id=job_id
    )
    payload = result.structured_content
    assert payload["state"] == "exited"
    assert payload["blocking_policy"] == "no_policy"
    assert payload["wait_effective_s"] == 2
    assert payload["blocking_budget_s"] is None
    assert payload["blocking_remaining_s"] is None
    assert payload["blocking_budget_exhausted"] is False
    assert payload["waited_s"] < 1.5
    assert tracker._states == {}


def test_real_job_no_turn_preserves_ordinary_wait(real_job_env, tmp_path):
    tracker = real_job_env
    job_id = _start_real_job("sleep 0.2", tmp_path)
    result = _call_with_context(
        client="phase2-real/1", turn=None, wait_seconds=2, job_id=job_id
    )
    payload = result.structured_content
    assert payload["state"] == "exited"
    assert payload["blocking_policy"] == "no_turn"
    assert payload["wait_effective_s"] == 2
    assert payload["blocking_budget_s"] is None
    assert payload["blocking_remaining_s"] is None
    assert payload["blocking_budget_exhausted"] is False
    assert payload["waited_s"] < 1.5
    assert tracker._states == {}
