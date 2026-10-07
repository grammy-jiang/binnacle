"""Explicit platform construction and job-engine activation contracts."""


def test_constructors_are_lazy_and_return_current_adapters(monkeypatch):
    from binnacle import job_platform
    from binnacle.platform.linux import job_cgroup, job_process

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


def test_accounting_capture_survives_binding_change_before_finalizer(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from binnacle import job_resource_history, jobs

    events = []
    pending = []
    counters = iter(({"processes": 1}, {"processes": 0, "memory_peak": 456}))
    cleaned = iter((False, True))
    identity = "opaque:identity"

    def wrap(argv, scope):
        assert argv == ["bash", "-c", "true"] and scope == identity
        events.append("wrap")
        return argv

    accounting = SimpleNamespace(
        create=lambda job: identity,
        wrap_argv=wrap,
        snapshot=lambda scope: next(counters),
        cleanup=lambda scope: next(cleaned),
        wait_empty=lambda scope: events.append(("wait", scope)) or True,
    )

    class DeferredThread:
        def __init__(self, *, target, name, daemon):
            pending.append(target)
            assert daemon is True

        def start(self):
            pass

    monkeypatch.setattr(jobs, "_RESOURCE_ACCOUNTING", accounting)
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(job_resource_history.threading, "Thread", DeferredThread)
    job_id, handle = jobs.start_job("true", tmp_path, None, owner_instance_id="owner")
    handle.wait(timeout=5)
    jobs.record_exit(job_id, handle)
    before = jobs._read_meta(job_id)
    assert before["cgroup"] == identity
    assert before["cgroup_cleanup_pending"] is True
    assert before["exit_code"] == 0
    monkeypatch.setattr(jobs, "_RESOURCE_ACCOUNTING", object())
    assert len(pending) == 1
    pending[0]()
    after = jobs._read_meta(job_id)
    assert "cgroup_cleanup_pending" not in after
    assert after["ended_at"] == before["ended_at"] and after["exit_code"] == 0
    assert after["resource_usage"] == {"processes": 0, "memory_peak": 456}
    assert after["resource_history_path"]
    assert events == ["wrap", ("wait", identity)]


def test_manager_prepares_selected_accounting_before_recovery(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from binnacle import job_manager, jobs

    socket = tmp_path / "private" / "manager.sock"
    events = []

    def prepare(*, log_ready):
        assert log_ready is True and not socket.parent.exists()
        events.append("accounting")

    def recover(owner, boot):
        assert socket.parent.is_dir()
        events.append((owner, boot))
        return 3

    monkeypatch.setattr(jobs, "_RESOURCE_ACCOUNTING", SimpleNamespace(prepare=prepare))
    monkeypatch.setattr(job_manager.job_owner, "recover_previous_owner", recover)
    manager = job_manager.JobManager(socket, owner_instance_id="owner", boot_id="boot")
    assert manager.prepare() == 3
    assert events == ["accounting", ("owner", "boot")]


def test_manager_owned_command_runs_without_accounting(tmp_path, monkeypatch):
    from binnacle import jobs
    from binnacle.platform.contracts.resource_contracts import NoResourceAccounting

    monkeypatch.setattr(jobs, "_RESOURCE_ACCOUNTING", NoResourceAccounting())
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    job_id, handle = jobs.start_job(
        "printf missing-accounting", tmp_path, None, owner_instance_id="owner"
    )
    handle.wait(timeout=5)
    jobs.record_exit(job_id, handle)
    state = jobs.job_state(job_id)
    assert state["exit_code"] == 0 and state["resource_usage"] is None
    assert state["cgroup"] is None
    assert jobs.read_log(job_id) == b"missing-accounting"
