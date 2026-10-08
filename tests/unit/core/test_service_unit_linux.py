import subprocess

from binnacle import service_unit_linux


def test_unit_property_uses_linux_systemctl_without_timeout():
    seen = []

    def run(argv, **kwargs):
        seen.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="value\n", stderr="")

    assert service_unit_linux.unit_property("demo.service", "After", run=run) == "value"
    assert seen == [
        (
            ["systemctl", "--user", "show", "demo.service", "-p", "After", "--value"],
            {"capture_output": True, "text": True, "check": False},
        )
    ]


def test_unit_property_operational_failure_is_empty():
    def run(argv, **kwargs):
        raise OSError("missing")

    assert service_unit_linux.unit_property("demo.service", "After", run=run) == ""


def test_legacy_module_is_same_as_linux_owned_module():
    from binnacle.platform.linux import service_unit_linux as linux_adapter

    assert service_unit_linux is linux_adapter


def test_legacy_units_module_is_deployment_owned():
    from binnacle import units
    from binnacle.deployment import units as implementation

    assert units is implementation
