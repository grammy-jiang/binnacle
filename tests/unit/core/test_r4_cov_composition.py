"""Linux-runnable coverage for the R4 Darwin branches of the composition root."""

from typing import ClassVar

import pytest

from binnacle.platform import composition
from binnacle.platform.contracts import darwin_release_scope as rows
from binnacle.platform.darwin import (
    job_manager_client,
    process_backend,
    resource_accounting,
)

MANAGER_STATES = {
    tool: rows.DARWIN_MANAGER_RELEASE_SCOPE[tool].capability.state.value
    for tool in rows.COMMAND_TOOLS
}
EMBEDDED_STATES = {
    tool: rows.DARWIN_RELEASE_SCOPE[tool].capability.state.value
    for tool in rows.COMMAND_TOOLS
}


@pytest.fixture
def on_darwin(monkeypatch):
    monkeypatch.setattr(composition, "host_os_family", lambda system=None: "darwin")


class FakeProcess:
    instances: ClassVar[list] = []

    def __init__(self, foreground_runner=None):
        self.foreground_runner = foreground_runner
        self.validated = []
        FakeProcess.instances.append(self)

    def validate_release_states(self, states):
        self.validated.append(dict(states))


@pytest.fixture
def fake_process(monkeypatch):
    FakeProcess.instances = []
    monkeypatch.setattr(process_backend, "DarwinProcessBackend", FakeProcess)
    monkeypatch.setattr(
        resource_accounting, "DarwinResourceAccounting", lambda: "accounting"
    )
    return FakeProcess


def test_validate_states_linux_and_manager_skip_process_check(
    fake_process, monkeypatch
):
    monkeypatch.setattr(composition, "host_os_family", lambda system=None: "linux")
    composition.validate_native_command_states(EMBEDDED_STATES, owner="embedded")
    monkeypatch.setattr(composition, "host_os_family", lambda system=None: "darwin")
    composition.validate_native_command_states(MANAGER_STATES, owner="manager")
    assert fake_process.instances == []


def test_validate_states_darwin_embedded_checks_process(on_darwin, fake_process):
    composition.validate_native_command_states(EMBEDDED_STATES, owner="embedded")
    assert fake_process.instances[0].validated == [EMBEDDED_STATES]

    observed = composition._ObservedForegroundExecution(FakeProcess(), "accounting")
    composition.validate_native_command_states(
        EMBEDDED_STATES, owner="embedded", execution=observed
    )
    assert observed.process.validated == [EMBEDDED_STATES]


def test_create_job_client_requires_darwin(monkeypatch):
    monkeypatch.setattr(composition, "host_os_family", lambda system=None: "linux")
    with pytest.raises(composition.UnsupportedHostOS):
        composition.create_job_client()


def test_create_job_client_on_darwin(on_darwin, monkeypatch):
    monkeypatch.setattr(job_manager_client, "DarwinJobClient", lambda: "client")
    assert composition.create_job_client() == "client"


@pytest.mark.parametrize("owner", ["manager", "embedded"])
def test_native_file_capability_on_darwin(on_darwin, fake_process, owner):
    capability = composition.native_file_capability(owner=owner)
    scope = rows.release_scope_for_owner(owner)
    assert capability in [scope[tool].capability for tool in rows.FILE_TOOLS]


def test_native_file_capability_on_linux(monkeypatch, fake_process):
    monkeypatch.setattr(composition, "host_os_family", lambda system=None: "linux")
    assert composition.native_file_capability(owner="manager") is None


def test_create_foreground_execution_requires_darwin(monkeypatch):
    monkeypatch.setattr(composition, "host_os_family", lambda system=None: "linux")
    with pytest.raises(composition.UnsupportedHostOS):
        composition.create_foreground_execution(owner="embedded")


@pytest.mark.parametrize("limited", [True, False])
def test_create_foreground_execution_on_darwin(
    on_darwin, fake_process, monkeypatch, limited
):
    runners = []

    class Runner:
        def __init__(self, limit, wait_max):
            runners.append((limit, wait_max))

    monkeypatch.setattr(process_backend, "_ForegroundRunner", Runner)
    monkeypatch.setattr(
        composition, "validate_native_command_states", lambda *a, **k: None
    )
    states = {"run_command": "LIMITED"} if limited else None
    execution = composition.create_foreground_execution(
        owner="embedded", command_states=states, foreground_limit_s=7, wait_max_s=9
    )
    assert isinstance(execution, composition._ObservedForegroundExecution)
    assert execution.accounting == "accounting"
    assert runners == ([(7, 9)] if limited else [])
    assert (execution.process.foreground_runner is not None) is limited


def test_observed_foreground_binds_reaper_usage_to_accounting():
    from threading import Event

    from binnacle.platform.contracts.darwin_contracts import ForegroundResult

    recorded = []

    class Accounting:
        def record_direct_child_exit(self, observation_id, usage):
            recorded.append((observation_id, usage))

    class Process:
        def run_foreground(self, request, *, cancel, on_direct_child_exit):
            on_direct_child_exit({"cpu_s": 0.5})
            return ForegroundResult("old", "gen", 0, None, b"", 0, False, 0.1, True)

    observed = composition._ObservedForegroundExecution(Process(), Accounting())
    result = observed.run_foreground(object(), cancel=Event())
    assert result.execution_id != "old" and len(result.execution_id) == 32
    assert recorded == [(result.execution_id, {"cpu_s": 0.5})]
