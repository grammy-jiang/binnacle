"""OS2 host-selection boundary with Linux parity and explicit unsupported hosts."""

import pytest

from binnacle.platform import composition, deployment_platform, job_platform


@pytest.mark.parametrize("host", ["FreeBSD", "Windows", "Fedora", ""])
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


def test_darwin_factories_use_native_adapters_without_linux_imports(tmp_path):
    import os
    import subprocess
    import sys

    code = """
import importlib.abc, platform, sys
from pathlib import Path
platform.system = lambda: "Darwin"
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("binnacle.platform.linux"):
            raise AssertionError("Linux adapter imported: " + fullname)
sys.meta_path.insert(0, Block())
from binnacle.platform import composition as c
from binnacle.platform.contracts.capability_contracts import CapabilityState
from binnacle.platform.contracts.darwin_release_scope import DARWIN_RELEASE_SCOPE
root = Path(sys.argv[1])
lease = c.create_service_lease(root=root, label="com.binnacle.r3test.probe", generation="positive-darwin-123456")
assert c.create_process_backend().__class__.__name__ == "DarwinProcessBackend"
assert c.create_resource_accounting().__class__.__name__ == "DarwinResourceAccounting"
assert c.create_runtime_paths().jobs_socket == root / "jobs.sock"
assert c.create_service_log_source(root=root, generation=lease.generation).__class__.__name__ == "PrivateServiceLogSource"
assert c.create_service_inspector(lease=lease).__class__.__name__ == "LaunchdUserServices"
assert c.create_service_controller(lease=lease).__class__.__name__ == "LaunchdUserServices"
assert all(row.capability.state == CapabilityState.UNAVAILABLE for row in DARWIN_RELEASE_SCOPE.values())
assert c.native_file_capability().state == CapabilityState.UNAVAILABLE
assert not any(m.startswith("binnacle.platform.linux") for m in sys.modules)
"""
    # Short root also satisfies Darwin's Unix-domain socket path limit on Linux CI.
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory(
        prefix="b0host-", dir=Path("/tmp").resolve()
    ) as directory:
        result = subprocess.run(
            [sys.executable, "-c", code, directory],
            env={**os.environ, "BINNACLE_RUNTIME_DIR": directory},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
