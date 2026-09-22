import subprocess

import pytest

from binnacle import logstats_io


def test_fetch_journal_builds_window_and_returns_stdout(monkeypatch):
    seen = []

    def run(cmd, **kwargs):
        seen.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="journal\n", stderr="")

    monkeypatch.setattr(logstats_io.subprocess, "run", run)

    assert logstats_io.fetch_journal("svc", "-1 hour", "now") == "journal\n"
    cmd, kwargs = seen[0]
    assert cmd[:5] == ["journalctl", "--user", "-u", "svc", "--since"]
    assert cmd[-2:] == ["--until", "now"]
    assert kwargs["check"] is False


def test_fetch_journal_accepts_multiple_units(monkeypatch):
    seen = []

    def run(cmd, **kwargs):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="merged\n", stderr="")

    monkeypatch.setattr(logstats_io.subprocess, "run", run)
    assert logstats_io.fetch_journal(("mcp", "jobs"), "-1 hour") == "merged\n"
    assert seen[0][:6] == ["journalctl", "--user", "-u", "mcp", "-u", "jobs"]


def test_fetch_journal_without_until_and_failure(monkeypatch):
    monkeypatch.setattr(
        logstats_io.subprocess,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="permission denied"
        ),
    )

    with pytest.raises(SystemExit, match="permission denied"):
        logstats_io.fetch_journal("svc", "-1 hour")
