"""Deterministic /proc failure and race coverage for job_process."""

from types import SimpleNamespace

from binnacle import job_process


def test_proc_starttime_tolerates_short_and_invalid_stat(monkeypatch):
    monkeypatch.setattr(job_process, "_proc_stat_fields", lambda pid: ["x"])
    assert job_process._proc_starttime(123) is None

    fields = ["0"] * 20
    fields[19] = "not-an-int"
    monkeypatch.setattr(job_process, "_proc_stat_fields", lambda pid: fields)
    assert job_process._proc_starttime(123) is None


def test_descendants_skips_vanished_and_malformed_proc_entries(monkeypatch):
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

    monkeypatch.setattr(job_process, "_proc_stat_fields", fields)

    assert job_process._descendants(1) == {12}


def test_uptime_failure_returns_zero(monkeypatch):
    class BrokenPath:
        def read_text(self):
            raise OSError("proc unavailable")

    monkeypatch.setattr(job_process, "Path", lambda path: BrokenPath())
    assert job_process._uptime_s() == 0.0


def test_job_processes_tolerates_process_vanishing_during_scan(tmp_path, monkeypatch):
    vanished = tmp_path / "12345"
    entry = SimpleNamespace(name="12345", path=str(vanished))
    monkeypatch.setattr(job_process.os, "scandir", lambda path: [entry])

    assert job_process.job_processes(12345) == []
