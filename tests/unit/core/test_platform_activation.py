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
    handle = SimpleNamespace(pid=771, returncode=0, wait=lambda timeout: 0)
    backend = SimpleNamespace(
        launch=lambda *args, **kwargs: handle,
        starttime=lambda pid: calls.append(("starttime", pid)) or 912,
        alive=lambda pid, token: calls.append(("alive", pid, token)) or True,
        processes=lambda pgid, max_cmd_chars=200: (
            calls.append(("processes", pgid, max_cmd_chars)) or summaries
        ),
        descendants=lambda pid: calls.append(("descendants", pid)) or {17, 19},
        signal_job=lambda *args: None,
    )
    monkeypatch.setattr(jobs, "_PROCESS_BACKEND", backend)
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    job_id, proc = jobs.start_job("true", tmp_path, None)
    proc.wait(timeout=5)
    assert jobs._read_meta(job_id)["starttime"] == 912
    assert jobs.job_state(job_id)["state"] == "running"
    assert jobs.job_processes(proc.pid, 33) is summaries
    signals = []
    monkeypatch.setattr(backend, "signal_job", lambda *args: signals.append(args))
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


def test_jobs_launch_passes_owned_files_and_preserves_handle(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from binnacle import jobs

    handle = SimpleNamespace(pid=771, returncode=-9)
    seen = []
    payload = "large stdin\n" * 10000

    def launch(argv, *, workdir, env, stdin, output):
        assert argv == ["bash", "-c", "fake-command"]
        assert workdir == tmp_path
        assert env["BINNACLE"] == "1" and env["PAGER"] == "cat"
        assert env["BINNACLE_JOB_ID"]
        assert stdin.read() == payload.encode()
        assert not output.closed
        output.write(b"fake output")
        seen.extend((stdin, output))
        return handle

    backend = SimpleNamespace(launch=launch, starttime=lambda pid: 42)
    monkeypatch.setattr(jobs, "_PROCESS_BACKEND", backend)
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    job_id, proc = jobs.start_job("fake-command", tmp_path, payload)
    assert proc is handle and all(stream.closed for stream in seen)
    jobs.record_exit(job_id, proc)
    assert jobs.job_state(job_id)["signal"] == 9
    assert jobs.read_log(job_id) == b"fake output"


def test_manager_boot_identity_uses_default_process_seam(monkeypatch):
    from types import SimpleNamespace

    from binnacle import job_manager

    monkeypatch.setattr(
        job_manager,
        "create_process_backend",
        lambda: SimpleNamespace(boot_id=lambda: "opaque-boot"),
    )
    assert job_manager._boot_id() == "opaque-boot"
