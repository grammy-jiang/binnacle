"""Native launchd log ingestion: bounded, timestamped, private, no Linux tools."""

from __future__ import annotations

import bz2
from datetime import datetime
from pathlib import Path

import pytest

from binnacle.observability.logstats import analyze, parse
from binnacle.platform.contracts.service_log_contracts import ServiceLogError
from binnacle.platform.darwin.daemon_logstats import (
    DarwinDaemonLogStatsSource,
    _instant,
)


def source(root: Path, *, budget: int = 1 << 20) -> DarwinDaemonLogStatsSource:
    return DarwinDaemonLogStatsSource(root=root, max_bytes=budget)


def create(root: Path, name: str, text: str) -> None:
    (root / name).write_text(text)


def test_window_filters_mcp_and_jobs_and_analyzes(tmp_path):
    create(
        tmp_path,
        "mcp.stderr.log",
        (
            "2026-10-12T08:00:00.000 INFO: event=tool_call call=old tool=read_file\n"
            "2026-10-13T08:00:00.000 INFO: event=tool_call call=new tool=read_file\n"
            "2026-10-13T08:00:01.000 INFO: event=tool_result call=new tool=read_file duration_ms=15\n"
        ),
    )
    create(
        tmp_path,
        "com.binnacle.jobs.err.log",
        (
            "2026-10-13T08:00:01.500 INFO: event=job_start job_id=job1 call=new owner=manager\n"
            "2026-10-13T08:00:02.000 INFO: event=job_exit job_id=job1 "
            "exit_code=0 signal=None reason=normal_exit runtime_s=1 log_bytes=0 "
            "call=new owner=manager owner_instance=owner command_hash=abc\n"
        ),
    )
    logs = source(tmp_path).read_spec(
        ("binnacle-mcp", "binnacle-jobs"),
        "2026-10-13 08:00:00",
        "2026-10-13 08:00:03",
    )
    assert "call=old" not in logs
    assert "call=new" in logs
    assert logs.index("event=tool_call") < logs.index("event=tool_result")
    assert logs.index("event=job_start") < logs.index("event=job_exit")
    events, _ = parse(logs)
    counts = analyze(events).events
    assert counts["job_exit"] == 1
    assert counts["tool_call"] == 1


def test_rich_timestamp_and_continuation_lines(tmp_path):
    create(
        tmp_path,
        "mcp.stderr.log",
        (
            "[10/13/26 08:00:00] INFO     event=request_start method=tools/call\n"
            "                    INFO     event=request_success method=tools/call\n"
            "[10/13/26 08:01:00] INFO     event=request_start method=tools/list\n"
        ),
    )
    text = source(tmp_path).read_spec(
        "binnacle-mcp", "2026-10-13 08:00:00", "2026-10-13 08:00:30"
    )
    assert "request_start method=tools/call" in text
    assert "request_success method=tools/call" in text
    assert "tools/list" not in text


def test_legacy_stampless_jobs_excluded_with_warning(tmp_path, capsys):
    create(
        tmp_path,
        "com.binnacle.jobs.err.log",
        (
            "INFO event=job_exit job_id=old\n"
            "2026-10-13T08:00:00.000 INFO: event=job_exit job_id=new\n"
        ),
    )
    text = source(tmp_path).read_spec(
        "binnacle-jobs", "2026-10-13 00:00:00", "2026-10-13 23:59:59"
    )
    assert "job_id=old" not in text
    assert "job_id=new" in text
    assert "legacy" in capsys.readouterr().err


def test_compressed_archives_and_deduplicated_units(tmp_path):
    (tmp_path / "mcp.stderr.log.0.bz2").write_bytes(
        bz2.compress(b"2026-10-13T07:00:00.000 INFO: event=tool_call call=archive\n")
    )
    create(
        tmp_path,
        "mcp.stderr.log",
        ("2026-10-13T08:00:00.000 INFO: event=tool_call call=active\n"),
    )
    text = source(tmp_path).read_spec(
        ("binnacle-mcp", "com.binnacle.mcp"),
        "2026-10-13 06:00:00",
        "2026-10-13 09:00:00",
    )
    assert text.count("call=archive") == 1
    assert text.index("call=archive") < text.index("call=active")


@pytest.mark.parametrize(
    "units",
    [
        "other-service",
        "../../etc/passwd",
        "com.binnacle.unknown",
    ],
)
def test_refuses_unknown_units(tmp_path, units):
    with pytest.raises(ServiceLogError, match="unrecognised"):
        source(tmp_path).read_spec(units, "-24 hours")


def test_refuses_symlinked_log(tmp_path):
    create(tmp_path, "mcp.stderr.log.real", "secret")
    (tmp_path / "mcp.stderr.log").symlink_to("mcp.stderr.log.real")
    with pytest.raises(ServiceLogError, match="safely open"):
        source(tmp_path).read_spec("binnacle-mcp", "-24 hours")


def test_bounded_read_is_not_silent_truncation(tmp_path):
    create(
        tmp_path,
        "mcp.stderr.log",
        ("2026-10-13T08:00:00.000 INFO: event=tool_call call=new\n" * 15),
    )
    with pytest.raises(ServiceLogError, match="budget exceeded"):
        source(tmp_path, budget=50).read_spec("binnacle-mcp", "-24 hours")


def test_absent_log_directory_and_primary_stream(tmp_path):
    with pytest.raises(ServiceLogError, match="directory unavailable"):
        source(tmp_path / "gone").read_spec("binnacle-mcp", "-24 hours")
    with pytest.raises(ServiceLogError, match="log missing"):
        source(tmp_path).read_spec("binnacle-mcp", "-24 hours")


@pytest.mark.parametrize(
    "since,seconds",
    [
        ("-1 hour", 3600),
        ("2 days ago", 172800),
        ("-10 minutes", 600),
    ],
)
def test_relative_time_is_strict(since, seconds):
    now = datetime.now().astimezone()
    assert abs(_instant(since, now) - (now.timestamp() - seconds)) < 0.001


def test_invalid_windows_fail_explicitly(tmp_path):
    create(tmp_path, "mcp.stderr.log", "")
    with pytest.raises(ServiceLogError, match="unsupported"):
        source(tmp_path).read_spec("binnacle-mcp", "three weeks before tomorrow")
    with pytest.raises(ServiceLogError, match="until before since"):
        source(tmp_path).read_spec(
            "binnacle-mcp", "2026-10-13 12:00:00", "2026-10-13 11:00:00"
        )


def test_rename_only_rotation_continues_ingestion_from_live_raw_archive(tmp_path):
    """The original launchd FD remains on .0; the new .log may be empty."""
    original = tmp_path / "mcp.stderr.log"
    create(
        tmp_path,
        "mcp.stderr.log",
        "2026-10-13T07:59:59.000 INFO: event=tool_call call=before\n",
    )
    # newsyslog GN renames the inode without compressing or signalling.
    original.rename(tmp_path / "mcp.stderr.log.0")
    create(tmp_path, "mcp.stderr.log", "")
    with (tmp_path / "mcp.stderr.log.0").open("a") as oldfd:
        oldfd.write("2026-10-13T08:00:00.000 INFO: event=tool_result call=after\n")
    text = source(tmp_path).read_spec(
        "binnacle-mcp", "2026-10-13 07:00:00", "2026-10-13 09:00:00"
    )
    assert text.count("call=before") == 1
    assert text.count("call=after") == 1
    assert text.index("call=before") < text.index("call=after")


def test_raw_and_canonical_compressed_same_generation_never_double_count(tmp_path):
    event = "2026-10-13T07:00:00.000 INFO: event=tool_call call=single\n"
    create(tmp_path, "mcp.stderr.log", "")
    create(tmp_path, "mcp.stderr.log.0", event)
    compressed = tmp_path / "mcp.stderr.log.0.bz2"
    compressed.write_bytes(bz2.compress(event.encode("utf-8")))
    stats = source(tmp_path)
    first = stats.read_spec("binnacle-mcp", "2026-10-13 06:00", "2026-10-13 08:00")
    assert first.count("call=single") == 1
    # A write received by the old fd before pruning wins over a stale .bz2.
    with (tmp_path / "mcp.stderr.log.0").open("a") as stream:
        stream.write("2026-10-13T07:01:00.000 INFO: event=tool_call call=raw_tail\n")
    middle = stats.read_spec("binnacle-mcp", "2026-10-13 06:00", "2026-10-13 08:00")
    assert middle.count("call=raw_tail") == 1
    (tmp_path / "mcp.stderr.log.0").unlink()
    last = stats.read_spec("binnacle-mcp", "2026-10-13 06:00", "2026-10-13 08:00")
    assert last.count("call=single") == 1
    assert "call=raw_tail" not in last
