"""OI-09/OI-12: systemd unit inspection is Linux-specific and parity is frozen."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from binnacle.deployment import job_manager_unit, server_unit, units
from binnacle.deployment.provisioning_contracts import PlannedUnit
from binnacle.platform.linux.service_provisioning_linux import LinuxServiceProvisioner

REFERENCE = (
    Path(__file__).resolve().parents[3]
    / "docs/os-independent-stage1-evidence/os0-host-baseline.json"
)


def test_linux_template_bytes_match_pre_refactor_capture():
    baseline = json.loads(REFERENCE.read_text(encoding="utf-8"))
    expected = baseline["rendered_linux_units"]
    # The immutable JSON snapshot sorts object keys, whereas the systemd marker
    # records the original insertion order. Reconstruct the frozen Linux order.
    captured_dev = baseline["recorded_unit_parameters"]["mcp_dev"]
    captured_prod = baseline["recorded_unit_parameters"]["mcp_prod"]
    dev = {
        name: captured_dev[name]
        for name in ("mode", "host", "port", "jobs_owner", "repo")
    }
    prod = {
        name: captured_prod[name]
        for name in ("mode", "host", "port", "jobs_owner", "binnacle")
    }
    actual = {
        "mcp_dev": server_unit.render_server_unit(dev),
        "mcp_prod": server_unit.render_server_unit(prod),
        "jobs_dev": job_manager_unit.render_job_manager_unit(
            {
                "mode": "dev",
                "jobs": "/tmp/binnacle-os0-reference/.venv/bin/binnacle-jobs",
            }
        ),
        "jobs_prod": job_manager_unit.render_job_manager_unit(
            {"mode": "prod", "jobs": "/usr/local/bin/binnacle-jobs"}
        ),
    }
    assert actual == expected
    assert all(hashlib.sha256(value.encode()).digest() for value in actual.values())


def test_linux_provisioner_returns_domain_owned_unit_plan(tmp_path):
    provisioner = LinuxServiceProvisioner(
        unit_dir=tmp_path / "unit",
        backup_dir=tmp_path / "backup",
        run=lambda *args, **kwargs: None,
    )
    spec = units.UnitSpec("example.service", "binnacle", "[Unit]\n", {})
    plan = provisioner.plan_unit(spec)
    assert isinstance(plan, PlannedUnit)
    assert plan.name == "example.service"
    assert plan.write.action == "create"
    assert not plan.path.exists()


def test_pure_unit_plan_works_with_all_linux_modules_blocked(tmp_path):
    source = """
import importlib.abc, sys
class BlockLinux(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith((
                "binnacle.platform.linux",
                "binnacle.observability.linux",
                "binnacle.deployment.linux",
        )):
            raise ImportError("blocked: " + fullname)
sys.meta_path.insert(0, BlockLinux())
from pathlib import Path
from binnacle.deployment import units
root = Path(sys.argv[1])
spec = units.UnitSpec("fixture.service", "binnacle", "[Unit]\\n", {})
planned = units.plan_write(root / spec.name, spec)
assert planned.action == "create"
assert planned.text.startswith("# Managed by binnacle")
assert "binnacle.deployment.linux.unit_inspection" not in sys.modules
print("LINUX_UNIT_PLAN_ISOLATED")
"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("BINNACLE_")}
    env["BINNACLE_CONFIG_FILE"] = str(tmp_path / "missing.toml")
    result = subprocess.run(
        [sys.executable, "-c", source, str(tmp_path)],
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
        check=False,
        cwd=Path(__file__).resolve().parents[3],
    )
    assert result.returncode == 0, result.stderr
    assert "LINUX_UNIT_PLAN_ISOLATED" in result.stdout
