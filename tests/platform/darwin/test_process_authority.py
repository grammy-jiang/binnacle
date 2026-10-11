"""Portable authority-denial tests; no test signals a numeric real process."""

from __future__ import annotations

import os
import signal
from dataclasses import asdict, replace
from threading import Event, Thread

import pytest

from binnacle.platform.contracts.capability_contracts import (
    AuthorityUnknown,
    CapabilityState,
    CapabilityUnavailable,
    GenerationMismatch,
)
from binnacle.platform.contracts.darwin_contracts import OwnerGeneration
from binnacle.platform.contracts.process_contracts import (
    JobProcessIdentity,
    UnverifiedJobProcess,
)
from binnacle.platform.darwin import process_authority, witness_protocol
from binnacle.platform.darwin.process_authority import (
    _ForegroundOwner,
    observe_authority,
)
from binnacle.platform.darwin.process_backend import DarwinProcessBackend
from binnacle.platform.darwin.witness_protocol import DarwinWitness

GENERATION = OwnerGeneration("manager-1", "witness-1", "job-1")


class Channel:
    def __init__(self):
        self.payloads = []
        self.closed = 0
        self.mutate = lambda reply: reply

    def request(self, payload, *, timeout_s):
        assert 0 < timeout_s <= 1
        self.payloads.append(payload)
        return self.mutate({**payload, "enrolled": True})

    def close(self):
        self.closed += 1


def assert_unknown(observation):
    assert observation.capability.state is CapabilityState.UNKNOWN
    assert observation.generation is None
    assert not observation.membership_closed
    assert not observation.can_signal


def test_positive_enrollment_is_observation_only():
    channel = Channel()
    witness = DarwinWitness(channel, GENERATION)
    observation = observe_authority("job-1", witness=witness)
    assert observation.capability.state is CapabilityState.LIMITED
    assert observation.generation == GENERATION
    assert not observation.can_signal and not observation.membership_closed
    assert witness.reconnect(GENERATION).generation == GENERATION
    assert channel.payloads[0]["challenge"] != channel.payloads[1]["challenge"]
    assert channel.payloads[0]["generation"] == asdict(GENERATION)


@pytest.mark.parametrize(
    "field,value",
    [
        ("enrolled", False),
        ("enrolled", 1),
        ("enrolled", "true"),
        ("challenge", "replay"),
        ("operation", "stop"),
        ("protocol", "unknown"),
        ("generation", {}),
        ("generation", asdict(replace(GENERATION, manager_epoch="stale"))),
        ("generation", asdict(replace(GENERATION, witness_epoch="stale"))),
        ("generation", asdict(replace(GENERATION, job_id="foreign"))),
    ],
)
def test_replay_wrong_generation_and_nonpositive_enrollment_fail_closed(field, value):
    channel = Channel()
    channel.mutate = lambda reply: {**reply, field: value}
    assert_unknown(DarwinWitness(channel, GENERATION).observe("job-1"))


def test_no_cached_success_after_witness_crash():
    channel = Channel()
    witness = DarwinWitness(channel, GENERATION)
    assert witness.observe("job-1").generation == GENERATION

    def crash(reply):
        raise BrokenPipeError("secret native details")

    channel.mutate = crash
    observation = witness.observe("job-1")
    assert_unknown(observation)
    assert "secret" not in repr(observation)
    assert_unknown(observe_authority("job-1", witness=None))


def test_late_or_malformed_witness_response_never_restores_authority(monkeypatch):
    ticks = iter((0.0, 1.01))
    monkeypatch.setattr(witness_protocol.time, "monotonic", lambda: next(ticks))
    assert_unknown(DarwinWitness(Channel(), GENERATION).observe("job-1"))
    monkeypatch.setattr(witness_protocol.time, "monotonic", lambda: 0.0)
    channel = Channel()
    channel.mutate = lambda reply: None
    assert_unknown(DarwinWitness(channel, GENERATION).observe("job-1"))


def test_reconnect_never_adopts_a_new_manager_or_job():
    channel = Channel()
    witness = DarwinWitness(channel, GENERATION)
    for generation in (
        replace(GENERATION, manager_epoch="manager-2"),
        replace(GENERATION, witness_epoch="witness-2"),
        replace(GENERATION, job_id="job-2"),
    ):
        with pytest.raises(GenerationMismatch):
            witness.reconnect(generation)
    with pytest.raises(GenerationMismatch):
        witness.observe("job-2")
    assert not channel.payloads
    assert_unknown(observe_authority("job-2", witness=witness))


def test_empty_generation_and_closed_witness():
    channel = Channel()
    with pytest.raises(GenerationMismatch):
        DarwinWitness(channel, replace(GENERATION, manager_epoch=""))
    witness = DarwinWitness(channel, GENERATION)
    witness.close()
    witness.close()
    assert channel.closed == 1
    assert_unknown(witness.observe("job-1"))
    assert not channel.payloads


def test_inherited_witness_does_not_use_inherited_channel(monkeypatch):
    channel = Channel()
    witness = DarwinWitness(channel, GENERATION)
    pid = os.getpid()
    monkeypatch.setattr(os, "getpid", lambda: pid + 1)
    assert_unknown(witness.observe("job-1"))
    witness.close()
    assert not channel.payloads and channel.closed == 0


def test_witness_cannot_promote_membership_or_signal_rights():
    observation = DarwinWitness(Channel(), GENERATION).observe("job-1")

    class LyingWitness:
        def observe(self, job_id):
            return replace(observation, can_signal=True, membership_closed=True)

    result = observe_authority("job-1", witness=LyingWitness())
    assert not result.membership_closed and not result.can_signal


def test_legacy_pid_metadata_never_becomes_a_darwin_identity(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("historic PID/PGID was consulted or signaled")

    monkeypatch.setattr(os, "kill", forbidden)
    monkeypatch.setattr(os, "killpg", forbidden)
    monkeypatch.setattr(os, "waitpid", forbidden)
    backend = DarwinProcessBackend(witness=DarwinWitness(Channel(), GENERATION))
    for pid in (-1, 0, 1, 999999):
        assert (
            backend.identity_from_record({"pid": pid, "pgid": pid, "starttime": 1})
            is None
        )
        assert backend.starttime(pid) is None
        with pytest.raises(AuthorityUnknown):
            backend.alive(pid, 1)
        with pytest.raises(AuthorityUnknown):
            backend.processes(pid)
        with pytest.raises(AuthorityUnknown):
            backend.descendants(pid)
        with pytest.raises(CapabilityUnavailable):
            backend.signal_job(pid, {pid}, "kill")
    with pytest.raises(UnverifiedJobProcess):
        backend.open_job_signals(JobProcessIdentity({"pid": 1}))
    with pytest.raises(AuthorityUnknown):
        backend.inspect_job(JobProcessIdentity({"pid": 1}))
    with pytest.raises(AuthorityUnknown):
        backend.boot_id()


@pytest.fixture
def simulated_owner(monkeypatch):
    """Synthetic PID reuse/race injection, explicitly not native reuse proof."""
    monkeypatch.setattr(process_authority.sys, "platform", "darwin")
    monkeypatch.setattr(signal, "getsignal", lambda sig: signal.SIG_DFL)
    monkeypatch.setattr(os, "posix_spawn", lambda *a, **kw: 12345)
    return _ForegroundOwner(["/bin/bash"], env={}, file_actions=[])


def test_reaped_pid_reuse_cannot_reopen_signal_authority(simulated_owner, monkeypatch):
    calls = []
    monkeypatch.setattr(os, "waitpid", lambda pid, flags: (pid, 0))
    monkeypatch.setattr(os, "killpg", lambda *args: calls.append(args))
    owner = simulated_owner
    assert owner.poll(owner.generation) == 0
    # Model another process now occupying the same numeric identifier.
    monkeypatch.setattr(os, "waitpid", lambda *args: pytest.fail("second reap"))
    owner.cleanup(owner.generation)
    with pytest.raises(AuthorityUnknown):
        owner._signal_locked(signal.SIGKILL)
    assert not calls


def test_invalid_generation_and_different_parent_never_signal(
    simulated_owner, monkeypatch
):
    owner = simulated_owner
    monkeypatch.setattr(os, "killpg", lambda *args: pytest.fail("unowned signal"))
    monkeypatch.setattr(os, "waitpid", lambda *args: pytest.fail("unowned wait"))
    with pytest.raises(AuthorityUnknown):
        owner.cleanup("wrong-generation")
    pid = os.getpid()
    monkeypatch.setattr(os, "getpid", lambda: pid + 1)
    with pytest.raises(AuthorityUnknown):
        owner.cleanup(owner.generation)
    with pytest.raises(AuthorityUnknown):
        owner.poll(owner.generation)


def test_inherited_owner_with_recycled_parent_pid_is_still_rejected(
    simulated_owner, monkeypatch
):
    channel = Channel()
    witness = DarwinWitness(channel, GENERATION)
    # Same numeric owner PID, different process incarnation after a fork.
    monkeypatch.setattr(process_authority, "_PROCESS_TOKEN", object())
    monkeypatch.setattr(os, "killpg", lambda *args: pytest.fail("inherited signal"))
    monkeypatch.setattr(os, "waitpid", lambda *args: pytest.fail("inherited wait"))
    with pytest.raises(AuthorityUnknown):
        simulated_owner.cleanup(simulated_owner.generation)
    assert_unknown(witness.observe("job-1"))
    assert not channel.payloads


def test_competing_reap_loss_is_sticky_and_never_numeric_fallback(
    simulated_owner, monkeypatch
):
    def lost(*args):
        raise ChildProcessError()

    monkeypatch.setattr(os, "waitpid", lost)
    monkeypatch.setattr(os, "killpg", lambda *args: pytest.fail("signal after ECHILD"))
    owner = simulated_owner
    with pytest.raises(AuthorityUnknown):
        owner.poll(owner.generation)
    with pytest.raises(AuthorityUnknown):
        owner.cleanup(owner.generation)


def test_term_kill_precede_only_reap(simulated_owner, monkeypatch):
    owner = simulated_owner
    events = []
    monkeypatch.setattr(os, "killpg", lambda pid, sig: events.append(sig))

    def reap(pid, flags):
        events.append("reap")
        return pid, signal.SIGKILL

    monkeypatch.setattr(os, "waitpid", reap)
    owner.cleanup(owner.generation)
    owner.cleanup(owner.generation)
    assert events == [signal.SIGTERM, signal.SIGKILL, "reap"]


def test_concurrent_poll_cannot_reap_between_term_and_kill(
    simulated_owner, monkeypatch
):
    owner = simulated_owner
    term, release, poll_started, poll_finished = (Event() for _ in range(4))
    events = []
    failures = []

    def send(pid, number):
        events.append(number)
        if number == signal.SIGTERM:
            term.set()
            assert release.wait(2)

    def reap(pid, flags):
        events.append("reap")
        return pid, 0

    def cleanup():
        try:
            owner.cleanup(owner.generation)
        except (AuthorityUnknown, AssertionError) as exc:
            failures.append(exc)

    def poll():
        poll_started.set()
        try:
            owner.poll(owner.generation)
        except (AuthorityUnknown, AssertionError) as exc:
            failures.append(exc)
        finally:
            poll_finished.set()

    monkeypatch.setattr(os, "killpg", send)
    monkeypatch.setattr(os, "waitpid", reap)
    cleaner = Thread(target=cleanup)
    waiter = Thread(target=poll)
    cleaner.start()
    try:
        assert term.wait(1)
        waiter.start()
        assert poll_started.wait(1)
        assert not poll_finished.wait(0.05)
        assert events == [signal.SIGTERM]
    finally:
        release.set()
        cleaner.join(3)
        if waiter.ident is not None:
            waiter.join(3)
    assert not failures
    assert events == [signal.SIGTERM, signal.SIGKILL, "reap"]


def test_reap_timeout_reports_unknown_without_retry_adoption(
    simulated_owner, monkeypatch
):
    signals = []
    ticks = iter((0, 3))
    monkeypatch.setattr(process_authority.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(os, "waitpid", lambda *args: (0, 0))
    monkeypatch.setattr(os, "killpg", lambda pid, sig: signals.append(sig))
    with pytest.raises(AuthorityUnknown, match="darwin_foreground_reap_timeout"):
        simulated_owner.cleanup(simulated_owner.generation)
    with pytest.raises(AuthorityUnknown, match="darwin_foreground_owner_lost"):
        simulated_owner.cleanup(simulated_owner.generation)
    assert signals == [signal.SIGTERM, signal.SIGKILL]


def test_sigchld_handler_refused_before_spawn(monkeypatch):
    monkeypatch.setattr(process_authority.sys, "platform", "darwin")
    monkeypatch.setattr(signal, "getsignal", lambda sig: signal.SIG_IGN)
    monkeypatch.setattr(os, "posix_spawn", lambda *a, **kw: pytest.fail("spawn"))
    with pytest.raises(AuthorityUnknown):
        _ForegroundOwner(["/bin/bash"], env={}, file_actions=[])


def test_signal_failure_reaps_but_never_reports_cleanup_success(
    simulated_owner, monkeypatch
):
    def denied(*args):
        raise PermissionError("secret")

    monkeypatch.setattr(os, "killpg", denied)
    monkeypatch.setattr(os, "waitpid", lambda pid, flags: (pid, 0))
    with pytest.raises(AuthorityUnknown, match="descendants_unverified=true") as error:
        simulated_owner.cleanup(simulated_owner.generation)
    assert "secret" not in str(error.value)
