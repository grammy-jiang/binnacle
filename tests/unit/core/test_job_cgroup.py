from __future__ import annotations

from binnacle import job_cgroup


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
