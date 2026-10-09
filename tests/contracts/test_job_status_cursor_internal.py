"""IB1 cursor semantics before the public MCP parameter lands in IB2."""

import json

import pytest
from fastmcp.exceptions import ToolError

from binnacle import jobs
from binnacle.mcp.callctx import current_call
from binnacle.tools import job_status as js


@pytest.fixture()
def cursor_store(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path)
    monkeypatch.setattr(jobs, "job_processes", lambda _pgid, max_cmd_chars=200: [])
    return tmp_path


def _record(
    root,
    monkeypatch,
    *,
    job_id="cursorjob001",
    data=b"",
    state_name="exited",
    last_output_age_s=0.0,
):
    directory = root / job_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "meta.json").write_text(json.dumps({"job": job_id}))
    (directory / "out.log").write_bytes(data)
    state = {
        "job_id": job_id,
        "state": state_name,
        "exit_code": 0 if state_name == "exited" else None,
        "signal": None,
        "runtime_s": 1.0,
        "last_output_age_s": last_output_age_s,
        "log_bytes": len(data),
        "log_path": str(directory / "out.log"),
        "command": "synthetic",
        "workdir": "/tmp",
        "pgid": 1,
        "termination_reason": None,
    }
    monkeypatch.setattr(
        jobs, "job_state", lambda requested: state if requested == job_id else None
    )
    return job_id, state, directory


def _status(job_id, cursor):
    result = js.job_status_impl(job_id, 100, 0, cursor=cursor)
    assert result.structured_content is not None
    return result.structured_content


def test_cursor_start_drains_multi_chunk_log(cursor_store, monkeypatch):
    job_id, _, _ = _record(cursor_store, monkeypatch, data=b"abcdefghij")
    monkeypatch.setattr(jobs, "RUN_MAX_OUTPUT_CHARS", 4)

    cursor = "start"
    parts = []
    ranges = []
    while True:
        payload = _status(job_id, cursor)
        assert "log_tail" not in payload
        parts.append(payload["log_delta"])
        ranges.append((payload["delta_start"], payload["delta_end"]))
        cursor = payload["next_cursor"]
        if not payload["has_more"]:
            break

    assert "".join(parts) == "abcdefghij"
    assert ranges == [(0, 4), (4, 8), (8, 10)]
    assert cursor == f"v1:{job_id}:10"


def test_cursor_end_explicitly_skips_existing_output(cursor_store, monkeypatch):
    job_id, _, _ = _record(cursor_store, monkeypatch, data=b"existing")
    payload = _status(job_id, "end")
    assert payload["log_delta"] == ""
    assert payload["delta_start"] == payload["delta_end"] == 8
    assert payload["next_cursor"] == f"v1:{job_id}:8"
    assert payload["has_more"] is False


def test_cursor_rejects_wrong_job_beyond_end_and_malformed(cursor_store, monkeypatch):
    job_id, _, _ = _record(cursor_store, monkeypatch, data=b"abc")

    with pytest.raises(ToolError, match=f"cursor belongs to job other, not {job_id}"):
        _status(job_id, "v1:other:0")
    with pytest.raises(ToolError, match="cursor beyond end of output"):
        _status(job_id, f"v1:{job_id}:4")
    for cursor in ("v2:x:0", "v1::0", f"v1:{job_id}:-1", "garbage", "v1:a:0:1"):
        with pytest.raises(ToolError, match="Invalid cursor"):
            _status(job_id, cursor)


def test_cursor_missing_log_after_state_read_uses_existing_error(
    cursor_store, monkeypatch
):
    job_id, _, directory = _record(cursor_store, monkeypatch, data=b"abc")
    (directory / "out.log").unlink()
    with pytest.raises(ToolError, match="No job with id"):
        _status(job_id, "start")


def test_cursor_quiet_running_job_can_have_unread_output(cursor_store, monkeypatch):
    job_id, _, _ = _record(
        cursor_store,
        monkeypatch,
        data=b"abcdefgh",
        state_name="running",
        last_output_age_s=100.0,
    )
    monkeypatch.setattr(jobs, "RUN_MAX_OUTPUT_CHARS", 4)
    payload = _status(job_id, "start")
    assert payload["quiet"] is True
    assert payload["log_delta"] == "abcd"
    assert payload["has_more"] is True


def test_cursor_pending_utf8_suffix_flushes_after_exit(cursor_store, monkeypatch):
    data = b"A" + "😀".encode()[:2]
    job_id, state, _ = _record(
        cursor_store, monkeypatch, data=data, state_name="running"
    )

    running = _status(job_id, "start")
    assert running["log_delta"] == "A"
    assert running["delta_end"] == 1
    assert running["has_more"] is False

    state["state"] = "exited"
    state["exit_code"] = 0
    terminal = _status(job_id, running["next_cursor"])
    assert terminal["log_delta"] == "�"
    assert terminal["delta_start"] == 1
    assert terminal["delta_end"] == len(data)
    assert terminal["has_more"] is False


def test_cursor_invalid_bytes_are_consumed_with_replacement(cursor_store, monkeypatch):
    job_id, _, _ = _record(cursor_store, monkeypatch, data=b"A" + bytes([0xFF]) + b"B")
    payload = _status(job_id, "start")
    assert payload["log_delta"] == "A�B"
    assert payload["delta_end"] == 3
    assert payload["has_more"] is False


def test_cursor_zero_configured_limit_still_progresses(cursor_store, monkeypatch):
    job_id, _, _ = _record(cursor_store, monkeypatch, data=b"abcdefgh")
    monkeypatch.setattr(jobs, "RUN_MAX_OUTPUT_CHARS", 0)
    payload = _status(job_id, "start")
    assert payload["log_delta"] == "abcd"
    assert payload["delta_end"] == 4
    assert payload["has_more"] is True


def test_cursor_unknown_job_state_is_readable_and_final(cursor_store, monkeypatch):
    data = b"ok" + "猫".encode()[:2]
    job_id, _, _ = _record(cursor_store, monkeypatch, data=data, state_name="unknown")
    payload = _status(job_id, "start")
    assert payload["state"] == "unknown"
    assert payload["log_delta"] == "ok�"
    assert payload["delta_end"] == len(data)
    assert payload["has_more"] is False


def test_cursor_emits_telemetry_field_list(cursor_store, monkeypatch, caplog):
    job_id, _, _ = _record(cursor_store, monkeypatch, data=b"abcdef")
    monkeypatch.setattr(jobs, "RUN_MAX_OUTPUT_CHARS", 4)
    token = current_call.set("cursor-call")
    try:
        with caplog.at_level("INFO", logger="binnacle.job_status"):
            _status(job_id, "start")
    finally:
        current_call.reset(token)

    line = next(
        line for line in caplog.messages if line.startswith("event=job_status_cursor ")
    )
    assert "call=cursor-call" in line
    assert f"job_id={job_id}" in line
    assert (
        "delta_start=0 delta_end=4 returned_chars=4 has_more=true log_bytes=6"
    ) in line


def test_tail_mode_payload_remains_legacy_shape(cursor_store, monkeypatch):
    job_id, _, _ = _record(cursor_store, monkeypatch, data=b"one\ntwo\n")
    result = js.job_status_impl(job_id, 1, 0)
    assert result.structured_content is not None
    payload = result.structured_content
    assert payload["log_tail"] == "two"
    assert (
        not {
            "log_delta",
            "delta_start",
            "delta_end",
            "next_cursor",
            "has_more",
        }
        & payload.keys()
    )


def test_cursor_missing_job_uses_existing_error(cursor_store, monkeypatch):
    monkeypatch.setattr(jobs, "job_state", lambda _requested: None)
    with pytest.raises(ToolError, match="No job with id"):
        _status("prunedjob001", "start")
