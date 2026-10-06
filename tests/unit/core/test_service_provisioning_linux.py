import subprocess

import pytest

from binnacle.service_provisioning_linux import LinuxServiceProvisioner


def completed(argv, rc=0, out="", err=""):
    return subprocess.CompletedProcess(argv, rc, stdout=out, stderr=err)


def test_persistence_enabled_without_timeout_uses_current_user(monkeypatch):
    seen = []

    def run(argv, **kwargs):
        seen.append((argv, kwargs))
        return completed(argv, out="yes\n")

    monkeypatch.setenv("USER", "grammy")
    provisioner = LinuxServiceProvisioner(run=run)

    assert provisioner.inspect_persistence().enabled is True
    assert seen == [
        (
            ["loginctl", "show-user", "grammy", "-p", "Linger", "--value"],
            {"capture_output": True, "text": True, "check": False},
        )
    ]


def test_persistence_enabled_with_timeout_and_explicit_user():
    seen = []

    def run(argv, **kwargs):
        seen.append((argv, kwargs))
        return completed(argv, out="no\n")

    provisioner = LinuxServiceProvisioner(run=run)

    assert provisioner.inspect_persistence(user="pi", timeout=3.5).enabled is False
    assert seen[0][1]["timeout"] == 3.5


@pytest.mark.parametrize(
    "result",
    [
        completed([], rc=1, err="denied"),
        OSError("missing"),
        subprocess.TimeoutExpired(["loginctl"], 1),
    ],
)
def test_persistence_enabled_failure_is_unknown(result):
    def run(argv, **kwargs):
        if isinstance(result, BaseException):
            raise result
        return result

    provisioner = LinuxServiceProvisioner(run=run)

    assert provisioner.inspect_persistence(user="pi", timeout=1.0).enabled is None


def test_enable_persistence_invokes_loginctl():
    seen = []

    def run(argv, **kwargs):
        seen.append((argv, kwargs))
        return completed(argv)

    provisioner = LinuxServiceProvisioner(run=run)

    provisioner.enable_persistence()

    assert seen == [(["loginctl", "enable-linger"], {"check": True})]
