import subprocess

import pytest

from binnacle.observability import logstats_io
from binnacle.platform.contracts.service_log_contracts import ServiceLogError
from binnacle.platform.linux import service_journal


def test_fetch_journal_is_linux_string_compatibility_facade(monkeypatch):
    seen = []

    def run(cmd, **kwargs):
        seen.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="journal\n", stderr="")

    monkeypatch.setattr(service_journal.subprocess, "run", run)

    assert logstats_io.fetch_journal("svc", "-1 hour", "now") == "journal\n"
    cmd, kwargs = seen[0]
    assert cmd == [
        "journalctl",
        "--user",
        "-u",
        "svc",
        "--since",
        "-1 hour",
        "-o",
        "cat",
        "--no-pager",
        "--until",
        "now",
    ]
    assert "timeout" not in kwargs
    assert kwargs["check"] is False


def test_fetch_journal_accepts_multiple_units(monkeypatch):
    seen = []

    def run(cmd, **kwargs):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="merged\n", stderr="")

    monkeypatch.setattr(service_journal.subprocess, "run", run)

    assert logstats_io.fetch_journal(("mcp", "jobs"), "-1 hour") == "merged\n"
    assert seen[0][:6] == ["journalctl", "--user", "-u", "mcp", "-u", "jobs"]


def test_fetch_journal_exposes_typed_acquisition_failure(monkeypatch):
    monkeypatch.setattr(
        service_journal.subprocess,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="permission denied"
        ),
    )

    with pytest.raises(ServiceLogError, match="permission denied"):
        logstats_io.fetch_journal("svc", "-1 hour")
