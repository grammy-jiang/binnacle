"""OBS-01..03: metadata-only observation after fresh shared authority."""

from copy import copy

import pytest

from binnacle.features.commands.job_awareness.models import (
    ErrorCode,
    Observation,
    ObservationState,
    Scope,
    Success,
    TerminalKind,
    TerminalOutcome,
)
from binnacle.features.commands.job_awareness.observation import JobObserver
from tests.contracts.job_awareness.fakes import FakeHandleAuthority
from tests.unit.core.job_awareness.test_snapshots import (
    CountingCatalog,
    assert_error,
    enroll,
    job_ref,
    setup_store,
)


@pytest.mark.parametrize(
    "outcome",
    [
        None,
        TerminalOutcome(TerminalKind.EXIT_CODE, 0),
        TerminalOutcome(TerminalKind.EXIT_CODE, 7),
        TerminalOutcome(TerminalKind.SIGNAL, 9),
    ],
)
def test_state_projection(tmp_path, outcome):
    authority = FakeHandleAuthority()
    catalog = CountingCatalog()
    job = job_ref()
    grant = authority.issue((job,))
    observer = JobObserver(authority, catalog, lambda: 1000)
    assert_error(observer.observe(grant, job), ErrorCode.SOURCE_UNAVAILABLE)
    if outcome:
        snapshot, source = enroll(catalog, tmp_path, terminal=outcome)
        observation = observer.observe(grant, job).value
        assert observation.state is ObservationState.TERMINAL
        assert observation.terminal == outcome and observation.snapshot == snapshot
        assert source.reads == 0
    else:
        for state in (ObservationState.RUNNING, ObservationState.UNKNOWN):
            assert isinstance(
                catalog.register(Observation(job, state, None, None)), Success
            )
            assert observer.observe(grant, job).value == Observation(
                job, state, None, None
            )


def test_legacy_source_has_no_seal(tmp_path):
    authority = FakeHandleAuthority()
    catalog = CountingCatalog()
    job = job_ref()
    grant = authority.issue((job,))
    observer = JobObserver(authority, catalog, lambda: 1000)
    file = tmp_path / "simulated-descendant"
    file.write_bytes(b"leader exited")
    catalog.register(
        Observation(
            job,
            ObservationState.TERMINAL,
            TerminalOutcome(TerminalKind.EXIT_CODE, 0),
            None,
        )
    )
    for _ in range(2):
        assert_error(observer.observe(grant, job), ErrorCode.SOURCE_UNSEALED)
    with file.open("ab") as stream:
        stream.write(b"descendant still writing")
    assert_error(observer.observe(grant, job), ErrorCode.SOURCE_UNSEALED)


@pytest.mark.parametrize(
    "denial",
    [
        "copy",
        "foreign",
        "expired",
        "revoked",
        "epoch",
        "generation",
        "unavailable",
        "observe_only",
        "read_only",
    ],
)
def test_authority_precedes_all_source_reads(tmp_path, denial):
    authority, catalog, snap, source, grant, _, store = setup_store(tmp_path)
    observer = JobObserver(authority, catalog, lambda: authority.now_ms)
    assert isinstance(observer.observe(grant, snap.job), Success)
    with store.open_verified(grant, snap).value:
        pass
    if denial == "copy":
        grant = copy(grant)
    elif denial == "foreign":
        grant = authority.issue((job_ref(2),))
    elif denial == "expired":
        authority.now_ms += 3600000
    elif denial == "revoked":
        authority.revoke(grant)
    elif denial == "epoch":
        authority.rotate_epoch()
    elif denial == "generation":
        authority.reissue(grant)
    elif denial == "unavailable":
        authority.available = False
    elif denial == "observe_only":
        grant = authority.issue((snap.job,), scopes=frozenset({Scope.OBSERVE}))
    else:
        grant = authority.issue((snap.job,), scopes=frozenset({Scope.READ}))
    catalog.lookups = source.reads = 0
    checks = authority.check_calls
    if denial != "observe_only":
        assert_error(observer.observe(grant, snap.job), ErrorCode.DENIED)
    if denial != "read_only":
        assert_error(store.open_verified(grant, snap), ErrorCode.DENIED)
    assert catalog.lookups == source.reads == 0
    assert authority.check_calls > checks


def test_unknown_and_foreign_denials_identical(tmp_path):
    authority, catalog, snap, _, grant, _, store = setup_store(tmp_path)
    authority.revoke(grant)
    observer = JobObserver(authority, catalog, lambda: 1000)
    assert observer.observe(grant, snap.job) == observer.observe(grant, job_ref(99))
    assert catalog.lookups == 0
    assert_error(store.open_verified(grant, snap), ErrorCode.DENIED)


def test_unsealed_read_and_catalog_failures(tmp_path):
    authority, catalog, snap, source, grant, _, store = setup_store(tmp_path)
    from binnacle.features.commands.job_awareness.snapshots import SnapshotStore

    empty = CountingCatalog()
    empty.register(
        Observation(snap.job, ObservationState.TERMINAL, snap.terminal, None)
    )
    unsealed = SnapshotStore(authority, empty, lambda: 1000)
    assert_error(unsealed.open_verified(grant, snap), ErrorCode.SOURCE_UNSEALED)
    assert source.reads == 0
    source.path.unlink()
    assert_error(store.open_verified(grant, snap), ErrorCode.SOURCE_UNAVAILABLE)
    observer = JobObserver(authority, catalog, lambda: 1000)
    assert_error(observer.observe(grant, snap.job), ErrorCode.SOURCE_UNAVAILABLE)


@pytest.mark.parametrize("time", [999, True, -1, 9007199254740992])
def test_unsafe_snapshot_clock(tmp_path, time):
    authority, catalog, snap, _, grant, _, _ = setup_store(tmp_path)
    observer = JobObserver(authority, catalog, lambda: time)
    assert_error(observer.observe(grant, snap.job), ErrorCode.CLOCK_UNSAFE)
