"""Deterministic /proc failure and race coverage for job_process."""

import signal
from pathlib import Path
from types import SimpleNamespace

import pytest

from binnacle.platform.linux import job_process


@pytest.fixture(params=["helpers", "backend"])
def inspection(request):
    if request.param == "backend":
        return job_process.LinuxProcessBackend()
    return SimpleNamespace(
        starttime=job_process._proc_starttime,
        alive=job_process._pid_alive,
        descendants=job_process._descendants,
        processes=job_process.job_processes,
    )


def test_proc_starttime_tolerates_short_and_invalid_stat(monkeypatch, inspection):
    monkeypatch.setattr(job_process, "_proc_stat_fields", lambda pid: ["x"])
    assert inspection.starttime(123) is None

    fields = ["0"] * 20
    fields[19] = "not-an-int"
    monkeypatch.setattr(job_process, "_proc_stat_fields", lambda pid: fields)
    assert inspection.starttime(123) is None


def test_descendants_skips_vanished_and_malformed_proc_entries(monkeypatch, inspection):
    entries = [
        SimpleNamespace(name="not-a-pid"),
        SimpleNamespace(name="10"),
        SimpleNamespace(name="11"),
        SimpleNamespace(name="12"),
        # Duplicate entry deliberately exercises the already-seen child branch.
        SimpleNamespace(name="12"),
    ]
    monkeypatch.setattr(job_process.os, "scandir", lambda path: entries)

    def fields(pid):
        if pid == 10:
            return None
        if pid == 11:
            return ["S"]  # no ppid field
        if pid == 12:
            return ["S", "1"]
        return None

    monkeypatch.setattr(job_process, "_proc_stat_fields", fields)

    assert inspection.descendants(1) == {12}


def test_uptime_failure_returns_zero(monkeypatch):
    class BrokenPath:
        def read_text(self):
            raise OSError("proc unavailable")

    monkeypatch.setattr(job_process, "Path", lambda path: BrokenPath())
    assert job_process._uptime_s() == 0.0


def test_job_processes_tolerates_process_vanishing_during_scan(
    tmp_path, monkeypatch, inspection
):
    vanished = tmp_path / "12345"
    entry = SimpleNamespace(name="12345", path=str(vanished))
    monkeypatch.setattr(job_process.os, "scandir", lambda path: [entry])

    assert inspection.processes(12345) == []


def test_stat_comm_parentheses_and_sorted_process_summaries(
    tmp_path, monkeypatch, inspection
):
    entries = []
    for pid in (42, 21):
        directory = tmp_path / str(pid)
        directory.mkdir()
        fields = ["S", "1", "42"] + ["0"] * 17
        fields[11:13] = ["100", "50"]
        fields[19] = "200"
        (directory / "stat").write_text(
            f"{pid} (a (name) with spaces) " + " ".join(fields)
        )
        (directory / "cmdline").write_bytes(
            b"long\x00command\x00" if pid == 42 else b""
        )
        entries.append(SimpleNamespace(name=str(pid), path=str(directory)))
    monkeypatch.setattr(job_process.os, "scandir", lambda path: entries)
    monkeypatch.setattr(job_process, "_uptime_s", lambda: 5)
    monkeypatch.setattr(job_process, "_CLK_TCK", 100)
    assert inspection.processes(42, max_cmd_chars=6) == [
        {"pid": 21, "state": "S", "etime_s": 3.0, "cpu_s": 1.5, "cmd": ""},
        {"pid": 42, "state": "S", "etime_s": 3.0, "cpu_s": 1.5, "cmd": "long c"},
    ]


def test_starttime_is_an_opaque_integer_after_parenthesized_comm(
    tmp_path, monkeypatch, inspection
):
    stat = tmp_path / "stat"
    stat.write_text("42 (a (name) with spaces) S " + "0 " * 18 + "18446744073709550000")
    monkeypatch.setattr(job_process, "Path", lambda path: stat)
    assert inspection.starttime(42) == 18446744073709550000
    assert inspection.alive(42, 18446744073709550000)
    assert inspection.alive(42)
    assert not inspection.alive(42, 18446744073709550001)
    stat.write_text("malformed stat without closing delimiter")
    assert inspection.starttime(42) is None
    assert not inspection.alive(42)
    stat.unlink()
    assert inspection.starttime(42) is None
    assert not inspection.alive(42, 18446744073709550000)


def test_descendants_follow_parent_links_across_sessions(monkeypatch, inspection):
    fields = {
        10: ["S", "1", "10", "10"],
        11: ["S", "10", "10", "10"],
        12: ["S", "11", "12", "12"],  # setsid child remains reachable
        13: ["S", "12", "12", "12"],
        14: ["S", "1", "14", "14"],  # already reparented, not reachable
        15: ["S", "bad-ppid"],
    }
    monkeypatch.setattr(
        job_process.os,
        "scandir",
        lambda path: [SimpleNamespace(name=str(p)) for p in fields],
    )
    monkeypatch.setattr(job_process, "_proc_stat_fields", fields.get)
    assert inspection.descendants(10) == {11, 12, 13}


@pytest.mark.parametrize("uptime", ["", "not-a-number", "1.25 0.5"])
def test_uptime_parsing_fallback(tmp_path, monkeypatch, uptime):
    path = tmp_path / "uptime"
    path.write_text(uptime)
    monkeypatch.setattr(job_process, "Path", lambda _: path)
    assert job_process._uptime_s() == (1.25 if uptime == "1.25 0.5" else 0.0)


@pytest.mark.parametrize("bad_field, exception", [(19, ValueError), (11, ValueError)])
def test_summary_numeric_errors_still_propagate(
    tmp_path, monkeypatch, inspection, bad_field, exception
):
    fields = ["S", "1", "42"] + ["0"] * 17
    fields[bad_field] = "malformed"
    (tmp_path / "stat").write_text("42 (name) " + " ".join(fields))
    (tmp_path / "cmdline").write_bytes(b"command")
    monkeypatch.setattr(
        job_process.os,
        "scandir",
        lambda path: [SimpleNamespace(name="42", path=str(tmp_path))],
    )
    with pytest.raises(exception):
        inspection.processes(42)


@pytest.mark.parametrize(
    "intent, sig", [("terminate", signal.SIGTERM), ("kill", signal.SIGKILL)]
)
def test_signal_job_sends_group_then_strays_and_ignores_vanished(
    monkeypatch, intent, sig
):
    calls = []
    monkeypatch.setattr(
        job_process.os, "killpg", lambda pid, sig: calls.append(("group", pid, sig))
    )

    def kill(pid, sig):
        calls.append(("stray", pid, sig))
        if pid == 43:
            raise ProcessLookupError("stray vanished")

    monkeypatch.setattr(job_process.os, "kill", kill)
    job_process.LinuxProcessBackend().signal_job(42, {43, 44}, intent)
    assert calls[0] == ("group", 42, sig)
    assert len(calls) == 3
    assert set(calls[1:]) == {("stray", 43, sig), ("stray", 44, sig)}


@pytest.mark.parametrize(
    "error", [ProcessLookupError("group vanished"), PermissionError("group denied")]
)
def test_signal_job_group_errors_propagate_before_strays(monkeypatch, error):
    calls = []

    def killpg(pid, sig):
        calls.append((pid, sig))
        raise error

    monkeypatch.setattr(job_process.os, "killpg", killpg)
    monkeypatch.setattr(
        job_process.os,
        "kill",
        lambda *args: pytest.fail("stray signaled after group failure"),
    )
    with pytest.raises(type(error)) as raised:
        job_process.LinuxProcessBackend().signal_job(42, {43}, "terminate")
    assert raised.value is error
    assert calls == [(42, signal.SIGTERM)]


def test_signal_job_stray_permission_error_propagates(monkeypatch):
    monkeypatch.setattr(job_process.os, "killpg", lambda *args: None)
    error = PermissionError("stray denied")

    def kill(pid, sig):
        raise error

    monkeypatch.setattr(job_process.os, "kill", kill)
    with pytest.raises(PermissionError) as raised:
        job_process.LinuxProcessBackend().signal_job(42, {43}, "kill")
    assert raised.value is error


@pytest.mark.parametrize(
    "contents, expected", [("  boot-token\n", "boot-token"), ("", "")]
)
def test_boot_id_preserves_stripped_contents(monkeypatch, contents, expected):
    def read_text(path):
        assert path == Path("/proc/sys/kernel/random/boot_id")
        return contents

    monkeypatch.setattr(Path, "read_text", read_text)
    assert job_process.LinuxProcessBackend().boot_id() == expected


@pytest.mark.parametrize(
    "error",
    [FileNotFoundError("missing"), PermissionError("denied"), ValueError("bad read")],
)
def test_boot_id_only_os_errors_fall_back(monkeypatch, error):
    def read_text(path):
        raise error

    monkeypatch.setattr(Path, "read_text", read_text)
    backend = job_process.LinuxProcessBackend()
    if isinstance(error, OSError):
        assert backend.boot_id() == "unknown"
    else:
        with pytest.raises(ValueError) as raised:
            backend.boot_id()
        assert raised.value is error
