from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from scripts import chat_scheduling_historical_guard as historical


def _acquire(
    tracker: historical.HistoricalOneShotTracker,
    *,
    client: str = "openai-mcp(ChatGPT)",
    turn: str = "turn-1",
    bounded_wait_s: int = 50,
):
    return tracker.acquire(
        client=client,
        turn=turn,
        requested_wait_s=bounded_wait_s,
        bounded_wait_s=bounded_wait_s,
        budget_s=999,
    )


def test_first_wait_is_capped_and_later_wait_is_nonblocking():
    tracker = historical.HistoricalOneShotTracker()
    first = _acquire(tracker)
    assert first.decision.policy == "historical_one_shot"
    assert first.decision.effective_wait_s == 10
    assert first.decision.budget_s == 10
    assert first.decision.blocking_budget_exhausted is False
    release = first.release()
    assert release.remaining_after_s == 0.0

    later = _acquire(tracker)
    assert later.decision.policy == "historical_one_shot_exhausted"
    assert later.decision.effective_wait_s == 0
    assert later.decision.blocking_budget_exhausted is True


def test_independent_turns_each_receive_one_shot():
    tracker = historical.HistoricalOneShotTracker()
    one = _acquire(tracker, turn="turn-1")
    two = _acquire(tracker, turn="turn-2")
    assert one.decision.effective_wait_s == 10
    assert two.decision.effective_wait_s == 10
    one.release()
    two.release()


def test_independent_clients_do_not_share_turn_state():
    tracker = historical.HistoricalOneShotTracker()
    one = _acquire(tracker, client="openai-mcp-one", turn="same")
    two = _acquire(tracker, client="openai-mcp-two", turn="same")
    assert one.decision.effective_wait_s == 10
    assert two.decision.effective_wait_s == 10
    one.release()
    two.release()


def test_concurrent_acquisitions_on_one_turn_allow_exactly_one_positive_wait():
    tracker = historical.HistoricalOneShotTracker()

    with ThreadPoolExecutor(max_workers=8) as pool:
        leases = list(pool.map(lambda _: _acquire(tracker), range(8)))

    decisions = [lease.decision for lease in leases]
    assert sum(decision.effective_wait_s > 0 for decision in decisions) == 1
    assert sum(decision.blocking_budget_exhausted for decision in decisions) == 7
    for lease in leases:
        lease.release()


def test_release_is_idempotent():
    now = [100.0]
    tracker = historical.HistoricalOneShotTracker(clock=lambda: now[0])
    lease = _acquire(tracker)
    now[0] += 2.5
    first = lease.release()
    now[0] += 5.0
    second = lease.release()
    assert first is second
    assert first.window_wall_s == 2.5
    assert first.remaining_after_s == 0.0


def test_early_job_exit_still_exhausts_later_waits():
    now = [1.0]
    tracker = historical.HistoricalOneShotTracker(clock=lambda: now[0])
    first = _acquire(tracker)
    now[0] += 0.25
    release = first.release()
    assert release.window_wall_s == 0.25

    later = _acquire(tracker)
    assert later.decision.effective_wait_s == 0
    assert later.decision.blocking_budget_exhausted is True


def test_missing_turn_uses_compatible_untracked_decision():
    tracker = historical.HistoricalOneShotTracker()
    lease = tracker.acquire(
        client="openai-mcp",
        turn=None,
        requested_wait_s=7,
        bounded_wait_s=7,
        budget_s=10,
    )
    assert lease.decision.policy == "no_turn"
    assert lease.decision.effective_wait_s == 7
    assert lease.decision.budget_s is None
    assert lease.release().remaining_after_s is None


def test_install_historical_tracker_replaces_job_status_tracker(monkeypatch):
    from binnacle.tools import job_status

    sentinel = object()
    monkeypatch.setattr(job_status, "blocking_wall_tracker", sentinel)
    tracker = historical.install_historical_tracker()
    assert isinstance(tracker, historical.HistoricalOneShotTracker)
    assert job_status.blocking_wall_tracker is tracker


def test_h_server_installs_adapter_before_uvicorn(monkeypatch):
    events: list[object] = []
    monkeypatch.setattr(
        historical,
        "install_historical_tracker",
        lambda: events.append("installed"),
    )

    def run(*args, **kwargs):
        events.append((args, kwargs))

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=run))
    historical.serve("127.0.0.1", 8115)

    assert events[0] == "installed"
    args, kwargs = events[1]
    assert args == ("binnacle.server:app",)
    assert kwargs == {
        "host": "127.0.0.1",
        "port": 8115,
        "reload": False,
        "loop": "uvloop",
        "http": "httptools",
    }
