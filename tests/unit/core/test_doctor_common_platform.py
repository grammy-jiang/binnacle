import subprocess

from binnacle import doctor_common
from binnacle.platform import deployment_platform
from binnacle.platform.contracts.service_lifecycle_contracts import ManagedServiceStatus


def completed(argv, stdout="", rc=0):
    return subprocess.CompletedProcess(argv, rc, stdout=stdout, stderr="")


def test_systemctl_compatibility_facade_delegates_to_linux_provisioner(monkeypatch):
    seen = []

    class Provisioner:
        def systemctl(self, *args, check=True):
            seen.append((args, check))
            return completed(args, "active\n")

    monkeypatch.setattr(
        deployment_platform, "create_linux_provisioner", lambda: Provisioner()
    )

    proc = doctor_common.systemctl("is-active", "demo.service")

    assert proc.stdout == "active\n"
    assert seen == [(("is-active", "demo.service"), False)]


def test_default_unit_state_uses_semantic_service_inspector(monkeypatch):
    class Inspector:
        def status(self, service):
            assert service == "demo.service"
            return ManagedServiceStatus("deactivating", main_pid=9, restart_count=2)

    monkeypatch.setattr(
        deployment_platform, "create_service_inspector", lambda: Inspector()
    )

    assert doctor_common.unit_state("demo.service") == "deactivating"


def test_injected_runner_preserves_compatibility_state_and_property_behavior():
    def run(*args):
        if args[0] == "is-active":
            return completed(args, "active\n")
        return completed(args, "value\n")

    assert doctor_common.unit_state("demo.service", run) == "active"
    assert doctor_common.unit_property("demo.service", "After", run) == "value"


def test_legacy_doctor_common_module_alias_identity():
    import importlib

    from binnacle.diagnostics import doctor_common as owned

    assert doctor_common is owned
    assert importlib.import_module("binnacle.doctor_common") is owned
    assert importlib.import_module("binnacle.diagnostics.doctor_common") is owned
    assert doctor_common.unit_property.__defaults__ == (doctor_common.systemctl,)
