"""OI-04/OI-06: Core stop policy operates on opaque fake native identities."""

import logging
from types import SimpleNamespace

import pytest

from binnacle.features.commands import job_stop
from binnacle.platform.contracts.process_contracts import UnverifiedJobProcess


def scenario(*, state="running", identity=None, open_error=None, signals_error=None):
    events = []
    lease = SimpleNamespace(
        signal=lambda intent: (
            events.append(("signal", intent))
            if intent != signals_error
            else (_ for _ in ()).throw(ProcessLookupError())
        ),
        close=lambda: events.append(("close",)),
    )
    backend = SimpleNamespace(
        identity_from_record=lambda meta: (
            events.append(("identity", meta.get("pid"))) or identity
        ),
        open_job_signals=lambda token: (
            (_ for _ in ()).throw(open_error)
            if open_error is not None
            else events.append(("open", token)) or lease
        ),
    )
    data = {"state": state, "pid": 10, "pgid": 10}

    def read_meta(job):
        events.append(("meta", job))
        return {"pid": 10, "starttime": 123}

    def stop(wait_results):
        iterator = iter(wait_results)
        return job_stop.stop_embedded(
            "fake-job",
            process_backend=backend,
            job_state=lambda job: data,
            read_meta=read_meta,
            await_exit=lambda job, timeout: (
                events.append(("wait", timeout)) or next(iterator)
            ),
            stop_sigterm_grace_s=1.5,
            stop_sigkill_grace_s=0.75,
            current_call_id=lambda: "synthetic-call",
            logger=logging.getLogger("test.binnacle.job_stop"),
        )

    return stop, events


def test_no_identity_or_untrusted_lease_never_emits_signal():
    stop, events = scenario(identity=None)
    assert stop([])["state"] == "running"
    assert all(item[0] != "signal" for item in events)

    stop, events = scenario(identity=object(), open_error=UnverifiedJobProcess())
    assert stop([])["state"] == "running"
    assert all(item[0] != "signal" for item in events)


def test_opaque_fake_lease_terminates_once_then_closes():
    stop, events = scenario(identity=object())
    state = {"state": "exited", "signal": 15}
    assert stop([state]) is state
    assert [e[0] for e in events].count("signal") == 1
    assert events[-1] == ("close",)


def test_escalation_uses_same_pinned_lease():
    stop, events = scenario(identity=object())
    final = {"state": "exited", "signal": 9}
    assert stop([{"state": "running"}, final]) == final
    assert [item for item in events if item[0] == "signal"] == [
        ("signal", "terminate"),
        ("signal", "kill"),
    ]
    assert [item for item in events if item[0] == "open"]
    assert events[-1] == ("close",)


def test_process_disappearance_during_term_waits_and_closes():
    stop, events = scenario(identity=object(), signals_error="terminate")
    assert stop([{"state": "exited"}])["state"] == "exited"
    assert events[-1] == ("close",)


def test_unknown_or_terminal_states_do_not_acquire_native_lease():
    stop, events = scenario(state="exited", identity=object())
    assert stop([])["state"] == "exited"
    assert events == []
    stop, events = scenario(state="unknown", identity=object())
    assert stop([])["state"] == "unknown"
    assert events == [("meta", "fake-job")]


def test_native_partial_termination_is_reported_even_if_leader_exits(caplog):
    """Do not claim full completion when a verified child could not be stopped."""
    from binnacle.platform.contracts.process_contracts import JobSignalDeliveryError

    stop, events = scenario(identity=object())
    # Replace fixture's signal closure using the same synthetic backend.
    # A special lease is substituted at native open time in a direct test below.
    assert callable(stop)
    assert events == []

    signals = []
    lease = SimpleNamespace(
        signal=lambda intent: (
            signals.append(intent)
            or (_ for _ in ()).throw(
                JobSignalDeliveryError("one unsignalable descendant")
            )
        ),
        close=lambda: signals.append("close"),
    )
    backend = SimpleNamespace(
        identity_from_record=lambda meta: object(),
        open_job_signals=lambda ident: lease,
    )
    with (
        caplog.at_level("ERROR", logger="binnacle.jobs"),
        pytest.raises(JobSignalDeliveryError, match="unsignalable descendant"),
    ):
        job_stop.stop_embedded(
            "fakesignal001",
            process_backend=backend,
            job_state=lambda job: {"state": "running"},
            read_meta=lambda job: {"pid": 55, "starttime": 44},
            await_exit=lambda job, timeout: {"state": "exited"},
            stop_sigterm_grace_s=1,
            stop_sigkill_grace_s=1,
            current_call_id=lambda: "test",
            logger=logging.getLogger("binnacle.jobs"),
        )
    assert signals == ["terminate", "close"]
    assert "event=job_stop_signal_partial" in caplog.text


def test_partial_sigterm_and_sigkill_both_attempted_without_false_success():
    from binnacle.platform.contracts.process_contracts import JobSignalDeliveryError

    history = []
    states = iter([{"state": "running"}, {"state": "exited"}])

    def signal_owned(intent):
        history.append(intent)
        raise JobSignalDeliveryError(f"partial {intent}")

    lease = SimpleNamespace(signal=signal_owned, close=lambda: history.append("close"))
    backend = SimpleNamespace(
        identity_from_record=lambda meta: object(),
        open_job_signals=lambda ident: lease,
    )
    with pytest.raises(JobSignalDeliveryError) as caught:
        job_stop.stop_embedded(
            "fakesignal002",
            process_backend=backend,
            job_state=lambda job: {"state": "running"},
            read_meta=lambda job: {"pid": 77, "starttime": 66},
            await_exit=lambda job, timeout: next(states),
            stop_sigterm_grace_s=1,
            stop_sigkill_grace_s=1,
            current_call_id=lambda: "test",
            logger=logging.getLogger("test.binnacle.job_stop"),
        )
    assert "partial terminate" in str(caught.value)
    assert "partial kill" in str(caught.value)
    assert history == ["terminate", "kill", "close"]


def test_partial_kill_only_still_returns_explicit_delivery_failure():
    from binnacle.platform.contracts.process_contracts import JobSignalDeliveryError

    history = []
    lease = SimpleNamespace(
        signal=lambda intent: (
            history.append(intent)
            or (
                (_ for _ in ()).throw(JobSignalDeliveryError("partial KILL"))
                if intent == "kill"
                else None
            )
        ),
        close=lambda: history.append("close"),
    )
    backend = SimpleNamespace(
        identity_from_record=lambda meta: object(),
        open_job_signals=lambda ident: lease,
    )
    responses = iter([{"state": "running"}, {"state": "exited"}])
    with pytest.raises(JobSignalDeliveryError, match="partial KILL"):
        job_stop.stop_embedded(
            "fakesignal003",
            process_backend=backend,
            job_state=lambda job: {"state": "running"},
            read_meta=lambda job: {"pid": 77, "starttime": 66},
            await_exit=lambda job, timeout: next(responses),
            stop_sigterm_grace_s=1,
            stop_sigkill_grace_s=1,
            current_call_id=lambda: "test",
            logger=logging.getLogger("test.binnacle.job_stop"),
        )
    assert history == ["terminate", "kill", "close"]
