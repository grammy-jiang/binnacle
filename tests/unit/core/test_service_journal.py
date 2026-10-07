import subprocess

import pytest

from binnacle.platform.contracts.service_log_contracts import ServiceLogError
from binnacle.platform.linux import service_journal


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


def test_read_window_boundary_events_preserve_truncation_and_inclusive_until(
    monkeypatch,
):
    events = [
        (99.999, "before"),
        (100.0, "since-boundary"),
        (100.999, "fractional-since"),
        (200.999, "fractional-until"),
        (201.0, "inclusive-until-plus-one"),
        (201.001, "after"),
    ]

    def run(argv, **kwargs):
        since = int(argv[argv.index("--since") + 1].removeprefix("@"))
        until = int(argv[argv.index("--until") + 1].removeprefix("@"))
        selected = [text for ts, text in events if since <= ts <= until]
        return completed(argv, out="\n".join(selected) + "\n")

    monkeypatch.setattr(service_journal.subprocess, "run", run)
    source = service_journal.JournalServiceLogSource(command_timeout_s=60.0)

    assert source.read_window(("svc",), 100.9, 200.1).splitlines() == [
        "since-boundary",
        "fractional-since",
        "fractional-until",
        "inclusive-until-plus-one",
    ]


@pytest.mark.parametrize("kind", ["completion", "launch"])
def test_operational_failure_detail_is_clipped_to_200_characters(monkeypatch, kind):
    detail = "x" * 240

    def run(argv, **kwargs):
        if kind == "completion":
            return completed(argv, rc=1, err=detail)
        raise OSError(detail)

    monkeypatch.setattr(service_journal.subprocess, "run", run)
    source = service_journal.JournalServiceLogSource(command_timeout_s=60.0)

    with pytest.raises(ServiceLogError) as exc:
        source.read_window(("svc",), 1)

    message = str(exc.value)
    prefix = (
        "journalctl failed: "
        if kind == "completion"
        else "journalctl failed to start: "
    )
    assert message == prefix + ("x" * 200)


def test_nonzero_completion_becomes_service_log_error(monkeypatch):
    monkeypatch.setattr(
        service_journal.subprocess,
        "run",
        lambda argv, **kwargs: completed(argv, rc=1, err="permission denied"),
    )

    with pytest.raises(ServiceLogError, match="permission denied"):
        service_journal.JournalServiceLogSource().read_spec("svc", "-1 hour")


def test_top_level_service_journal_facade_reexports_implementation():
    from binnacle import service_journal as facade

    assert facade.JournalServiceLogSource is service_journal.JournalServiceLogSource
