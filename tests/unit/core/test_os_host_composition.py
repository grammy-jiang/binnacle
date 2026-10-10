"""OS2 host-selection boundary with Linux parity and explicit unsupported hosts."""

import pytest

from binnacle.platform import composition, deployment_platform, job_platform


@pytest.mark.parametrize("host", ["Darwin", "FreeBSD", "Windows", "Fedora", ""])
def test_unavailable_host_fails_before_native_adapter_construction(monkeypatch, host):
    monkeypatch.setattr(composition.platform, "system", lambda: host)
    with pytest.raises(composition.UnsupportedHostOS, match="platform adapter"):
        job_platform.create_process_backend()
    with pytest.raises(composition.UnsupportedHostOS, match="platform adapter"):
        job_platform.create_resource_accounting()
    with pytest.raises(composition.UnsupportedHostOS, match="platform adapter"):
        deployment_platform.create_runtime_paths()
    with pytest.raises(composition.UnsupportedHostOS, match="platform adapter"):
        deployment_platform.create_service_log_source()
    with pytest.raises(composition.UnsupportedHostOS, match="platform adapter"):
        deployment_platform.create_service_inspector()
    with pytest.raises(composition.UnsupportedHostOS, match="platform adapter"):
        deployment_platform.create_service_controller()


def test_linux_selection_preserves_legacy_factory_contract(monkeypatch):
    monkeypatch.setattr(composition.platform, "system", lambda: "Linux")
    assert composition.host_os_family() == "linux"
    assert job_platform.create_process_backend().__class__.__name__ == (
        "LinuxProcessBackend"
    )
    assert job_platform.create_resource_accounting().__class__.__name__ == (
        "CgroupResourceAccounting"
    )
    assert deployment_platform.create_runtime_paths().jobs_socket.name == "jobs.sock"
