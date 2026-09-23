"""Concurrent real-job and reload coverage for the blocking-wall guard."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle import jobs as jobstore
from binnacle.blocking_wall_guard import BlockingWallTracker
from binnacle.callctx import current_client, current_turn
from binnacle.tools import job_status as js
from tests.integration.job_test_support import stop


class BudgetSettings:
    def __init__(self, budgets: dict[str, int]) -> None:
        self._budgets = budgets

    def blocking_wall_budget_for_client(self, client: str | None) -> int | None:
        if client is None:
            return None
        matches = (prefix for prefix in self._budgets if client.startswith(prefix))
        prefix = max(matches, key=len, default=None)
        return self._budgets[prefix] if prefix is not None else None


@pytest.fixture
def concurrency_env(tmp_path, monkeypatch):
    monkeypatch.setattr(jobstore, "JOBS_DIR", tmp_path / "jobs-concurrency")
    monkeypatch.setattr(jobstore, "OWNER_MODE", "embedded")
    monkeypatch.setattr(
        js,
        "get_settings",
        lambda: SimpleNamespace(jobs=BudgetSettings({"phase2-concurrent": 3})),
    )
    tracker = BlockingWallTracker()
    monkeypatch.setattr(js, "blocking_wall_tracker", tracker)
    yield tracker

    if jobstore.JOBS_DIR.exists():
        for state in jobstore.list_jobs():
            if state["state"] == "running":
                stop(state["job_id"])


def _start_job(workdir: Path) -> str:
    job_id, proc = jobstore.start_job("sleep 5", workdir, None)
    jobstore.reap_in_background(job_id, proc)
    return job_id


def _call_status(*, job_id: str, turn: str, wait_seconds: int):
    client_token = current_client.set("phase2-concurrent/1")
    turn_token = current_turn.set(turn)
    try:
        return js.job_status_impl(job_id, 20, wait_seconds)
    finally:
        current_turn.reset(turn_token)
        current_client.reset(client_token)


def _parallel_status(
    calls: list[tuple[str, str, int]],
) -> tuple[list, float]:
    barrier = threading.Barrier(len(calls) + 1)

    def worker(job_id: str, turn: str, wait_seconds: int):
        barrier.wait(timeout=3.0)
        return _call_status(job_id=job_id, turn=turn, wait_seconds=wait_seconds)

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(calls)) as executor:
        futures = [
            executor.submit(worker, job_id, turn, wait_seconds)
            for job_id, turn, wait_seconds in calls
        ]
        barrier.wait(timeout=3.0)
        results = [future.result(timeout=6.0) for future in futures]
    return results, time.monotonic() - started


def _payloads(results: list) -> list[dict]:
    return [result.structured_content for result in results]


def _tracked_state(tracker: BlockingWallTracker, turn: str):
    return tracker._states[("phase2-concurrent/1", turn)]


def _assert_no_active_leases(tracker: BlockingWallTracker) -> None:
    assert all(state.active_count == 0 for state in tracker._states.values())


def test_two_simultaneous_waits_charge_one_two_second_window(concurrency_env, tmp_path):
    tracker = concurrency_env
    job_id = _start_job(tmp_path)

    results, elapsed = _parallel_status(
        [(job_id, "turn-two", 2), (job_id, "turn-two", 2)]
    )
    payloads = _payloads(results)
    state = _tracked_state(tracker, "turn-two")

    assert all(payload["state"] == "running" for payload in payloads)
    assert all(payload["blocking_policy"] == "tracked" for payload in payloads)
    assert all(payload["wait_effective_s"] == 2 for payload in payloads)
    assert all(1.5 <= payload["waited_s"] <= 3.0 for payload in payloads)
    assert 1.5 <= elapsed <= 3.5
    assert 1.5 <= state.spent_s <= 2.8
    assert state.spent_s < 3.0
    _assert_no_active_leases(tracker)


def test_five_simultaneous_waits_charge_one_one_second_window(
    concurrency_env, tmp_path
):
    tracker = concurrency_env
    job_id = _start_job(tmp_path)

    results, elapsed = _parallel_status([(job_id, "turn-five", 1) for _ in range(5)])
    payloads = _payloads(results)
    state = _tracked_state(tracker, "turn-five")

    assert all(payload["state"] == "running" for payload in payloads)
    assert all(payload["blocking_policy"] == "tracked" for payload in payloads)
    assert all(payload["wait_effective_s"] == 1 for payload in payloads)
    assert all(0.7 <= payload["waited_s"] <= 2.0 for payload in payloads)
    assert 0.7 <= elapsed <= 2.5
    assert 0.7 <= state.spent_s <= 1.8
    assert state.spent_s < 2.0
    _assert_no_active_leases(tracker)


def test_second_wave_shares_original_deadline(concurrency_env, tmp_path, monkeypatch):
    tracker = concurrency_env
    job_id = _start_job(tmp_path)
    first_wait_entered = threading.Event()
    original_wait = js._wait_for_exit
    wait_calls = 0
    wait_calls_lock = threading.Lock()

    def observed_wait(job_id: str, wait_seconds: int):
        nonlocal wait_calls
        with wait_calls_lock:
            wait_calls += 1
            if wait_calls == 1:
                first_wait_entered.set()
        return original_wait(job_id, wait_seconds)

    monkeypatch.setattr(js, "_wait_for_exit", observed_wait)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            _call_status, job_id=job_id, turn="turn-wave", wait_seconds=2
        )
        assert first_wait_entered.wait(timeout=2.0)
        time.sleep(0.25)
        second = executor.submit(
            _call_status, job_id=job_id, turn="turn-wave", wait_seconds=3
        )
        first_result = first.result(timeout=5.0)
        second_result = second.result(timeout=5.0)

    first_payload = first_result.structured_content
    second_payload = second_result.structured_content
    state = _tracked_state(tracker, "turn-wave")

    assert first_payload["wait_effective_s"] == 2
    assert second_payload["blocking_policy"] == "tracked"
    assert second_payload["wait_effective_s"] == 2
    assert second_payload["blocking_remaining_s"] < 1.0
    assert 1.8 <= state.spent_s <= 3.0
    _assert_no_active_leases(tracker)


def test_different_jobs_same_turn_share_one_budget(concurrency_env, tmp_path):
    tracker = concurrency_env
    first_job = _start_job(tmp_path)
    second_job = _start_job(tmp_path)

    results, _ = _parallel_status(
        [
            (first_job, "turn-shared-jobs", 2),
            (second_job, "turn-shared-jobs", 2),
        ]
    )
    payloads = _payloads(results)
    state = _tracked_state(tracker, "turn-shared-jobs")

    assert {payload["job_id"] for payload in payloads} == {first_job, second_job}
    assert all(payload["blocking_policy"] == "tracked" for payload in payloads)
    assert 1.5 <= state.spent_s <= 2.8
    assert len(tracker._states) == 1
    _assert_no_active_leases(tracker)


def test_different_turns_keep_independent_deadlines(concurrency_env, tmp_path):
    tracker = concurrency_env
    job_id = _start_job(tmp_path)

    results, _ = _parallel_status([(job_id, "turn-a", 2), (job_id, "turn-b", 2)])
    payloads = _payloads(results)
    first = _tracked_state(tracker, "turn-a")
    second = _tracked_state(tracker, "turn-b")

    assert all(payload["blocking_policy"] == "tracked" for payload in payloads)
    assert all(payload["wait_effective_s"] == 2 for payload in payloads)
    assert 1.5 <= first.spent_s <= 2.8
    assert 1.5 <= second.spent_s <= 2.8
    assert len(tracker._states) == 2
    _assert_no_active_leases(tracker)


def test_one_turn_can_exhaust_while_another_retains_budget(concurrency_env, tmp_path):
    tracker = concurrency_env
    job_id = _start_job(tmp_path)

    first_results, _ = _parallel_status(
        [(job_id, "turn-exhaust", 3), (job_id, "turn-retain", 1)]
    )
    first_payloads = _payloads(first_results)
    assert {payload["blocking_policy"] for payload in first_payloads} == {"tracked"}

    exhausted = _call_status(
        job_id=job_id, turn="turn-exhaust", wait_seconds=1
    ).structured_content
    retained = _call_status(
        job_id=job_id, turn="turn-retain", wait_seconds=1
    ).structured_content

    exhausted_state = _tracked_state(tracker, "turn-exhaust")
    retained_state = _tracked_state(tracker, "turn-retain")

    assert exhausted["state"] == "running"
    assert exhausted["blocking_policy"] == "exhausted"
    assert exhausted["wait_effective_s"] == 0
    assert exhausted["blocking_budget_exhausted"] is True
    assert retained["blocking_policy"] == "tracked"
    assert retained["wait_effective_s"] >= 1
    assert retained["blocking_budget_exhausted"] is False
    assert exhausted_state.spent_s >= 2.5
    assert retained_state.spent_s < exhausted_state.spent_s
    assert retained_state.spent_s < 2.8
    _assert_no_active_leases(tracker)


def test_fresh_tracker_loses_only_ephemeral_budget_state(
    concurrency_env, tmp_path, monkeypatch
):
    old_tracker = concurrency_env
    job_id = _start_job(tmp_path)

    first = _call_status(
        job_id=job_id, turn="turn-reload", wait_seconds=1
    ).structured_content
    old_state = _tracked_state(old_tracker, "turn-reload")
    assert first["state"] == "running"
    assert 0.7 <= old_state.spent_s <= 1.8

    fresh_tracker = BlockingWallTracker()
    monkeypatch.setattr(js, "blocking_wall_tracker", fresh_tracker)

    observed = _call_status(
        job_id=job_id, turn="turn-reload", wait_seconds=0
    ).structured_content
    assert observed["state"] == "running"

    after_reload = _call_status(
        job_id=job_id, turn="turn-reload", wait_seconds=1
    ).structured_content
    fresh_state = _tracked_state(fresh_tracker, "turn-reload")

    assert after_reload["blocking_policy"] == "tracked"
    assert after_reload["blocking_budget_s"] == 3
    assert after_reload["wait_effective_s"] == 1
    assert 0.7 <= fresh_state.spent_s <= 1.8
    assert fresh_state.spent_s < old_state.spent_s + 0.5

    stopped = stop(job_id)
    assert stopped["state"] == "exited"
    assert stopped["signal"] in (15, 9)
    _assert_no_active_leases(fresh_tracker)
