import subprocess

import pytest

from binnacle import service_journal
from binnacle.service_log_contracts import ServiceLogError


def completed(argv, rc=0, out="journal\n", err=""):
    return subprocess.CompletedProcess(argv, rc, stdout=out, stderr=err)


def test_read_spec_preserves_core_literal_argv_and_unbounded_execution(monkeypatch):
    seen = []

    def run(argv, **kwargs):
        seen.append((argv, kwargs))
        return completed(argv)

    monkeypatch.setattr(service_journal.subprocess, "run", run)
    source = service_journal.JournalServiceLogSource(command_timeout_s=None)

    assert source.read_spec(("mcp", "jobs"), "-1 hour", "now") == "journal\n"
    argv, kwargs = seen[0]
    assert argv == [
        "journalctl",
        "--user",
        "-u",
        "mcp",
        "-u",
        "jobs",
        "--since",
        "-1 hour",
        "-o",
        "cat",
        "--no-pager",
        "--until",
        "now",
    ]
    assert kwargs == {"capture_output": True, "text": True, "check": False}


def test_read_window_preserves_deploy_epoch_conversion_order_and_timeout(monkeypatch):
    seen = []

    def run(argv, **kwargs):
        seen.append((argv, kwargs))
        return completed(argv)

    monkeypatch.setattr(service_journal.subprocess, "run", run)
    source = service_journal.JournalServiceLogSource(command_timeout_s=60.0)

    source.read_window(("binnacle-mcp.service",), 100.9, 200.1)

    argv, kwargs = seen[0]
    assert argv == [
        "journalctl",
        "--user",
        "-u",
        "binnacle-mcp.service",
        "--since",
        "@100",
        "--until",
        "@201",
        "--no-pager",
        "-o",
        "cat",
    ]
    assert kwargs["timeout"] == 60.0


def test_read_window_open_end_has_no_until(monkeypatch):
    seen = []

    def run(argv, **kwargs):
        seen.append(argv)
        return completed(argv)

    monkeypatch.setattr(service_journal.subprocess, "run", run)
    source = service_journal.JournalServiceLogSource(command_timeout_s=60.0)

    source.read_window(("svc",), 99.99)

    assert seen[0] == [
        "journalctl",
        "--user",
        "-u",
        "svc",
        "--since",
        "@99",
        "--no-pager",
        "-o",
        "cat",
    ]


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (subprocess.TimeoutExpired(["journalctl"], 60), "timed out after 60 s"),
        (FileNotFoundError("missing"), "failed to start: missing"),
    ],
)
def test_operational_failures_become_service_log_error(monkeypatch, failure, message):
    def run(argv, **kwargs):
        raise failure

    monkeypatch.setattr(service_journal.subprocess, "run", run)
    source = service_journal.JournalServiceLogSource(command_timeout_s=60.0)

    with pytest.raises(ServiceLogError, match=message):
        source.read_window(("svc",), 1)


def test_nonzero_completion_becomes_service_log_error(monkeypatch):
    monkeypatch.setattr(
        service_journal.subprocess,
        "run",
        lambda argv, **kwargs: completed(argv, rc=1, err="permission denied"),
    )

    with pytest.raises(ServiceLogError, match="permission denied"):
        service_journal.JournalServiceLogSource().read_spec("svc", "-1 hour")
