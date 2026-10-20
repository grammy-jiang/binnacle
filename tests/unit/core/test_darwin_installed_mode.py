"""Installed Darwin MCP mode: guarded source, native switch, rollback and dispatch."""

import os
import plistlib
import pwd
import subprocess
from pathlib import Path

import pytest

from binnacle.deployment.darwin.installed_cli import MacInstalledCLI
from binnacle.deployment.darwin.installed_mode import (
    TARGET,
    DarwinInstalledMcpMode,
    InstalledMcpModeError,
)
from binnacle.platform import deployment_platform


class FakeLaunchd:
    def __init__(self, plist):
        self.plist = plist
        self.running = True
        self.calls = []
        self.fail_bootstrap = False

    def __call__(self, argv):
        self.calls.append(argv)
        if argv == ("/bin/launchctl", "print", TARGET):
            rc = 0 if self.running else 1
        elif "/usr/bin/install" in argv:
            self.plist.write_bytes(Path(argv[-2]).read_bytes())
            rc = 0
        elif argv[-2:] == ("bootout", TARGET):
            self.running = False
            rc = 0
        elif "bootstrap" in argv and argv[-2] == "system":
            if self.fail_bootstrap:
                self.fail_bootstrap = False
                rc = 1
            else:
                self.running = True
                rc = 0
        else:
            rc = 0
        return subprocess.CompletedProcess(argv, rc, "", "")


@pytest.fixture
def installed(tmp_path):
    repo = tmp_path / "source"
    (repo / "src/binnacle").mkdir(parents=True)
    (repo / "src/binnacle/server.py").write_text("# fixture\n")
    binary = repo / ".venv/bin/binnacle"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o700)
    plist = tmp_path / "com.binnacle.mcp.plist"
    plist.write_bytes(
        plistlib.dumps(
            {
                "Label": "com.binnacle.mcp",
                "UserName": pwd.getpwuid(os.geteuid()).pw_name,
                "GroupName": "staff",
                "WorkingDirectory": str(repo),
                "EnvironmentVariables": {
                    "HOME": str(Path.home()),
                    "PATH": "/usr/bin:/bin",
                },
                "ProgramArguments": [
                    str(binary),
                    "serve",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                ],
                "KeepAlive": True,
            }
        )
    )
    plist.chmod(0o644)
    runner = FakeLaunchd(plist)
    mode = DarwinInstalledMcpMode(
        plist=plist, state_root=tmp_path / "audit", run=runner
    )
    return mode, runner, repo, plist


def test_status_and_noop_preserve_installed_plist(installed):
    mode, runner, repo, plist = installed
    old = plist.read_bytes()
    assert f"checkout={repo}" in mode.status()
    plan = mode.plan("prod")
    assert not plan.changed
    assert mode.apply(plan) == mode.preview(plan)
    assert plist.read_bytes() == old
    assert not any("sudo" in c for c in runner.calls)


def test_dry_run_preserves_live_server_and_plist(installed, capsys):
    mode, runner, repo, plist = installed
    before = plist.read_bytes()
    MacInstalledCLI(mode).setup(dev=repo, port=8000, dry_run=True, adopt=False)
    assert "dry run: nothing was changed" in capsys.readouterr().out
    assert plist.read_bytes() == before
    assert not any("sudo" in c for c in runner.calls)


def test_force_and_rollback(installed):
    mode, runner, _, plist = installed
    old = plist.read_bytes()
    plan = mode.plan("dev")
    assert plan.changed
    with pytest.raises(InstalledMcpModeError, match="force"):
        mode.apply(plan)
    assert plist.read_bytes() == old
    assert "switched to dev" in mode.apply(plan, force=True)
    assert "dev mode" in mode.status()
    assert plistlib.loads(plist.read_bytes())["ProgramArguments"][-1] == "--reload"
    assert "switched to prod" in mode.apply(mode.plan("prod"), force=True)
    assert "prod mode" in mode.status()
    assert list((plist.parent / "audit").glob("*.previous.plist"))
    assert not any("com.binnacle.jobs" in str(c) for c in runner.calls)


def test_bootstrap_failure_rolls_back_to_prior_service(installed):
    mode, runner, _, plist = installed
    old = plist.read_bytes()
    runner.fail_bootstrap = True
    with pytest.raises(InstalledMcpModeError, match="rollback"):
        mode.apply(mode.plan("dev"), force=True)
    assert plist.read_bytes() == old
    assert runner.running


@pytest.mark.parametrize(
    "field,bad",
    [
        ("Label", "com.untrusted.other"),
        ("UserName", "root"),
        ("ProgramArguments", ["/usr/bin/unknown"]),
        ("EnvironmentVariables", {"EVIL": "one"}),
    ],
)
def test_unknown_installed_identity_is_never_modified(installed, field, bad):
    mode, runner, _, plist = installed
    d = plistlib.loads(plist.read_bytes())
    d[field] = bad
    plist.write_bytes(plistlib.dumps(d))
    with pytest.raises(InstalledMcpModeError):
        mode.plan("dev")
    assert not any("sudo" in c for c in runner.calls)


def test_symlinked_plist_is_refused(installed, tmp_path):
    mode, _, _, plist = installed
    old = plist.read_bytes()
    plist.unlink()
    real = tmp_path / "real.plist"
    real.write_bytes(old)
    plist.symlink_to(real)
    with pytest.raises(InstalledMcpModeError, match="ownership"):
        mode.plan("dev")


def test_linux_dispatched_to_original_controller(monkeypatch):
    monkeypatch.setattr("binnacle.platform.composition.host_os_family", lambda: "linux")
    assert deployment_platform.create_native_installed_cli() is None


def test_darwin_factory_is_lazy(monkeypatch):
    monkeypatch.setattr(
        "binnacle.platform.composition.host_os_family", lambda: "darwin"
    )
    assert isinstance(
        deployment_platform.create_native_installed_cli(), MacInstalledCLI
    )


def test_public_cli_dispatches_to_darwin_not_linux(monkeypatch):
    from binnacle import cli

    seen = []

    class Native:
        def setup(self, **kwargs):
            seen.append(("setup", kwargs))

        def mode(self, **kwargs):
            seen.append(("mode", kwargs))

    monkeypatch.setattr(cli, "create_native_installed_cli", lambda: Native())
    monkeypatch.setattr(cli, "_provisioner", lambda: pytest.fail("Linux-only path"))
    cli.setup(dev=Path("/tmp/native"), dry_run=True)
    cli.mode(target="status")
    assert seen[0][0] == "setup" and seen[0][1]["dry_run"] is True
    assert seen[1] == ("mode", {"target": "status", "repo": None, "force": False})
