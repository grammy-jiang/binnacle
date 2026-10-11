"""com.binnacle.jobs launchd plan (R4 lanes J3/J3r, design section 2).

Pure plan rendering and A3 acceptance of the user-domain test variant. Nothing
here installs a LaunchDaemon, needs privileges or runs launchctl.
"""

from __future__ import annotations

import ast
import dataclasses
import os
import plistlib
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

import binnacle
from binnacle.deployment.darwin import plist as plan_constants
from binnacle.deployment.darwin.plist import (
    JOBS_DAEMON_PLIST_PATH,
    JobsDaemonSpec,
    render_jobs_daemon_plist,
    render_jobs_test_plist,
    validate_jobs_daemon_plist_bytes,
    validate_jobs_test_plist_bytes,
)
from binnacle.deployment.darwin.setup import (
    mcp_daemon_identity,
    per_user_process_limit,
    plan_jobs_daemon,
)
from binnacle.platform.contracts.capability_contracts import NativeCapabilityError
from binnacle.platform.contracts.native_service_contracts import ServicePlan
from binnacle.platform.darwin import service_launchd as launchd
from binnacle.platform.darwin.generation_runtime import open_service_lease
from tests.platform.darwin.test_ipc_generation import child_command, runtime

service_root = runtime


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "root"
    r.mkdir(mode=0o700)
    return r


JOBS_PYTHON = Path("/opt/binnacle/venv/bin/python")
JOBS_TEST_LABEL = "com.binnacle.r3test.j3jobs.manager"
MCP_PATH = "/opt/homebrew/bin:/Users/binnacle/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
LOGS = Path("/Users/binnacle/Library/Logs/binnacle")
UID = os.getuid()


def _jobs_spec(**changes: object) -> JobsDaemonSpec:
    spec = JobsDaemonSpec(
        user_name="binnacle",
        group_name="staff",
        python=JOBS_PYTHON,
        home=Path("/Users/binnacle"),
        config_file=Path("/Users/binnacle/.config/binnacle/config.toml"),
        path=MCP_PATH,
        stdout_path=LOGS / "jobs.out.log",
        stderr_path=LOGS / "jobs.err.log",
        number_of_processes=2666,
    )
    return dataclasses.replace(spec, **changes)  # type: ignore[arg-type]


def _mcp_plist(**changes: object) -> bytes:
    body: dict[str, object] = {
        "Label": "com.binnacle.mcp",
        "UserName": "binnacle",
        "GroupName": "staff",
        "ProgramArguments": ["/opt/binnacle/venv/bin/binnacle"],
        "EnvironmentVariables": {
            "HOME": "/Users/binnacle",
            "BINNACLE_CONFIG_FILE": "/Users/binnacle/.config/binnacle/config.toml",
            "PATH": MCP_PATH,
        },
    }
    body.update(changes)
    return plistlib.dumps({k: v for k, v in body.items() if v is not None})


def test_jobs_daemon_plist_matches_design_section_2() -> None:
    data = render_jobs_daemon_plist(_jobs_spec())
    assert data == render_jobs_daemon_plist(_jobs_spec())
    value = plistlib.loads(data)
    limits = {"NumberOfFiles": 8192, "NumberOfProcesses": 2666}
    assert value == {
        "Label": "com.binnacle.jobs",
        "UserName": "binnacle",
        "GroupName": "staff",
        "ProgramArguments": [
            str(JOBS_PYTHON),
            "-m",
            "binnacle.platform.darwin.job_manager_service",
        ],
        "EnvironmentVariables": {
            "HOME": "/Users/binnacle",
            "BINNACLE_CONFIG_FILE": "/Users/binnacle/.config/binnacle/config.toml",
            # R-J3-F1: the deployed MCP PATH, so jobs find uv, rg and brew tools.
            "PATH": MCP_PATH,
        },
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 10,
        "ProcessType": "Standard",
        "AbandonProcessGroup": False,
        "ExitTimeOut": 30,
        "Umask": 0o077,
        "SoftResourceLimits": limits,
        "HardResourceLimits": limits,
        "StandardOutPath": str(LOGS / "jobs.out.log"),
        "StandardErrorPath": str(LOGS / "jobs.err.log"),
    }
    assert validate_jobs_daemon_plist_bytes(data) == _jobs_spec()
    assert JOBS_DAEMON_PLIST_PATH == Path(
        "/Library/LaunchDaemons/com.binnacle.jobs.plist"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"user_name": "root"},
        {"user_name": "wheel"},
        {"group_name": "wheel"},
        {"group_name": "admin"},
        {"user_name": ""},
        {"user_name": "-oops"},
        {"user_name": "a b"},
        {"python": Path("python")},
        {"python": Path("/opt/binnacle/venv/bin/binnacle-jobs")},
        {"python": Path("/opt/binnacle/venv/python3")},
        {"python": Path("/opt/binnacle/../venv/bin/python3.12")},
        {"path": ""},
        {"path": "/usr/bin:"},
        {"path": "/usr/bin:bin"},
        {"path": "/usr/bin:/opt/../sbin"},
        {"path": "/usr/bin\x00:/bin"},
        {"home": Path("relative")},
        {"config_file": Path("/a/../b.toml")},
        {"stdout_path": Path("logs/out.log")},
        {"number_of_processes": 0},
        {"number_of_processes": True},
        {"number_of_processes": 1 << 21},
    ],
)
def test_jobs_daemon_spec_refusals(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        render_jobs_daemon_plist(_jobs_spec(**changes))


@pytest.mark.parametrize(
    "key,value",
    [
        ("KeepAlive", True),
        ("KeepAlive", {"SuccessfulExit": True}),
        ("KeepAlive", {"SuccessfulExit": False, "Crashed": True}),
        ("RunAtLoad", False),
        ("ProcessType", "Background"),
        ("AbandonProcessGroup", True),
        ("ExitTimeOut", 30.0),
        ("ExitTimeOut", 5),
        ("Umask", 18),
        ("ThrottleInterval", 1),
        ("SoftResourceLimits", {"NumberOfFiles": 8192}),
        ("HardResourceLimits", {"NumberOfFiles": 4096, "NumberOfProcesses": 2666}),
        ("ProgramArguments", [str(JOBS_PYTHON)]),
        ("ProgramArguments", [str(JOBS_PYTHON), "-m", "binnacle.cli"]),
        ("ProgramArguments", ["/repo/.venv/bin/binnacle-jobs"]),
        ("UserName", "root"),
        ("Label", "com.binnacle.mcp"),
        ("EnvironmentVariables", {"HOME": "/Users/binnacle"}),
        ("EnvironmentVariables", {"HOME": "/h", "BINNACLE_CONFIG_FILE": "/c"}),
        (
            "EnvironmentVariables",
            {"HOME": "/h", "BINNACLE_CONFIG_FILE": "/c", "PATH": "/b", "TOKEN": "x"},
        ),
        ("StartInterval", 60),
        ("Sockets", {}),
        ("LimitLoadToSessionType", "Background"),
        ("Program", "/bin/sh"),
    ],
)
def test_jobs_daemon_validator_refuses_edited_bytes(key: str, value: object) -> None:
    body = plistlib.loads(render_jobs_daemon_plist(_jobs_spec()))
    body[key] = value
    with pytest.raises(ValueError, match="plist_scope_refused"):
        validate_jobs_daemon_plist_bytes(plistlib.dumps(body))
    del body[key]
    if key in plistlib.loads(render_jobs_daemon_plist(_jobs_spec())):
        with pytest.raises(ValueError, match="plist_scope_refused"):
            validate_jobs_daemon_plist_bytes(plistlib.dumps(body))
    with pytest.raises(ValueError, match="plist_invalid"):
        validate_jobs_daemon_plist_bytes(b"not a plist")


def test_mcp_identity_is_the_only_run_as_source() -> None:
    identity = mcp_daemon_identity(_mcp_plist())
    assert (identity.user_name, identity.group_name) == ("binnacle", "staff")
    assert identity.config_file == Path("/Users/binnacle/.config/binnacle/config.toml")
    assert identity.path == MCP_PATH
    env = plistlib.loads(_mcp_plist())["EnvironmentVariables"]
    for path in (None, "", "/usr/bin::/bin", "~/.local/bin:/usr/bin"):
        bad = {k: v for k, v in dict(env, PATH=path).items() if v is not None}
        with pytest.raises(ValueError, match="mcp_identity_path_invalid"):
            mcp_daemon_identity(_mcp_plist(EnvironmentVariables=bad))
    for changes in (
        {"Label": "com.binnacle.jobs"},
        {"UserName": None},
        {"GroupName": None},
        {"UserName": "root"},
        {"EnvironmentVariables": {"HOME": "/Users/binnacle"}},
        {"EnvironmentVariables": {"HOME": "rel", "BINNACLE_CONFIG_FILE": "/c"}},
    ):
        with pytest.raises(ValueError):
            mcp_daemon_identity(_mcp_plist(**changes))


@pytest.mark.skipif(sys.platform != "darwin", reason="kern.maxprocperuid is Darwin")
def test_default_process_limit_is_kern_maxprocperuid_not_ulimit(tmp_path: Path) -> None:
    """R-J3-F2: a provisioner under a lowered ``ulimit -u`` still pins the sysctl."""
    sysctl = subprocess.run(
        ["/usr/sbin/sysctl", "-n", "kern.maxprocperuid"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert per_user_process_limit() == int(sysctl)
    lowered = (
        "import os, resource\n"
        "from binnacle.deployment.darwin.setup import per_user_process_limit\n"
        "hard = resource.getrlimit(resource.RLIMIT_NPROC)[1]\n"
        "resource.setrlimit(resource.RLIMIT_NPROC, (300, hard))\n"
        "print(per_user_process_limit(), os.sysconf('SC_CHILD_MAX'))\n"
    )
    child = subprocess.run(
        [sys.executable, "-c", lowered], capture_output=True, text=True, check=True
    )
    assert child.stdout.split() == [sysctl, "300"]
    plan = plan_jobs_daemon(
        _mcp_plist(),
        python=JOBS_PYTHON,
        log_dir=tmp_path,
        lookup=lambda user, group: (UID, 20),
    )
    limits = plistlib.loads(plan.plist_bytes)["HardResourceLimits"]
    assert limits["NumberOfProcesses"] == int(sysctl)


def test_exit_timeout_covers_the_close_persist_budget() -> None:
    """R-J3-F3 (CR0 point 3): one TERM sweep, both grace windows and the
    persist margin fit inside ExitTimeOut, mirroring the Linux constants."""
    jobs_py = Path(binnacle.__file__).parent / "features" / "commands" / "jobs.py"
    linux = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in ast.parse(jobs_py.read_text()).body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id.startswith("STOP_SIG")
    }
    c = plan_constants
    assert linux == {
        "STOP_SIGTERM_GRACE_S": c.JOBS_STOP_SIGTERM_GRACE_S,
        "STOP_SIGKILL_GRACE_S": c.JOBS_STOP_SIGKILL_GRACE_S,
    }
    budget = sum(linux.values()) + c.JOBS_PERSIST_MARGIN_S
    assert c.JOBS_PERSIST_MARGIN_S > 0
    assert budget <= c.JOBS_EXIT_TIMEOUT_S
    # SD-43 JCRP-F2 / SD-45: worst close() budget (handler release, TERM
    # grace, KILL grace, reaper join); ExitTimeOut >= budget + 10 s and >= 30.
    assert c.JOBS_CLOSE_BUDGET_S == 1.0 + sum(linux.values()) + 1.0
    assert c.JOBS_EXIT_TIMEOUT_S >= c.JOBS_CLOSE_BUDGET_S + 10.0
    assert c.JOBS_EXIT_TIMEOUT_S >= 30
    assert c.JOBS_EXIT_TIMEOUT_S == 30  # SD-45: not lowered
    value = plistlib.loads(render_jobs_daemon_plist(_jobs_spec()))
    assert value["ExitTimeOut"] == c.JOBS_EXIT_TIMEOUT_S


def _jobs_test_plist(
    root: Path,
    label: str = JOBS_TEST_LABEL,
    *,
    argv: tuple[str, ...] = ("/usr/bin/true",),
    number_of_processes: int = 2666,
) -> bytes:
    return render_jobs_test_plist(
        label,
        argv=argv,
        environment={"HOME": str(root)},
        workdir=root,
        runtime_dir=root,
        number_of_processes=number_of_processes,
    )


def test_jobs_test_variant_shares_lifecycle_but_stays_user_domain(root: Path) -> None:
    test_value = plistlib.loads(_jobs_test_plist(root))
    prod_value = plistlib.loads(render_jobs_daemon_plist(_jobs_spec()))
    shared = (
        "RunAtLoad",
        "ThrottleInterval",
        "ProcessType",
        "AbandonProcessGroup",
        "ExitTimeOut",
        "SoftResourceLimits",
        "HardResourceLimits",
    )
    assert {k: test_value[k] for k in shared} == {k: prod_value[k] for k in shared}
    assert test_value["KeepAlive"] is False
    assert test_value["LimitLoadToSessionType"] == "Background"
    assert test_value["EnvironmentVariables"] == {
        "BINNACLE_RUNTIME_DIR": str(root),
        "BINNACLE_SERVICE_ROLE": "manager",
        "HOME": str(root),
    }
    for key in ("UserName", "GroupName", "StandardOutPath", "StandardErrorPath"):
        assert key not in test_value
    validate_jobs_test_plist_bytes(
        _jobs_test_plist(root), label=JOBS_TEST_LABEL, runtime_dir=root
    )
    # Neither domain accepts the other's plan.
    with pytest.raises(ValueError):
        validate_jobs_daemon_plist_bytes(_jobs_test_plist(root))
    with pytest.raises(ValueError):
        validate_jobs_test_plist_bytes(
            render_jobs_daemon_plist(_jobs_spec()),
            label=JOBS_TEST_LABEL,
            runtime_dir=root,
        )


@pytest.mark.parametrize(
    "label",
    [
        "com.binnacle.jobs",
        "com.binnacle.mcp",
        "com.binnacle.r3test.j3jobs.probe",
        "com.binnacle.r3test.j3jobs.frontend",
        "com.binnacle.r3test.",
    ],
)
def test_jobs_test_variant_requires_owned_manager_label(root: Path, label: str) -> None:
    with pytest.raises(ValueError):
        _jobs_test_plist(root, label)


def test_jobs_test_variant_refusals(root: Path) -> None:
    for argv, limit in ((("rel",), 1), ((), 1), (("/usr/bin/true",), 0)):
        with pytest.raises(ValueError):
            _jobs_test_plist(root, argv=argv, number_of_processes=limit)
    with pytest.raises(ValueError):
        render_jobs_test_plist(
            JOBS_TEST_LABEL,
            argv=["/usr/bin/true"],
            environment={},
            workdir=Path("rel"),
            runtime_dir=root,
            number_of_processes=1,
        )
    good = plistlib.loads(_jobs_test_plist(root))
    for key, value in (
        ("KeepAlive", {"SuccessfulExit": False}),
        ("UserName", "binnacle"),
        ("StandardOutPath", "/tmp/x.log"),
        ("ProcessType", "Background"),
        ("AbandonProcessGroup", True),
        ("LimitLoadToSessionType", "Aqua"),
        ("Label", "com.binnacle.r3test.other.manager"),
    ):
        with pytest.raises(ValueError, match="plist_scope_refused"):
            validate_jobs_test_plist_bytes(
                plistlib.dumps(dict(good, **{key: value})),
                label=JOBS_TEST_LABEL,
                runtime_dir=root,
            )
    with pytest.raises(ValueError, match="plist_scope_refused"):
        validate_jobs_test_plist_bytes(
            _jobs_test_plist(root), label=JOBS_TEST_LABEL, runtime_dir=root / "x"
        )


def make_jobs_test_plan(root):
    """The com.binnacle.jobs user-domain test variant under an owned lease."""
    label = "com.binnacle.r3test." + secrets.token_hex(12) + ".manager"
    lease = open_service_lease(root=root, label=label, generation=secrets.token_hex(16))
    data = render_jobs_test_plist(
        label,
        argv=child_command(root, lease),
        environment={},
        workdir=Path.cwd(),
        runtime_dir=root,
        number_of_processes=2666,
    )
    path = root / "service.plist"
    path.write_bytes(data)
    path.chmod(0o600)
    return ServicePlan(lease, data, path, None)


def test_jobs_test_variant_is_a3_accepted_and_bootout_stays_gated(
    service_root, monkeypatch
):
    """J3 plist half: the variant loads in A3's scope; manager mutations stay
    refused until the J0/J2 quiet gate (running-job count) exists."""
    plan = make_jobs_test_plan(service_root)
    value = plistlib.loads(plan.plist_bytes)
    assert value["ProcessType"] == "Standard"
    assert value["AbandonProcessGroup"] is False
    assert value["KeepAlive"] is False
    owner = launchd.LaunchdUserServices(plan.lease)
    owner._validate_plist(value)
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        if args[0] == "print" and owner._plan is None:
            return subprocess.CompletedProcess(args, 113, "", "Could not find service")
        return subprocess.CompletedProcess(
            args, 0, f"\tpath = {plan.plist_path}\n\tstate = running\n\tpid = 100\n", ""
        )

    monkeypatch.setattr(launchd, "_run", run)
    owner.bootstrap(plan)
    assert ("bootstrap", f"user/{plan.lease.uid}", str(plan.plist_path)) in calls
    with pytest.raises(NativeCapabilityError, match="quiet_gate_unavailable"):
        owner.bootout(plan.lease, timeout_s=1)
    action = owner.restart(plan.lease.label)
    assert action.returncode == 1
    assert action.launch_error == "launchd_restart_quiet_gate_unavailable"
    assert not any(args[0] in ("bootout", "kickstart", "kill") for args in calls)


@pytest.mark.parametrize(
    "key,value",
    [
        ("AbandonProcessGroup", 1),
        ("SoftResourceLimits", {"NumberOfFiles": 0}),
        ("SoftResourceLimits", {"NumberOfFiles": True}),
        ("HardResourceLimits", {"Core": 1}),
        ("HardResourceLimits", [8192]),
        ("ThrottleInterval", 0),
        ("ThrottleInterval", "10"),
        ("UserName", "root"),
        ("KeepAlive", {"SuccessfulExit": False}),
    ],
)
def test_a3_refuses_jobs_test_variant_values(service_root, key, value):
    plan = make_jobs_test_plan(service_root)
    data = plistlib.loads(plan.plist_bytes)
    data[key] = value
    with pytest.raises(NativeCapabilityError, match="scope_refused"):
        launchd.LaunchdUserServices(plan.lease)._validate_plist(data)


def test_production_jobs_daemon_plan_is_refused_by_user_domain(service_root):
    plan = make_jobs_test_plan(service_root)
    daemon = plistlib.loads(render_jobs_daemon_plist(_jobs_spec()))
    with pytest.raises(NativeCapabilityError, match="scope_refused"):
        launchd.LaunchdUserServices(plan.lease)._validate_plist(daemon)
    daemon["Label"] = plan.lease.label
    with pytest.raises(NativeCapabilityError, match="scope_refused"):
        launchd.LaunchdUserServices(plan.lease)._validate_plist(daemon)
