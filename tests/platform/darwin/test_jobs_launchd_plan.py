"""com.binnacle.jobs launchd plan (R4 lane J3, design section 2).

Pure plan rendering and A3 acceptance of the user-domain test variant. Nothing
here installs a LaunchDaemon, needs privileges or runs launchctl: every
launchctl call is replaced by a recording fake.
"""

from __future__ import annotations

import dataclasses
import os
import plistlib
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

from binnacle.deployment.darwin.plist import (
    JOBS_DAEMON_PLIST_PATH,
    JobsDaemonSpec,
    mcp_daemon_identity,
    render_jobs_daemon_plist,
    render_jobs_test_plist,
    user_default_process_limit,
    validate_jobs_daemon_plist_bytes,
    validate_jobs_test_plist_bytes,
)
from binnacle.deployment.darwin.provisioner import (
    JobsDaemonRefused,
    lookup_account,
    plan_jobs_daemon,
    sha256_hex,
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


JOBS_PROGRAM = Path("/opt/binnacle/venv/bin/binnacle-jobs")
JOBS_TEST_LABEL = "com.binnacle.r3test.j3jobs.manager"


def _jobs_spec(**changes: object) -> JobsDaemonSpec:
    spec = JobsDaemonSpec(
        user_name="binnacle",
        group_name="staff",
        program=JOBS_PROGRAM,
        home=Path("/Users/binnacle"),
        config_file=Path("/Users/binnacle/.config/binnacle/config.toml"),
        stdout_path=Path("/Users/binnacle/Library/Logs/binnacle/jobs.out.log"),
        stderr_path=Path("/Users/binnacle/Library/Logs/binnacle/jobs.err.log"),
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
        "ProgramArguments": [str(JOBS_PROGRAM)],
        "EnvironmentVariables": {
            "HOME": "/Users/binnacle",
            "BINNACLE_CONFIG_FILE": "/Users/binnacle/.config/binnacle/config.toml",
        },
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 10,
        "ProcessType": "Standard",
        "AbandonProcessGroup": False,
        "ExitTimeOut": 30,
        "SoftResourceLimits": limits,
        "HardResourceLimits": limits,
        "StandardOutPath": "/Users/binnacle/Library/Logs/binnacle/jobs.out.log",
        "StandardErrorPath": "/Users/binnacle/Library/Logs/binnacle/jobs.err.log",
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
        {"program": Path("binnacle-jobs")},
        {"program": Path("/opt/binnacle/venv/bin/binnacle")},
        {"program": Path("/opt/binnacle/venv/binnacle-jobs")},
        {"program": Path("/opt/binnacle/../venv/bin/binnacle-jobs")},
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
        ("ThrottleInterval", 1),
        ("SoftResourceLimits", {"NumberOfFiles": 8192}),
        ("HardResourceLimits", {"NumberOfFiles": 4096, "NumberOfProcesses": 2666}),
        ("ProgramArguments", [str(JOBS_PROGRAM), "--dev"]),
        ("ProgramArguments", ["/repo/.venv/bin/binnacle"]),
        ("UserName", "root"),
        ("Label", "com.binnacle.mcp"),
        ("EnvironmentVariables", {"HOME": "/Users/binnacle"}),
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


def test_plan_jobs_daemon_is_pure_and_runs_as_mcp_user(tmp_path: Path) -> None:
    looked: list[tuple[str, str]] = []

    def lookup(user: str, group: str) -> tuple[int, int]:
        looked.append((user, group))
        return 501, 20

    logs = tmp_path / "logs"
    plan = plan_jobs_daemon(
        _mcp_plist(),
        program=JOBS_PROGRAM,
        log_dir=logs,
        number_of_processes=2666,
        lookup=lookup,
    )
    assert looked == [("binnacle", "staff")]
    assert (plan.uid, plan.gid) == (501, 20)
    assert plan.target_path == JOBS_DAEMON_PLIST_PATH
    assert plan.capability.state == "LIMITED"
    assert plan.capability.reason_code == "jobs_daemon_plan_only"
    assert plan.plist_sha256 == sha256_hex(plan.plist_bytes)
    assert plan.spec.stdout_path == logs / "com.binnacle.jobs.out.log"
    assert plan.spec.stderr_path == logs / "com.binnacle.jobs.err.log"
    assert plan.spec.number_of_processes == 2666
    assert validate_jobs_daemon_plist_bytes(plan.plist_bytes) == plan.spec
    # Planning is data only: no directory, log or plist was created.
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(sys.platform != "darwin", reason="kern.maxprocperuid is Darwin")
def test_default_process_limit_is_the_darwin_per_user_ceiling(tmp_path: Path) -> None:
    sysctl = subprocess.run(
        ["/usr/sbin/sysctl", "-n", "kern.maxprocperuid"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert user_default_process_limit() == int(sysctl.stdout)
    plan = plan_jobs_daemon(
        _mcp_plist(),
        program=JOBS_PROGRAM,
        log_dir=tmp_path,
        lookup=lambda user, group: (501, 20),
    )
    limits = plistlib.loads(plan.plist_bytes)["HardResourceLimits"]
    assert limits["NumberOfProcesses"] == int(sysctl.stdout)


@pytest.mark.parametrize("ids", [(0, 20), (501, 0)])
def test_plan_jobs_daemon_refuses_root_identity(
    ids: tuple[int, int], tmp_path: Path
) -> None:
    with pytest.raises(JobsDaemonRefused) as info:
        plan_jobs_daemon(
            _mcp_plist(),
            program=JOBS_PROGRAM,
            log_dir=tmp_path,
            lookup=lambda user, group: ids,
        )
    assert info.value.code == "jobs_daemon_root_refused"


def test_plan_jobs_daemon_refusals_are_controlled(tmp_path: Path) -> None:
    for kwargs, code in (
        ({"program": Path("/repo/.venv/bin/binnacle")}, "jobs_daemon_program_invalid"),
        ({"log_dir": Path("logs")}, "path_not_absolute"),
        ({"number_of_processes": 0}, "jobs_daemon_process_limit_invalid"),
    ):
        args: dict[str, object] = {
            "program": JOBS_PROGRAM,
            "log_dir": tmp_path,
            "lookup": lambda user, group: (501, 20),
            **kwargs,
        }
        with pytest.raises(JobsDaemonRefused) as info:
            plan_jobs_daemon(_mcp_plist(), **args)  # type: ignore[arg-type]
        assert info.value.code == code
    with pytest.raises(JobsDaemonRefused) as missing:
        lookup_account("binnacle-j3-no-such-user", "staff")
    assert missing.value.code == "jobs_daemon_account_missing"


def test_lookup_account_reads_local_databases() -> None:
    import grp
    import pwd

    me = pwd.getpwuid(os.getuid())
    group = grp.getgrgid(me.pw_gid).gr_name
    assert lookup_account(me.pw_name, group) == (me.pw_uid, me.pw_gid)


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
