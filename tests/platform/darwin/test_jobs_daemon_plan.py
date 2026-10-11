"""com.binnacle.jobs install plan (R4 lanes J3/J3r): identity, logs, install.

``plan_jobs_daemon`` is pure data plus read-only ``lstat`` checks. Nothing here
writes /Library or /etc, needs privileges or runs launchctl.
"""

from __future__ import annotations

import ctypes
import grp
import os
import plistlib
import pwd
import stat
from pathlib import Path
from typing import Any

import pytest

from binnacle.deployment.darwin.plist import (
    JOBS_DAEMON_PLIST_PATH,
    search_path,
    validate_jobs_daemon_plist_bytes,
)
from binnacle.deployment.darwin.provisioner import sha256_hex
from binnacle.deployment.darwin.setup import (
    MCP_NEWSYSLOG_PATH,
    JobsDaemonPlan,
    JobsDaemonRefused,
    lookup_account,
    newsyslog_covers_jobs_logs,
    per_user_process_limit,
    plan_jobs_daemon,
    verify_installed_jobs_daemon,
)

PYTHON = Path("/opt/binnacle/venv/bin/python")
MCP_PATH = "/opt/homebrew/bin:/Users/binnacle/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
UID = os.getuid()


def _mcp_plist(**env: str) -> bytes:
    return plistlib.dumps(
        {
            "Label": "com.binnacle.mcp",
            "UserName": "binnacle",
            "GroupName": "staff",
            "ProgramArguments": ["/opt/binnacle/venv/bin/binnacle"],
            "EnvironmentVariables": {
                "HOME": "/Users/binnacle",
                "BINNACLE_CONFIG_FILE": "/Users/binnacle/.config/binnacle/c.toml",
                "PATH": MCP_PATH,
                **env,
            },
        }
    )


def _plan(
    log_dir: Path | None, owner: tuple[int, int] = (UID, 20), **kw: Any
) -> JobsDaemonPlan:
    looked: list[tuple[str, str]] = []

    def lookup(user: str, group: str) -> tuple[int, int]:
        looked.append((user, group))
        return owner

    kw.setdefault("number_of_processes", 2666)
    plan = plan_jobs_daemon(
        _mcp_plist(), python=PYTHON, log_dir=log_dir, lookup=lookup, **kw
    )
    assert looked == [("binnacle", "staff")]
    return plan


@pytest.fixture
def logs(tmp_path: Path) -> Path:
    path = tmp_path / "logs"
    path.mkdir(mode=0o700)
    return path


def test_plan_is_pure_and_runs_as_mcp_user_with_its_path(logs: Path) -> None:
    plan = _plan(logs)
    assert (plan.uid, plan.gid) == (UID, 20)
    assert plan.target_path == JOBS_DAEMON_PLIST_PATH
    assert plan.capability.state == "LIMITED"
    assert plan.capability.reason_code == "jobs_daemon_plan_only"
    assert plan.plist_sha256 == sha256_hex(plan.plist_bytes)
    assert plan.spec.stdout_path == logs / "com.binnacle.jobs.out.log"
    assert plan.spec.stderr_path == logs / "com.binnacle.jobs.err.log"
    assert plan.spec.number_of_processes == 2666
    assert validate_jobs_daemon_plist_bytes(plan.plist_bytes) == plan.spec
    env = plistlib.loads(plan.plist_bytes)["EnvironmentVariables"]
    # R-J3-F1: jobs inherit exactly the deployed MCP PATH (no secrets, no extras).
    assert env == {
        "HOME": "/Users/binnacle",
        "BINNACLE_CONFIG_FILE": "/Users/binnacle/.config/binnacle/c.toml",
        "PATH": MCP_PATH,
    }
    # R-J3-F8: the Darwin manager entry, never the A1 Linux console script.
    assert plistlib.loads(plan.plist_bytes)["ProgramArguments"] == [
        str(PYTHON),
        "-m",
        "binnacle.platform.darwin.job_manager_service",
    ]
    # Planning is data only: no directory, log or plist was created.
    assert list(logs.iterdir()) == []


def test_plan_refuses_an_mcp_daemon_without_an_absolute_path(logs: Path) -> None:
    for path in ("", "/usr/bin::/bin", "relative/bin:/usr/bin"):
        with pytest.raises(JobsDaemonRefused) as info:
            plan_jobs_daemon(
                _mcp_plist(PATH=path),
                python=PYTHON,
                log_dir=logs,
                number_of_processes=2666,
                lookup=lambda user, group: (UID, 20),
            )
        assert info.value.code == "mcp_identity_path_invalid"


@pytest.mark.parametrize("ids", [(0, 20), (501, 0)])
def test_plan_refuses_root_identity(ids: tuple[int, int], logs: Path) -> None:
    with pytest.raises(JobsDaemonRefused) as info:
        _plan(logs, ids)
    assert info.value.code == "jobs_daemon_root_refused"


def test_plan_refusals_are_controlled(logs: Path) -> None:
    for kwargs, code in (
        (
            {"python": Path("/repo/.venv/bin/binnacle-jobs")},
            "jobs_daemon_program_invalid",
        ),
        ({"log_dir": Path("logs")}, "path_not_absolute"),
        ({"log_dir": logs / ".." / "logs"}, "path_not_absolute"),
        ({"number_of_processes": 0}, "jobs_daemon_process_limit_invalid"),
    ):
        # The limit is injected so every host checks the input under test;
        # the unavailable-limit refusal has its own test.
        args: dict[str, object] = {
            "python": PYTHON,
            "log_dir": logs,
            "number_of_processes": 2666,
            "lookup": lambda user, group: (UID, 20),
            **kwargs,
        }
        with pytest.raises(JobsDaemonRefused) as info:
            plan_jobs_daemon(_mcp_plist(), **args)  # type: ignore[arg-type]
        assert info.value.code == code
    with pytest.raises(JobsDaemonRefused) as missing:
        lookup_account("binnacle-j3-no-such-user", "staff")
    assert missing.value.code == "jobs_daemon_account_missing"


def test_lookup_account_reads_local_databases() -> None:
    me = pwd.getpwuid(os.getuid())
    group = grp.getgrgid(me.pw_gid).gr_name
    assert lookup_account(me.pw_name, group) == (me.pw_uid, me.pw_gid)


def test_process_limit_failure_refuses_never_guesses(
    logs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R-J3-F2: no sysctlbyname (or a failed read) refuses the plan."""

    def no_libc(*args: object, **kwargs: object) -> object:
        raise OSError("no libc")

    monkeypatch.setattr(ctypes, "CDLL", no_libc)
    with pytest.raises(ValueError, match="jobs_daemon_process_limit_unavailable"):
        per_user_process_limit()
    with pytest.raises(JobsDaemonRefused) as info:
        _plan(logs, number_of_processes=None)
    assert info.value.code == "jobs_daemon_process_limit_unavailable"
    # Documented order: the limit is read before the plist (python) is checked.
    with pytest.raises(JobsDaemonRefused) as order:
        plan_jobs_daemon(
            _mcp_plist(),
            python=Path("/repo/.venv/bin/binnacle-jobs"),
            log_dir=logs,
            lookup=lambda user, group: (UID, 20),
        )
    assert order.value.code == "jobs_daemon_process_limit_unavailable"


def test_log_dir_must_be_the_run_as_users_private_directory(
    tmp_path: Path, logs: Path
) -> None:
    """R-J3-F5: launchd opens the logs for the daemon; no shared or planted path."""
    link = tmp_path / "link"
    link.symlink_to(logs)
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o775)
    planted = tmp_path / "planted"
    planted.mkdir(mode=0o700)
    (planted / "com.binnacle.jobs.out.log").symlink_to(tmp_path / "elsewhere")
    linked = tmp_path / "linked"
    linked.mkdir(mode=0o700)
    (linked / "x").write_text("")
    os.link(linked / "x", linked / "com.binnacle.jobs.err.log")
    spaced = tmp_path / "has space"
    spaced.mkdir(mode=0o700)
    for log_dir, owner, code in (
        (link, UID, "jobs_daemon_log_dir_invalid"),
        (shared, UID, "jobs_daemon_log_dir_invalid"),
        (tmp_path / "missing", UID, "jobs_daemon_log_dir_invalid"),
        (logs, UID + 1, "jobs_daemon_log_dir_invalid"),
        (spaced, UID, "jobs_daemon_log_dir_invalid"),
        (planted, UID, "jobs_daemon_log_file_invalid"),
        (linked, UID, "jobs_daemon_log_file_invalid"),
    ):
        with pytest.raises(JobsDaemonRefused) as info:
            _plan(log_dir, (owner, 20))
        assert info.value.code == code
    (logs / "com.binnacle.jobs.out.log").write_text("kept\n")
    (logs / "com.binnacle.jobs.out.log").chmod(0o600)
    assert _plan(logs).spec.stdout_path == logs / "com.binnacle.jobs.out.log"


def test_default_log_dir_is_the_mcp_users_library_logs(logs: Path) -> None:
    seen: list[Path] = []

    def lstat(path: Path) -> os.stat_result:
        seen.append(path)
        if path.suffix == ".log":
            raise FileNotFoundError(path)
        return os.lstat(logs)

    plan = _plan(None, lstat=lstat)
    assert seen[0] == Path("/Users/binnacle/Library/Logs/binnacle")
    assert plan.spec.stderr_path == seen[0] / "com.binnacle.jobs.err.log"


@pytest.mark.parametrize(
    "key", ["BINNACLE_RUNTIME_DIR", "TMPDIR", "BINNACLE_JOBS_SOCKET", "TOKEN"]
)
def test_plan_refuses_unexpected_mcp_environment_keys(logs: Path, key: str) -> None:
    """R-J3d-N2: an extra MCP env key could move the runtime root or socket."""
    with pytest.raises(JobsDaemonRefused) as info:
        plan_jobs_daemon(
            _mcp_plist(**{key: "/tmp/x"}),
            python=PYTHON,
            log_dir=logs,
            number_of_processes=2666,
            lookup=lambda user, group: (UID, 20),
        )
    assert info.value.code == "mcp_identity_env_unexpected"


@pytest.mark.parametrize(
    "path,valid",
    [
        ("/usr/bin:/bin", True),
        ("/", True),
        ("/usr/./bin", False),
        ("/usr//bin", False),
        ("/usr/bin/", False),
        ("//usr/bin", False),
        ("/usr/../bin", False),
        ("usr/bin", False),
        ("~/.local/bin", False),
        ("/usr/bin::/bin", False),
        ("/usr/bin\x00", False),
    ],
)
def test_search_path_validates_raw_entries(path: str, valid: bool) -> None:
    """R-J3d-N3: the raw string, not a pathlib-collapsed copy, is checked."""
    if valid:
        assert search_path(path) == path
    else:
        with pytest.raises(ValueError, match="jobs_daemon_path_invalid"):
            search_path(path)


def test_jobs_newsyslog_lines_extend_the_mcp_conf(logs: Path) -> None:
    """R-J3d-N1 (SD-31): no jobs conf file; lines append to com.binnacle.mcp.conf."""
    plan = _plan(logs)
    assert MCP_NEWSYSLOG_PATH == Path("/etc/newsyslog.d/com.binnacle.mcp.conf")
    assert not hasattr(plan, "newsyslog_path")
    assert plan.newsyslog_lines == "".join(
        f"{logs}/com.binnacle.jobs.{name}.log\tbinnacle:staff\t600\t7\t10240\t*\tNJ\n"
        for name in ("out", "err")
    )
    assert newsyslog_covers_jobs_logs(plan.newsyslog_lines, plan.spec)
    assert not newsyslog_covers_jobs_logs("", plan.spec)


DEPLOYED_STYLE = (
    "# binnacle MCP daemon (com.binnacle.mcp) launchd stdout/stderr logs.\n"
    "# logfilename  [owner:group]  mode count size  when flags\n"
    "{logs}/*.log   binnacle:staff 600  7     10240 *    GNJ\n"
)


@pytest.mark.parametrize(
    "conf,covered",
    [
        (DEPLOYED_STYLE, True),
        ("{logs}/*.log binnacle:staff 600 7 10240 * NJ", False),
        ("{logs}/*.log binnacle:staff 644 7 10240 * GNJ", False),
        ("{logs}/*.log root:wheel 600 7 10240 * GNJ", False),
        ("{logs}/*.log 600 7 10240 * GNJ", False),
        ("{logs}/*.log binnacle:staff 600 7 * $D0 GNJ", False),
        ("{logs}/*/*.log binnacle:staff 600 7 10240 * GNJ", False),
        ("# {logs}/*.log binnacle:staff 600 7 10240 * GNJ", False),
        ("{logs}/com.binnacle.jobs.out.log binnacle:staff 600 7 10240 * NJ", False),
    ],
)
def test_newsyslog_coverage_check(logs: Path, conf: str, covered: bool) -> None:
    """A deployed-style ``G`` glob counts; wrong owner/mode/no size bound do not."""
    plan = _plan(logs)
    assert newsyslog_covers_jobs_logs(conf.format(logs=logs), plan.spec) is covered


def _stat(mode: int, uid: int = 0, gid: int = 0, nlink: int = 1) -> os.stat_result:
    return os.stat_result((mode, 1, 1, nlink, uid, gid, 100, 0, 0, 0))


def test_verify_installed_jobs_daemon_requires_root_wheel_0644(logs: Path) -> None:
    """R-J3-F6: pure check of the installed file's lstat and bytes."""
    plan = _plan(logs)
    assert (plan.install_owner, plan.install_mode) == ((0, 0), 0o644)
    regular = stat.S_IFREG | 0o644
    verify_installed_jobs_daemon(_stat(regular), plan.plist_bytes, plan)
    for st, data in (
        (_stat(stat.S_IFLNK | 0o644), plan.plist_bytes),
        (_stat(stat.S_IFREG | 0o664), plan.plist_bytes),
        (_stat(stat.S_IFREG | 0o600), plan.plist_bytes),
        (_stat(regular, uid=UID), plan.plist_bytes),
        (_stat(regular, gid=20), plan.plist_bytes),
        (_stat(regular, nlink=2), plan.plist_bytes),
        (_stat(regular), plan.plist_bytes + b"\n"),
    ):
        with pytest.raises(JobsDaemonRefused) as info:
            verify_installed_jobs_daemon(st, data, plan)
        assert info.value.code == "jobs_daemon_install_unverified"
