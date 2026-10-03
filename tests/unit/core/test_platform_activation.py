"""Explicit platform construction and job-engine activation contracts."""


def test_constructors_are_lazy_and_return_current_adapters(monkeypatch):
    from binnacle import job_cgroup, job_platform, job_process

    process = object()
    accounting = object()
    monkeypatch.setattr(job_process, "LinuxProcessBackend", lambda: process)
    monkeypatch.setattr(job_cgroup, "CgroupResourceAccounting", lambda: accounting)
    assert job_platform.create_process_backend() is process
    assert job_platform.create_resource_accounting() is accounting


def test_jobs_read_identity_and_inspection_through_one_binding(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from binnacle import jobs

    calls = []
    summaries = [{"pid": 17}]
    backend = SimpleNamespace(
        starttime=lambda pid: calls.append(("starttime", pid)) or 912,
        alive=lambda pid, token: calls.append(("alive", pid, token)) or True,
        processes=lambda pgid, max_cmd_chars=200: (
            calls.append(("processes", pgid, max_cmd_chars)) or summaries
        ),
        descendants=lambda pid: calls.append(("descendants", pid)) or {17, 19},
    )
    monkeypatch.setattr(jobs, "_PROCESS_BACKEND", backend)
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    job_id, proc = jobs.start_job("true", tmp_path, None)
    proc.wait(timeout=5)
    assert jobs._read_meta(job_id)["starttime"] == 912
    assert jobs.job_state(job_id)["state"] == "running"
    assert jobs.job_processes(proc.pid, 33) is summaries
    signals = []
    monkeypatch.setattr(jobs, "_signal_job", lambda *args: signals.append(args))
    monkeypatch.setattr(jobs, "await_exit", lambda *args: {"state": "exited"})
    assert jobs.stop_job_embedded(job_id) == {"state": "exited"}
    assert signals[0][:2] == (proc.pid, {19})
    assert calls == [
        ("starttime", proc.pid),
        ("alive", proc.pid, 912),
        ("processes", proc.pid, 33),
        ("alive", proc.pid, 912),
        ("processes", proc.pid, 200),
        ("descendants", proc.pid),
    ]
    jobs.record_exit(job_id, proc)
