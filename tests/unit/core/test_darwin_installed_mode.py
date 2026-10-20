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
        self.fail_bootstrap_all = False
        self.fail_install = False
        self.fail_bootout = False
        self.unhealthy_bootstrap_once = False

    def __call__(self, argv):
        self.calls.append(argv)
        if argv == ("/bin/launchctl", "print", TARGET):
            rc = 0 if self.running else 1
        elif "/usr/bin/install" in argv:
            if self.fail_install:
                rc = 1
            else:
                self.plist.write_bytes(Path(argv[-2]).read_bytes())
                rc = 0
        elif argv[-2:] == ("bootout", TARGET):
            if self.fail_bootout:
                rc = 1
            else:
                self.running = False
                rc = 0
        elif "bootstrap" in argv and argv[-2] == "system":
            if self.fail_bootstrap_all or self.fail_bootstrap:
                self.fail_bootstrap = False
                rc = 1
            else:
                self.running = not self.unhealthy_bootstrap_once
                self.unhealthy_bootstrap_once = False
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
    assert not any("/usr/bin/sudo" in c for c in runner.calls)


def test_dry_run_preserves_live_server_and_plist(installed, capsys):
    mode, runner, repo, plist = installed
    before = plist.read_bytes()
    MacInstalledCLI(mode).setup(dev=repo, port=8000, dry_run=True, adopt=False)
    assert "dry run: nothing was changed" in capsys.readouterr().out
    assert plist.read_bytes() == before
    assert not any("/usr/bin/sudo" in c for c in runner.calls)


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
    assert not any("/usr/bin/sudo" in c for c in runner.calls)


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


def test_cli_setup_applies_change_and_mode_recovers(installed, capsys):
    mode, _runner, repo, _ = installed
    adapter = MacInstalledCLI(mode)
    adapter.setup(dev=repo, port=8000, dry_run=False, adopt=True, force=True)
    assert "switched to dev" in capsys.readouterr().out
    adapter.mode(target="status", repo=None, force=False)
    assert "dev mode" in capsys.readouterr().out
    adapter.mode(target="prod", repo=repo, force=True)
    assert "switched to prod" in capsys.readouterr().out


def test_cli_setup_and_mode_errors_exit_one(installed, capsys):
    mode, _runner, repo, plist = installed
    adapter = MacInstalledCLI(mode)
    plist.unlink()
    with pytest.raises(SystemExit) as error:
        adapter.setup(dev=repo, port=8000, dry_run=False, adopt=False)
    assert error.value.code == 1
    assert "missing" in capsys.readouterr().out
    with pytest.raises(SystemExit) as error:
        adapter.mode(target="status", repo=None, force=False)
    assert error.value.code == 1
    assert "missing" in capsys.readouterr().out


def test_cli_mode_change_failure_is_an_error_not_a_traceback(installed, capsys):
    mode, _runner, repo, _ = installed
    with pytest.raises(SystemExit) as error:
        MacInstalledCLI(mode).mode(target="dev", repo=repo, force=False)
    assert error.value.code == 1
    assert "explicit --force" in capsys.readouterr().out


@pytest.mark.parametrize("kind", ["missing", "malformed", "nondict", "group_writable"])
def test_installed_plist_missing_or_invalid(installed, kind):
    mode, runner, _, plist = installed
    if kind == "missing":
        plist.unlink()
    elif kind == "malformed":
        plist.write_bytes(b"not a plist")
    elif kind == "nondict":
        plist.write_bytes(plistlib.dumps(["not", "a", "dictionary"]))
    else:
        plist.chmod(0o666)
    with pytest.raises(InstalledMcpModeError):
        mode.status()
    assert not any("/usr/bin/sudo" in c for c in runner.calls)


@pytest.mark.parametrize(
    "kind", ["wrong_shape", "wrong_flags", "bad_port", "relative_home", "other_binary"]
)
def test_installed_command_shape_rejected(installed, kind):
    mode, _runner, _, plist = installed
    original = plistlib.loads(plist.read_bytes())
    if kind == "wrong_shape":
        original["ProgramArguments"] = ["/usr/bin/untrusted"]
    elif kind == "wrong_flags":
        original["ProgramArguments"][1] = "unknown"
    elif kind == "bad_port":
        original["ProgramArguments"][5] = "invalid"
    elif kind == "relative_home":
        original["WorkingDirectory"] = "relative/path"
    else:
        original["ProgramArguments"][0] = "/tmp/other-binary"
    plist.write_bytes(plistlib.dumps(original))
    with pytest.raises(InstalledMcpModeError):
        mode.plan("dev")


def test_missing_checkout_and_invalid_port_rejected(installed, tmp_path):
    mode, _runner, _, _plist = installed
    with pytest.raises(InstalledMcpModeError, match="checkout"):
        mode.plan("dev", repo=tmp_path / "missing-checkout")
    with pytest.raises(InstalledMcpModeError, match="port"):
        mode.plan("dev", port=0)


def test_inactive_service_bootstraps_without_bootout(installed):
    mode, runner, _, _plist = installed
    runner.running = False
    assert "switched to dev" in mode.apply(mode.plan("dev"))
    assert runner.running
    assert not any(c[-2:] == ("bootout", TARGET) for c in runner.calls)


@pytest.mark.parametrize("kind", ["relative_root", "symlink_root", "insecure_root"])
def test_mode_transaction_requires_private_root(installed, tmp_path, kind):
    mode, runner, _, _plist = installed
    if kind == "relative_root":
        mode.state_root = Path("relative")
    elif kind == "symlink_root":
        real = tmp_path / "private-real"
        real.mkdir(mode=0o700)
        link = tmp_path / "root-link"
        link.symlink_to(real, target_is_directory=True)
        mode.state_root = link
    else:
        root = tmp_path / "insecure"
        root.mkdir()
        root.chmod(0o755)
        mode.state_root = root
    with pytest.raises(InstalledMcpModeError):
        mode.apply(mode.plan("dev"), force=True)
    assert not any("/usr/bin/sudo" in c for c in runner.calls)


def test_mode_transaction_rejects_changed_plist_since_plan(installed):
    mode, runner, _, plist = installed
    plan = mode.plan("dev")
    changed = plistlib.loads(plist.read_bytes())
    changed["KeepAlive"] = False
    plist.write_bytes(plistlib.dumps(changed))
    with pytest.raises(InstalledMcpModeError, match="changed since plan"):
        mode.apply(plan, force=True)
    assert not any("/usr/bin/sudo" in c for c in runner.calls)


def test_transaction_refuses_contending_lock(installed, monkeypatch):
    import fcntl

    mode, runner, _, _plist = installed

    def locked(*args):
        raise BlockingIOError()

    monkeypatch.setattr(fcntl, "flock", locked)
    with pytest.raises(InstalledMcpModeError, match="another MCP mode transaction"):
        mode.apply(mode.plan("dev"), force=True)
    assert not any("/usr/bin/sudo" in c for c in runner.calls)


def test_rollback_after_bootout_failure(installed):
    mode, runner, _, plist = installed
    prior = plist.read_bytes()
    runner.fail_bootout = True
    with pytest.raises(InstalledMcpModeError, match="rollback attempted"):
        mode.apply(mode.plan("dev"), force=True)
    assert plist.read_bytes() == prior
    assert runner.running


def test_refuse_failed_install_before_bootout(installed):
    mode, runner, _, plist = installed
    prior = plist.read_bytes()
    runner.fail_install = True
    with pytest.raises(InstalledMcpModeError, match="rollback attempted"):
        mode.apply(mode.plan("dev"), force=True)
    assert plist.read_bytes() == prior
    assert runner.running


def test_rollback_after_bootstrap_with_unhealthy_service(installed):
    mode, runner, _, plist = installed
    prior = plist.read_bytes()
    runner.unhealthy_bootstrap_once = True
    with pytest.raises(InstalledMcpModeError, match="rollback attempted"):
        mode.apply(mode.plan("dev"), force=True)
    assert plist.read_bytes() == prior
    assert runner.running
    assert sum(c[-2:] == ("bootout", TARGET) for c in runner.calls) >= 2


def test_both_bootstraps_fail_reports_incomplete_rollback(installed):
    mode, runner, _, _plist = installed
    runner.fail_bootstrap_all = True
    with pytest.raises(InstalledMcpModeError, match="AND rollback failed"):
        mode.apply(mode.plan("dev"), force=True)


@pytest.mark.parametrize(
    "failure",
    [
        OSError("spawn denied"),
        subprocess.TimeoutExpired("launchctl", 1),
    ],
)
def test_native_command_transport_failure_is_bounded(monkeypatch, failure):
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(InstalledMcpModeError, match="command unavailable"):
        DarwinInstalledMcpMode._run_command(("/bin/launchctl", "print", TARGET))


def test_native_command_transport_normal_result(monkeypatch):
    expected = subprocess.CompletedProcess(["/bin/launchctl", "print"], 0, "", "")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: expected)
    assert (
        DarwinInstalledMcpMode._run_command(("/bin/launchctl", "print", TARGET))
        is expected
    )
