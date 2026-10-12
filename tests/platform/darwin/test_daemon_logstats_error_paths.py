"""Error handling and date/rotation-path validation for Darwin usage statistics."""

from __future__ import annotations

import gzip
import os
from datetime import datetime
from pathlib import Path

import pytest

from binnacle.platform.contracts.service_log_contracts import ServiceLogError
from binnacle.platform.darwin.daemon_logstats import (
    DarwinDaemonLogStatsSource,
    _instant,
    _safe_fd,
    _stamp,
)


def test_relative_and_absolute_time_variants():
    now = datetime.now().astimezone()
    assert _instant("now", now) == now.timestamp()
    assert _instant("today", now) <= now.timestamp()
    assert _instant("yesterday", now) < _instant("today", now)
    assert _instant("@12345678", now) == 12345678
    assert _instant("2026-10-13T08:00:00", now) > 0
    with pytest.raises(ServiceLogError, match="unsupported"):
        _instant("@not_a_time", now)


@pytest.mark.parametrize(
    "line",
    [
        "2026-99-99T01:00:00 INFO event=test",
        "[99/99/99 00:00:00] INFO event=test",
        "no timestamp",
    ],
)
def test_malformed_or_absent_timestamps_are_unknown(line):
    assert _stamp(line) is None


def test_refuses_wrong_log_owner(tmp_path, monkeypatch):
    f = tmp_path / "file.log"
    f.write_bytes(b"a")
    monkeypatch.setattr(os, "getuid", lambda: -100000)
    with pytest.raises(ServiceLogError, match="unsafe"):
        _safe_fd(f)


def test_safe_fd_rejects_nonregular_file(tmp_path):
    with pytest.raises(ServiceLogError, match="unsafe"):
        _safe_fd(tmp_path)


def test_root_must_be_private_directory_owned_by_user(tmp_path, monkeypatch):
    f = tmp_path / "mcp.stderr.log"
    f.write_text("2026-10-13T01:00:00.000 INFO: event=test\n")
    monkeypatch.setattr(os, "getuid", lambda: -123456)
    with pytest.raises(ServiceLogError, match="unsafe"):
        DarwinDaemonLogStatsSource(root=tmp_path).read_spec("binnacle-mcp", "-1 hour")


def test_root_default_uses_user_library(tmp_path, monkeypatch):
    root = tmp_path / "Library" / "Logs" / "binnacle"
    root.mkdir(parents=True)
    (root / "mcp.stderr.log").write_text(
        "2026-10-13T08:00:00.000 INFO: event=tool_call call=default\n"
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    text = DarwinDaemonLogStatsSource().read_spec(
        "binnacle-mcp", "2026-10-13 07:00:00", "2026-10-13 09:00:00"
    )
    assert "call=default" in text


def test_empty_services_and_invalid_budget(tmp_path):
    (tmp_path / "mcp.stderr.log").write_text("")
    with pytest.raises(ServiceLogError, match="at least one"):
        DarwinDaemonLogStatsSource(root=tmp_path).read_spec((), "-1 hour")
    with pytest.raises(ServiceLogError, match="invalid.*budget"):
        DarwinDaemonLogStatsSource(root=tmp_path, max_bytes=0).read_spec(
            "binnacle-mcp", "-1 hour"
        )


def test_gzip_rotated_files_and_stampless_continuation(tmp_path):
    (tmp_path / "mcp.stderr.log").write_text(
        "2026-10-13T08:00:00.000 INFO: event=tool_result call=active\n"
    )
    with gzip.open(tmp_path / "mcp.stderr.log.0.gz", "wb") as dest:
        dest.write(
            b"2026-10-13T07:00:00.000 INFO: event=tool_call call=archive\n"
            b"              continuation\n"
        )
    text = DarwinDaemonLogStatsSource(root=tmp_path).read_spec(
        "binnacle-mcp", "2026-10-13 06:00:00", "2026-10-13 09:00:00"
    )
    assert "call=archive" in text
    assert "continuation" in text
    assert text.index("call=archive") < text.index("call=active")


def test_nonmatching_noise_files_ignored(tmp_path):
    (tmp_path / "mcp.stderr.log").write_text(
        "2026-10-13T08:00:00.000 INFO: event=tool_call call=allowed\n"
    )
    (tmp_path / "mcp.stderr.log.tmp").write_text("secret")
    (tmp_path / "other.log").write_text("secret")
    text = DarwinDaemonLogStatsSource(root=tmp_path).read_spec(
        "binnacle-mcp", "2026-10-13 06:00:00", "2026-10-13 09:00:00"
    )
    assert "allowed" in text and "secret" not in text
