"""Full MCP capture settings, file integrity and private retention behavior."""

import base64
import json
import stat
from enum import Enum
from pathlib import Path
from threading import Thread

import pytest
from pydantic import ValidationError

from binnacle.config import Settings
from binnacle.config_telemetry import FullCaptureSettings
from binnacle.observability.full_capture import FullCaptureSink, _secure_root


def _rows(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for f in sorted(path.glob("*.jsonl"))
        for line in f.read_text().splitlines()
    ]


def test_disabled_by_default_and_configured_explicitly(tmp_path, monkeypatch):
    monkeypatch.setenv("BINNACLE_CONFIG_FILE", str(tmp_path / "absent.toml"))
    assert Settings().telemetry.full_capture.enabled is False
    assert not (tmp_path / "full").exists()
    config = tmp_path / "explicit.toml"
    config.write_text(
        "[telemetry.full_capture]\nenabled = true\n"
        f'directory = "{tmp_path}/full"\nfsync = true\n'
    )
    monkeypatch.setenv("BINNACLE_CONFIG_FILE", str(config))
    value = Settings().telemetry.full_capture
    assert value.enabled and value.fsync
    assert value.directory == tmp_path / "full"
    assert not value.directory.exists()
    monkeypatch.setenv("BINNACLE_TELEMETRY__FULL_CAPTURE__ENABLED", "false")
    assert Settings().telemetry.full_capture.enabled is False


@pytest.mark.parametrize("key", ["unknown_toggle", "directory_extra", "redact"])
def test_full_capture_typo_fails_closed(key):
    with pytest.raises(ValidationError, match=key):
        FullCaptureSettings.model_validate({key: True})


def test_enabled_rejects_relative_directory():
    with pytest.raises(ValidationError, match="absolute"):
        FullCaptureSettings(enabled=True, directory=Path("relative/directory"))
    assert not FullCaptureSettings(enabled=False, directory=Path("relative")).enabled


def test_writer_keeps_full_multiline_unicode_and_binary(tmp_path):
    output = tmp_path / "private"
    sink = FullCaptureSink(FullCaptureSettings(enabled=True, directory=output))
    payload = "中文\n" + "x" * 9000
    sink.write("tool_call", arguments={"command": payload, "stdin": b"\x00\xff"})
    rows = _rows(output)
    assert len(rows) == 1
    assert rows[0]["arguments"]["command"] == payload
    assert rows[0]["arguments"]["stdin"]["__bytes_base64__"] == base64.b64encode(
        b"\x00\xff"
    ).decode("ascii")
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert stat.S_IMODE(next(output.glob("*.jsonl")).stat().st_mode) == 0o600


def test_symlinked_capture_directory_refused(tmp_path):
    real = tmp_path / "private"
    real.mkdir(mode=0o700)
    target = tmp_path / "shortcut"
    target.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        FullCaptureSink(FullCaptureSettings(enabled=True, directory=target))


def test_group_readable_directory_refused(tmp_path):
    target = tmp_path / "not-private"
    target.mkdir(mode=0o755)
    target.chmod(0o755)
    with pytest.raises(PermissionError, match="private"):
        FullCaptureSink(FullCaptureSettings(enabled=True, directory=target))
    assert stat.S_IMODE(target.stat().st_mode) == 0o755


@pytest.mark.parametrize("filetype", ["symlink", "insecure"])
def test_writer_refuses_symlink_or_insecure_existing_file(tmp_path, filetype):
    output = tmp_path / "private"
    sink = FullCaptureSink(FullCaptureSettings(enabled=True, directory=output))
    import datetime

    day = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    target = output / f"{day}.jsonl"
    if filetype == "symlink":
        target.symlink_to(tmp_path / "outside")
    else:
        target.write_text("existing\n")
        target.chmod(0o644)
    with pytest.raises((PermissionError, OSError)):
        sink.write("tool_call", arguments={"content": "must not be leaked"})
    if filetype == "symlink":
        assert not (tmp_path / "outside").exists()
    else:
        assert target.read_text() == "existing\n"


def test_unsupported_object_never_writes_partial_row(tmp_path):
    output = tmp_path / "private"
    sink = FullCaptureSink(FullCaptureSettings(enabled=True, directory=output))
    with pytest.raises(TypeError, match="unsupported full-capture"):
        sink.write("request", payload=object())
    assert not list(output.glob("*.jsonl"))


def test_best_effort_failure_is_logged_without_private_value(tmp_path, caplog):
    sink = FullCaptureSink(
        FullCaptureSettings(enabled=True, directory=tmp_path / "private")
    )
    with caplog.at_level("ERROR"):
        sink.best_effort("tool_result", response=object(), secret="never-journal")
    assert "event=full_capture_error" in caplog.text
    assert "never-journal" not in caplog.text
    assert not list((tmp_path / "private").glob("*.jsonl"))


def test_concurrent_records_are_complete_jsonl(tmp_path):
    output = tmp_path / "private"
    sink = FullCaptureSink(FullCaptureSettings(enabled=True, directory=output))

    def writer(index):
        for step in range(8):
            sink.write("test", worker=index, step=step, content=str(index) * 2000)

    threads = [Thread(target=writer, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert len(_rows(output)) == 32


def test_private_writer_serializes_path_enum_and_fsync(tmp_path, monkeypatch):
    class Phase(Enum):
        READY = "ready"

    import os

    calls = []
    original_fsync = os.fsync

    def spy_fsync(fd):
        calls.append(fd)
        return original_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    root = tmp_path / "private"
    sink = FullCaptureSink(
        FullCaptureSettings(enabled=True, directory=root, fsync=True)
    )
    sink.write("other", path=tmp_path / "file", phase=Phase.READY)
    rows = _rows(root)
    assert rows[0]["path"] == str(tmp_path / "file")
    assert rows[0]["phase"] == "ready"
    assert len(calls) == 1


def test_disabled_sink_and_relative_root_fail(tmp_path):
    with pytest.raises(ValueError, match="enabled=true"):
        FullCaptureSink(FullCaptureSettings(enabled=False, directory=tmp_path))
    with pytest.raises(ValueError, match="absolute"):
        _secure_root(Path("not-an-absolute-path"))


def test_incomplete_write_is_visible_and_not_silently_retried(tmp_path, monkeypatch):
    import os

    sink = FullCaptureSink(
        FullCaptureSettings(enabled=True, directory=tmp_path / "private")
    )
    monkeypatch.setattr(os, "write", lambda fd, data: 0)
    with pytest.raises(OSError, match="made no progress"):
        sink.write("attempt", content="full result")
    assert _rows(tmp_path / "private") == []


def test_required_capture_fails_before_operation(tmp_path, caplog):
    sink = FullCaptureSink(
        FullCaptureSettings(enabled=True, directory=tmp_path / "private")
    )
    with caplog.at_level("ERROR"), pytest.raises(RuntimeError, match="not executed"):
        sink.required("mcp_request", secret=object())
    assert "event=full_capture_error" in caplog.text
    assert "secret" not in caplog.text
