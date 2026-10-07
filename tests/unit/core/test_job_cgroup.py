from __future__ import annotations

import pytest

from binnacle.platform.linux import job_cgroup


def test_process_cgroup_reads_unified_entry(tmp_path):
    proc = tmp_path / "self"
    proc.mkdir()
    (proc / "cgroup").write_text("0::/user.slice/demo.service\n")
    assert job_cgroup.process_cgroup(proc_root=tmp_path) == "/user.slice/demo.service"


def test_create_is_best_effort_and_scoped_to_job_id(tmp_path, monkeypatch):
    monkeypatch.setattr(job_cgroup, "process_cgroup", lambda **kwargs: "/demo.service")
    (tmp_path / "demo.service").mkdir()
    rel = job_cgroup.create("012345abcdef", cgroup_fs=tmp_path)
    assert rel == "/demo.service/job-012345abcdef"
    assert (tmp_path / "demo.service/job-012345abcdef").is_dir()
    assert job_cgroup.create("../../escape", cgroup_fs=tmp_path) is None


def test_prepare_uses_delegated_service_root_and_enables_controllers(tmp_path):
    proc = tmp_path / "proc" / "self"
    proc.mkdir(parents=True)
    proc.joinpath("cgroup").write_text("0::/user.slice/demo.service/binnacle-manager\n")
    root = tmp_path / "cg" / "user.slice" / "demo.service"
    root.mkdir(parents=True)
    root.joinpath("cgroup.controllers").write_text("cpu memory pids\n")
    root.joinpath("cgroup.subtree_control").write_text("")
    got = job_cgroup.prepare(cgroup_fs=tmp_path / "cg", proc_root=tmp_path / "proc")
    assert got == "/user.slice/demo.service"
    # A real cgroupfs interprets +controller commands; the synthetic file stores
    # the exact command, which proves all required controllers were requested.
    assert root.joinpath("cgroup.subtree_control").read_text() == "+cpu +memory +pids"


def test_launch_argv_moves_same_shell_then_execs_command(tmp_path):
    cg = tmp_path / "demo/job-012345abcdef"
    cg.mkdir(parents=True)
    procs = cg / "cgroup.procs"
    procs.write_text("")
    argv = job_cgroup.launch_argv(
        "printf payload", "/demo/job-012345abcdef", cgroup_fs=tmp_path
    )
    assert argv[:2] == ["bash", "-c"]
    assert str(procs) in argv
    assert argv[-1] == "printf payload"


def test_snapshot_collects_only_available_controllers(tmp_path):
    cg = tmp_path / "demo/job-012345abcdef"
    cg.mkdir(parents=True)
    (cg / "cpu.stat").write_text(
        "usage_usec 100\nuser_usec 70\nsystem_usec 30\nnr_periods 4\n"
    )
    (cg / "io.stat").write_text(
        "259:0 rbytes=100 wbytes=20 rios=2 wios=1\n"
        "179:0 rbytes=7 wbytes=3 rios=1 wios=1\n"
    )
    (cg / "memory.current").write_text("4096\n")
    (cg / "memory.peak").write_text("8192\n")
    (cg / "memory.swap.current").write_text("1024\n")
    (cg / "memory.swap.peak").write_text("2048\n")
    (cg / "memory.stat").write_text("anon 6000\nfile 1000\nshmem 200\n")
    (cg / "memory.events").write_text("low 0\nhigh 2\nmax 0\noom 0\noom_kill 0\n")
    (cg / "memory.swap.events").write_text("high 1\nmax 0\nfail 0\n")
    (cg / "pids.current").write_text("2\n")
    (cg / "pids.peak").write_text("5\n")
    (cg / "cgroup.procs").write_text("12\n13\n")
    got = job_cgroup.snapshot("/demo/job-012345abcdef", cgroup_fs=tmp_path)
    assert got["cpu"] == {
        "usage_usec": 100,
        "user_usec": 70,
        "system_usec": 30,
        "nr_periods": 4,
    }
    assert got["io"] == {"rbytes": 107, "wbytes": 23, "rios": 3, "wios": 2}
    assert got["memory_current"] == 4096
    assert got["memory_peak"] == 8192
    assert got["memory_swap_current"] == 1024
    assert got["memory_swap_peak"] == 2048
    assert got["memory_stat"] == {"anon": 6000, "file": 1000, "shmem": 200}
    assert got["memory_events"]["high"] == 2
    assert got["memory_swap_events"]["high"] == 1
    assert got["pids_current"] == 2
    assert got["pids_peak"] == 5
    assert got["processes"] == 2


def test_cleanup_keeps_populated_cgroup_and_removes_empty(tmp_path):
    cg = tmp_path / "demo/job-012345abcdef"
    cg.mkdir(parents=True)
    marker = cg / "synthetic"
    marker.write_text("x")
    assert not job_cgroup.cleanup("/demo/job-012345abcdef", cgroup_fs=tmp_path)
    marker.unlink()
    assert job_cgroup.cleanup("/demo/job-012345abcdef", cgroup_fs=tmp_path)
    assert not cg.exists()


def test_process_cgroup_missing_and_legacy_entries_return_none(tmp_path):
    assert job_cgroup.process_cgroup(proc_root=tmp_path) is None
    proc = tmp_path / "self"
    proc.mkdir()
    (proc / "cgroup").write_text("2:cpu:/legacy\n1:name=systemd:/user.slice\n")
    assert job_cgroup.process_cgroup(proc_root=tmp_path) is None


def test_accounting_root_handles_absent_plain_and_delegated(tmp_path, monkeypatch):
    monkeypatch.setattr(job_cgroup, "process_cgroup", lambda **kw: None)
    assert job_cgroup.accounting_root(proc_root=tmp_path) is None
    monkeypatch.setattr(job_cgroup, "process_cgroup", lambda **kw: "/demo.service")
    assert job_cgroup.accounting_root(proc_root=tmp_path) == "/demo.service"
    monkeypatch.setattr(
        job_cgroup,
        "process_cgroup",
        lambda **kw: "/demo.service/binnacle-manager",
    )
    assert job_cgroup.accounting_root(proc_root=tmp_path) == "/demo.service"


def test_prepare_handles_absent_and_non_delegated_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(job_cgroup, "accounting_root", lambda **kw: None)
    assert job_cgroup.prepare(cgroup_fs=tmp_path) is None

    monkeypatch.setattr(job_cgroup, "accounting_root", lambda **kw: "/demo.service")
    (tmp_path / "demo.service").mkdir()
    # Missing controller files means cgroup accounting is optional, not fatal.
    assert job_cgroup.prepare(cgroup_fs=tmp_path) == "/demo.service"


def test_prepare_is_idempotent_and_can_log_ready(tmp_path, monkeypatch, caplog):
    root = tmp_path / "demo.service"
    root.mkdir()
    (root / "cgroup.controllers").write_text("cpu memory pids\n")
    (root / "cgroup.subtree_control").write_text("cpu memory pids\n")
    monkeypatch.setattr(job_cgroup, "accounting_root", lambda **kw: "/demo.service")
    with caplog.at_level("INFO", logger="binnacle.jobs"):
        assert job_cgroup.prepare(cgroup_fs=tmp_path, log_ready=True) == "/demo.service"
    assert "event=job_cgroup_ready" in caplog.text


def test_prepare_controller_write_failure_is_best_effort(tmp_path, monkeypatch, caplog):
    root = tmp_path / "demo.service"
    root.mkdir()
    controllers = root / "cgroup.controllers"
    subtree = root / "cgroup.subtree_control"
    controllers.write_text("cpu memory pids\n")
    subtree.write_text("")
    monkeypatch.setattr(job_cgroup, "accounting_root", lambda **kw: "/demo.service")
    original = type(subtree).write_text

    def fail_subtree(self, data, *args, **kwargs):
        if self == subtree:
            raise PermissionError("not delegated")
        return original(self, data, *args, **kwargs)

    monkeypatch.setattr(type(subtree), "write_text", fail_subtree)
    with caplog.at_level("INFO", logger="binnacle.jobs"):
        assert job_cgroup.prepare(cgroup_fs=tmp_path) == "/demo.service"
    assert "event=job_cgroup_controller_unavailable" in caplog.text


def test_prepare_second_subtree_read_failure_is_tolerated(tmp_path, monkeypatch):
    root = tmp_path / "demo.service"
    root.mkdir()
    controllers = root / "cgroup.controllers"
    subtree = root / "cgroup.subtree_control"
    controllers.write_text("cpu memory pids\n")
    subtree.write_text("")
    monkeypatch.setattr(job_cgroup, "accounting_root", lambda **kw: "/demo.service")
    original = type(subtree).read_text
    reads = 0

    def flaky_read(self, *args, **kwargs):
        nonlocal reads
        if self == subtree:
            reads += 1
            if reads == 2:
                raise OSError("synthetic reread failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(type(subtree), "read_text", flaky_read)
    assert job_cgroup.prepare(cgroup_fs=tmp_path) == "/demo.service"
    assert reads == 2


def test_create_without_parent_or_writable_parent_is_best_effort(tmp_path, monkeypatch):
    monkeypatch.setattr(job_cgroup, "prepare", lambda **kw: None)
    assert job_cgroup.create("012345abcdef", cgroup_fs=tmp_path) is None

    monkeypatch.setattr(job_cgroup, "prepare", lambda **kw: "/missing/service")
    assert job_cgroup.create("012345abcdef", cgroup_fs=tmp_path) is None


def test_launch_without_cgroup_is_plain_bash():
    assert job_cgroup.launch_argv("printf ok", None) == ["bash", "-c", "printf ok"]


def test_kv_and_io_parsers_ignore_malformed_values(tmp_path):
    kv = tmp_path / "kv"
    kv.write_text("good 7\nmissing\nextra 1 2\nbad nope\n")
    assert job_cgroup._kv(kv) == {"good": 7}
    assert job_cgroup._kv(tmp_path / "absent") == {}

    io = tmp_path / "io"
    io.write_text("259:0 rbytes=10 broken wbytes=nope rios=2\n259:1 rbytes=5 rios=3\n")
    assert job_cgroup._io(io) == {"rbytes": 15, "rios": 5}
    assert job_cgroup._io(tmp_path / "absent-io") == {}


def test_snapshot_absent_and_partial_files_are_tolerated(tmp_path):
    assert job_cgroup.snapshot(None, cgroup_fs=tmp_path) == {}
    assert job_cgroup.snapshot("/missing", cgroup_fs=tmp_path) == {}

    root = tmp_path / "demo"
    root.mkdir()
    (root / "cpu.stat").write_text("malformed\n")
    (root / "io.stat").write_text("259:0 nope\n")
    (root / "memory.stat").write_text("")
    (root / "memory.events").write_text("")
    (root / "memory.swap.events").write_text("")
    (root / "memory.current").write_text("not-an-int\n")
    # No cgroup.procs on purpose: missing optional files stay omitted.
    assert job_cgroup.snapshot("/demo", cgroup_fs=tmp_path) == {}


def test_cleanup_none_missing_and_move_pid_paths(tmp_path):
    assert job_cgroup.cleanup(None, cgroup_fs=tmp_path)
    assert job_cgroup.cleanup("/already-gone", cgroup_fs=tmp_path)

    root = tmp_path / "demo"
    root.mkdir()
    procs = root / "cgroup.procs"
    procs.write_text("")
    assert job_cgroup.move_pid(123, "/demo", cgroup_fs=tmp_path)
    assert procs.read_text() == "123\n"
    assert not job_cgroup.move_pid(123, "/missing", cgroup_fs=tmp_path)


def test_wait_empty_uses_event_driven_poll_without_timeout(tmp_path, monkeypatch):
    root = tmp_path / "demo"
    root.mkdir()
    events = root / "cgroup.events"
    events.write_text("populated 1\nfrozen 0\n")
    reads = iter([b"populated 1\nfrozen 0\n", b"populated 0\nfrozen 0\n"])
    poll_calls: list[tuple[object, ...]] = []
    closed: list[int] = []

    monkeypatch.setattr(job_cgroup.os, "open", lambda *args: 42)
    monkeypatch.setattr(job_cgroup.os, "lseek", lambda *args: 0)
    monkeypatch.setattr(job_cgroup.os, "read", lambda *args: next(reads))
    monkeypatch.setattr(job_cgroup.os, "close", lambda fd: closed.append(fd))

    class FakePoll:
        def register(self, fd, mask):
            assert fd == 42
            assert mask == job_cgroup.select.POLLPRI | job_cgroup.select.POLLERR

        def poll(self, *args):
            poll_calls.append(args)
            return [(42, job_cgroup.select.POLLPRI)]

    monkeypatch.setattr(job_cgroup.select, "poll", FakePoll)
    assert job_cgroup.wait_empty("/demo", cgroup_fs=tmp_path)
    assert poll_calls == [()]  # no timer: the kernel event is the only wakeup
    assert closed == [42]


def test_wait_empty_handles_open_missing_event_and_already_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(
        job_cgroup.os, "open", lambda *args: (_ for _ in ()).throw(OSError("missing"))
    )
    assert not job_cgroup.wait_empty("/missing", cgroup_fs=tmp_path)

    root = tmp_path / "demo"
    root.mkdir()
    (root / "cgroup.events").write_text("populated 0\nfrozen 0\n")
    # Restore real os functions after the synthetic open failure.
    monkeypatch.undo()
    assert job_cgroup.wait_empty("/demo", cgroup_fs=tmp_path)


def test_wait_empty_rejects_unreadable_or_unrecognised_events(tmp_path, monkeypatch):
    root = tmp_path / "demo"
    root.mkdir()
    (root / "cgroup.events").write_text("frozen 0\n")
    assert not job_cgroup.wait_empty("/demo", cgroup_fs=tmp_path)

    monkeypatch.setattr(
        job_cgroup.os, "read", lambda *args: (_ for _ in ()).throw(OSError("read"))
    )
    assert not job_cgroup.wait_empty("/demo", cgroup_fs=tmp_path)


def test_cleanup_permission_failure_retains_the_scope(tmp_path, monkeypatch):
    root = tmp_path / "demo"
    root.mkdir()

    def denied(self):
        assert self == root
        raise PermissionError("synthetic cleanup denial")

    monkeypatch.setattr(type(root), "rmdir", denied)
    assert job_cgroup.cleanup("/demo", cgroup_fs=tmp_path) is False
    assert root.is_dir()


@pytest.mark.parametrize("read_failure", [False, True])
def test_wait_empty_closes_fd_when_event_wait_fails(
    tmp_path, monkeypatch, read_failure
):
    root = tmp_path / "demo"
    root.mkdir()
    (root / "cgroup.events").write_text("populated 1\n")
    closed = []
    real_close = job_cgroup.os.close

    def close(fd):
        closed.append(fd)
        real_close(fd)

    class FailedPoll:
        def register(self, fd, mask):
            pass

        def poll(self):
            if read_failure:
                monkeypatch.setattr(job_cgroup.os, "read", fail_read)
                return []
            raise OSError("synthetic poll failure")

    def fail_read(*args):
        raise OSError("synthetic event read failure")

    monkeypatch.setattr(job_cgroup.os, "close", close)
    monkeypatch.setattr(job_cgroup.select, "poll", FailedPoll)
    if read_failure:
        assert job_cgroup.wait_empty("/demo", cgroup_fs=tmp_path) is False
    else:
        with pytest.raises(OSError, match="synthetic poll failure"):
            job_cgroup.wait_empty("/demo", cgroup_fs=tmp_path)
    assert len(closed) == 1
