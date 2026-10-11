"""E2 S5: the controller terminal point (``deferred_seal`` + ``seal``)."""

import asyncio

import pytest

from binnacle.features.commands.job_awareness import session_serving as serving
from binnacle.features.commands.job_awareness.session_lab import LabConfig
from tests.integration.job_awareness.emission_support import (
    ORIGINAL,
    Adapter,
    allocate,
    binding_of,
    emit_states,
    run,
)
from tests.unit.core.job_awareness.session_support import make_lab

DEFERRED = LabConfig(deferred_seal=True)


def seal(lab, name, handle):
    return asyncio.run(serving.seal(lab.lab, lab.key(name), handle))


def test_config_rejects_a_non_bool_deferred_seal():
    with pytest.raises(ValueError, match="Invalid lab config"):
        LabConfig(deferred_seal=1)


def test_default_allocation_is_terminal_at_once(tmp_path):
    lab = make_lab(tmp_path / "phase")
    (handle,) = allocate(lab, "A", 1)
    (entry,) = binding_of(lab, "A").jobs.values()
    assert entry.terminal is True
    assert seal(lab, "A", handle) is False  # already terminal: no change


def test_deferred_job_is_not_hinted_until_sealed(tmp_path):
    lab = make_lab(tmp_path / "phase", config=DEFERRED)
    first, second = allocate(lab, "A", 2)
    adapter = Adapter()
    assert run(lab, "A", adapter) is ORIGINAL and adapter.routes == []
    assert seal(lab, "A", second) is True
    assert seal(lab, "A", second) is False
    result = run(lab, "A", adapter)
    (route,) = adapter.routes
    entries = {e.handle: e.job for e in binding_of(lab, "A").jobs.values()}
    assert route.jobs == (entries[second],)
    assert result["hint"] == [entries[second].canonical_key]
    states = emit_states(lab)
    assert states[entries[first].canonical_key] == "PENDING"
    assert any(e.get("event") == "ja_sealed" for e in lab.events)


def test_seal_is_owner_scoped_and_refuses_unknown_or_suspended(tmp_path):
    lab = make_lab(tmp_path / "phase", config=DEFERRED)
    (handle,) = allocate(lab, "A", 1)
    assert seal(lab, "B", handle) is False  # no binding for B
    allocate(lab, "B", 1)
    assert seal(lab, "B", handle) is False  # foreign handle
    assert seal(lab, "A", "j_000000000000") is False
    assert asyncio.run(serving.suspend(lab.lab, lab.key("A"))) is True
    assert seal(lab, "A", handle) is False


def test_seal_times_out_without_the_fence(tmp_path):
    lab = make_lab(
        tmp_path / "phase", config=LabConfig(deferred_seal=True, fence_timeout_s=0.01)
    )
    (handle,) = allocate(lab, "A", 1)

    async def blocked():
        lock = lab.lab.fences.lock(lab.key("A").kd)
        await lock.acquire()
        try:
            return await serving.seal(lab.lab, lab.key("A"), handle)
        finally:
            lock.release()

    assert asyncio.run(blocked()) is False
    (entry,) = binding_of(lab, "A").jobs.values()
    assert entry.terminal is False
