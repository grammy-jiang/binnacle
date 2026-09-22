"""Process-lifecycle contract for the binary rg JSONL stream."""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from binnacle.search_text_stream import RgJsonStream


def executable(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "fake-rg"
    path.write_text("#!/usr/bin/env python3\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_stream_yields_bytes_jsonl_and_counts_events(tmp_path):
    rg = executable(
        tmp_path,
        "import json\n"
        "for kind in ('begin','match','context'):\n"
        " print(json.dumps({'type':kind,'data':{}}), flush=True)\n",
    )
    with RgJsonStream(tmp_path, "x", False, 1, rg_bin=str(rg), timeout_s=2) as stream:
        events = list(stream)
    assert [event["type"] for event in events] == ["begin", "match", "context"]
    assert stream.stats.events == 3
    assert stream.stats.match_events == 1
    assert stream.stats.context_events == 1
    assert stream.stats.begin_events == 1
    assert stream.stats.stdout_bytes > 0
    assert stream.stats.bad_json == 0
    assert stream.stats.timed_out is False
    assert stream.stats.wall_ms >= 0 and stream.stats.stream_cpu_ms >= 0


def test_bad_json_is_counted_and_skipped(tmp_path):
    rg = executable(
        tmp_path,
        "print('not-json', flush=True)\n"
        'print(\'{"type":"match","data":{}}\', flush=True)\n',
    )
    with RgJsonStream(tmp_path, "x", False, 0, rg_bin=str(rg), timeout_s=2) as stream:
        events = list(stream)
    assert len(events) == 1 and stream.stats.bad_json == 1


def test_missing_rg_keeps_existing_error_contract(tmp_path):
    with (
        pytest.raises(ToolError, match="ripgrep .* not available") as exc,
        RgJsonStream(
            tmp_path, "x", False, 0, rg_bin=str(tmp_path / "missing"), timeout_s=1
        ),
    ):
        pass
    assert exc.value.telemetry_code == "rg_missing"


def test_timeout_kills_and_reaps_child(tmp_path):
    rg = executable(tmp_path, "import time\ntime.sleep(30)\n")
    stream = RgJsonStream(tmp_path, "x", False, 0, rg_bin=str(rg), timeout_s=0.15)
    started = time.monotonic()
    with pytest.raises(ToolError, match="timed out") as exc, stream:
        list(stream)
    assert time.monotonic() - started < 2
    assert exc.value.telemetry_code == "rg_timeout"
    assert stream.stats.timed_out is True
    assert stream._proc is not None and stream._proc.poll() is not None


def test_consumer_exception_kills_and_reaps_child(tmp_path):
    rg = executable(
        tmp_path,
        "import json,time\n"
        "print(json.dumps({'type':'match','data':{}}), flush=True)\n"
        "time.sleep(30)\n",
    )
    stream = RgJsonStream(tmp_path, "x", False, 0, rg_bin=str(rg), timeout_s=10)
    with pytest.raises(RuntimeError, match="consumer boom"), stream:
        for _event in stream:
            raise RuntimeError("consumer boom")
    assert stream._proc is not None and stream._proc.poll() is not None


def test_large_stderr_cannot_deadlock_stdout(tmp_path):
    rg = executable(
        tmp_path,
        "import json,sys\n"
        "sys.stderr.write('e' * 300000)\n"
        "sys.stderr.flush()\n"
        "print(json.dumps({'type':'match','data':{}}), flush=True)\n",
    )
    with RgJsonStream(tmp_path, "x", False, 0, rg_bin=str(rg), timeout_s=2) as stream:
        events = list(stream)
    assert len(events) == 1 and stream.stats.timed_out is False


def test_rejected_rg_uses_bounded_stderr_tail(tmp_path):
    rg = executable(
        tmp_path,
        "import sys\n"
        "sys.stderr.write('prefix-' + 'x' * 1000 + '-useful-tail')\n"
        "raise SystemExit(2)\n",
    )
    with (
        pytest.raises(ToolError, match="useful-tail") as exc,
        RgJsonStream(tmp_path, "x", False, 0, rg_bin=str(rg), timeout_s=2) as stream,
    ):
        list(stream)
    assert exc.value.telemetry_code == "rg_rejected"


def test_early_break_context_exit_reaps_child(tmp_path):
    rg = executable(
        tmp_path,
        "import json,time\n"
        "print(json.dumps({'type':'match','data':{}}), flush=True)\n"
        "time.sleep(30)\n",
    )
    stream = RgJsonStream(tmp_path, "x", False, 0, rg_bin=str(rg), timeout_s=10)
    with stream:
        for _event in stream:
            break
    assert stream._proc is not None and stream._proc.poll() is not None
    assert not os.path.exists(f"/proc/{stream.pid}")
