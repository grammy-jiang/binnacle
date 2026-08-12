"""Static and safe functional checks for Phase 3 development-Pi assets."""

from __future__ import annotations

import grp
import json
import os
import pwd
from pathlib import Path

import pytest
from scripts import setup_dev_pi, verify_dev_pi


def test_systemd_unit_has_exact_unprivileged_source_checkout_shape(repo_root: Path) -> None:
    unit = (repo_root / "deploy/systemd/binnacle-dev.service").read_text(encoding="utf-8")

    required_lines = {
        "User=binnacle",
        "Group=binnacle",
        "SupplementaryGroups=binnacle-dev binnacle-executor-client",
        "WorkingDirectory=/srv/binnacle-dev/repo",
        (
            "ExecStart=/srv/binnacle-dev/repo/.venv/bin/binnacle serve "
            "--config /etc/binnacle/dev.toml"
        ),
        "NoNewPrivileges=yes",
        "ProtectSystem=strict",
        "RuntimeDirectory=binnacle",
        "RuntimeDirectoryMode=0750",
        "RuntimeDirectoryPreserve=yes",
        "KillMode=control-group",
        "SendSIGKILL=yes",
        "Delegate=no",
        "CapabilityBoundingSet=",
        "AmbientCapabilities=",
    }
    assert required_lines <= set(unit.splitlines())
    assert "0.0.0.0" not in unit
    assert "PrivateNetwork=" not in unit
    assert "Environment=" not in unit
    assert "/bin/sh" not in unit
    assert "/bin/bash" not in unit


def test_no_tunnel_service_is_invented_before_live_product_observation(repo_root: Path) -> None:
    assert not (repo_root / "deploy/systemd/binnacle-tunnel.service").exists()


def test_setup_atomic_install_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.service"
    source.write_bytes(b"[Service]\nNoNewPrivileges=yes\n")
    destination = tmp_path / "systemd" / "installed.service"
    monkeypatch.setattr("scripts.setup_dev_pi.os.chown", lambda *_args: None)

    setup_dev_pi._atomic_install(source, destination, mode=0o644)
    first = destination.read_bytes()
    setup_dev_pi._atomic_install(source, destination, mode=0o644)

    assert destination.read_bytes() == first
    assert destination.stat().st_mode & 0o777 == 0o644


def test_setup_refuses_mutation_when_any_preflight_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = setup_dev_pi.SetupPlan(
        checks=(setup_dev_pi.Check("repository", "fail", "unsafe"),),
        actions=("must-not-run",),
    )
    monkeypatch.setattr(setup_dev_pi, "build_setup_plan", lambda _repo: failed)
    invoked = False

    def must_not_run(*_args: object, **_kwargs: object) -> None:
        nonlocal invoked
        invoked = True

    monkeypatch.setattr("scripts.setup_dev_pi.subprocess.run", must_not_run)

    with pytest.raises(setup_dev_pi.SetupError, match="no changes"):
        setup_dev_pi.apply_setup(Path("/unsafe"), enable=False)
    assert invoked is False


def test_setup_rejects_service_and_development_group_gid_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groups = {
        "binnacle": grp.struct_group(("binnacle", "x", 1200, [])),
        "binnacle-dev": grp.struct_group(("binnacle-dev", "x", 1200, [])),
    }

    def group_by_name(name: str) -> grp.struct_group:
        return groups[name]

    def missing_user(_name: str) -> pwd.struct_passwd:
        raise KeyError

    monkeypatch.setattr(grp, "getgrnam", group_by_name)
    monkeypatch.setattr(pwd, "getpwnam", missing_user)

    check = setup_dev_pi._check_identity_compatibility()

    assert check.status == "fail"
    assert "distinct group IDs" in check.summary


def test_verifier_keeps_external_live_gates_explicitly_blocked(tmp_path: Path) -> None:
    checks = verify_dev_pi.verify_deployment(
        config_path=tmp_path / "missing-dev.toml",
        controller_profile_path=tmp_path / "missing-controller.toml",
        expected_commit="0" * 40,
        repo=tmp_path / "missing-repo",
    )
    by_name = {check.name: check for check in checks}

    assert by_name["application-config"].status == "fail"
    assert by_name["selected-auth-profile"].status == "blocked"
    assert by_name["authenticated-catalogue"].status == "blocked"
    assert by_name["tunnel-identity"].status == "blocked"
    assert by_name["probe-filesystem-primitives"].status == "blocked"
    assert by_name["write-probe-catalogue"].status == "blocked"


def test_verifier_rejects_a_clean_but_unreviewed_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(verify_dev_pi, "CANONICAL_REPO", tmp_path)

    def git_output(command: list[str], *, cwd: Path | None = None) -> str:
        del cwd
        return "a" * 40 if "rev-parse" in command else ""

    monkeypatch.setattr(verify_dev_pi, "_run_bounded", git_output)

    check = verify_dev_pi._repository_check(tmp_path, "b" * 40)

    assert check.status == "fail"
    assert "expected reviewed commit" in check.summary


def test_verifier_requires_service_identity_read_only_checkout_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_user = pwd.struct_passwd(
        ("binnacle", "x", os.geteuid(), os.getegid(), "", "/nonexistent", "/usr/sbin/nologin")
    )
    monkeypatch.setattr(pwd, "getpwnam", lambda _name: service_user)

    def read_only_access(_path: Path, mode: int) -> bool:
        return mode != os.W_OK

    monkeypatch.setattr(os, "access", read_only_access)

    check = verify_dev_pi._checkout_access_check(tmp_path)

    assert check.status == "pass"
    assert "without source write access" in check.summary


def test_verifier_rejects_broader_protected_directory_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o770)
    expected_group = grp.struct_group(("binnacle", "x", tmp_path.stat().st_gid, []))
    monkeypatch.setattr(grp, "getgrnam", lambda _name: expected_group)

    check = verify_dev_pi._protected_directory_check(tmp_path, "protected-config-directory")

    assert check.status == "fail"
    assert "root:binnacle 0750" in check.summary


def test_verifier_reads_only_bounded_non_secret_server_fields(tmp_path: Path) -> None:
    config = tmp_path / "dev.toml"
    config.write_text(
        """
runtime_profile = "development"

[server]
host = "127.0.0.1"
port = 8000
workers = 1

[unrelated]
credential_reference = "not-rendered"
""".strip(),
        encoding="utf-8",
    )

    assert verify_dev_pi._safe_server_settings(config) == ("127.0.0.1", 8000, 1)

    config.write_text(
        '[server]\nhost = "127.0.0.1"\nport = 8000\nworkers = true\n',
        encoding="utf-8",
    )
    assert verify_dev_pi._safe_server_settings(config) is None


def test_verifier_accepts_only_the_fixed_bounded_probe_profile(tmp_path: Path) -> None:
    config = tmp_path / "dev.toml"
    config.write_text(
        """
[probe_workspace]
enabled = false
root = "/var/lib/binnacle/probe-workspace"
max_file_bytes = 65536
preparation_ttl_seconds = 300
""".strip(),
        encoding="utf-8",
    )

    assert verify_dev_pi._safe_probe_settings(config) == (False, 65_536, 300)

    config.write_text(
        '[probe_workspace]\nroot = "/tmp/model-selected"\n',
        encoding="utf-8",
    )
    assert verify_dev_pi._safe_probe_settings(config) is None


def test_probe_mount_profile_accepts_only_reviewed_ext4_block_storage() -> None:
    mount = verify_dev_pi._parse_probe_mount_facts(
        json.dumps(
            {
                "filesystems": [
                    {
                        "target": "/",
                        "source": "/dev/mmcblk0p2",
                        "fstype": "ext4",
                        "options": "rw,relatime",
                        "fsroot": "/",
                    }
                ]
            }
        )
    )

    assert verify_dev_pi._probe_mount_is_supported(
        mount,
        root_device=7,
        protected_devices=frozenset({7}),
    )


@pytest.mark.parametrize(
    "filesystem",
    ("nfs4", "ceph", "cifs", "xfs"),
)
def test_probe_mount_profile_rejects_network_and_unreviewed_filesystems(
    filesystem: str,
) -> None:
    mount = verify_dev_pi._ProbeMountFacts(
        target=Path("/"),
        source="/dev/mmcblk0p2",
        filesystem_type=filesystem,
        options=frozenset({"rw"}),
        filesystem_root="/",
    )

    assert not verify_dev_pi._probe_mount_is_supported(
        mount,
        root_device=7,
        protected_devices=frozenset({7}),
    )


def test_probe_mount_profile_rejects_bind_to_checkout_subdirectory() -> None:
    mount = verify_dev_pi._ProbeMountFacts(
        target=verify_dev_pi.PROBE_ROOT,
        source="/dev/mmcblk0p2[/srv/binnacle-dev/repo/probe-data]",
        filesystem_type="ext4",
        options=frozenset({"rw", "bind"}),
        filesystem_root="/srv/binnacle-dev/repo/probe-data",
    )

    assert not verify_dev_pi._probe_mount_is_supported(
        mount,
        root_device=7,
        protected_devices=frozenset({7}),
    )


def test_probe_mount_profile_rejects_whole_filesystem_alias_of_protected_tree() -> None:
    mount = verify_dev_pi._ProbeMountFacts(
        target=verify_dev_pi.PROBE_ROOT,
        source="/dev/mmcblk0p2",
        filesystem_type="ext4",
        options=frozenset({"rw"}),
        filesystem_root="/",
    )

    assert not verify_dev_pi._probe_mount_is_supported(
        mount,
        root_device=7,
        protected_devices=frozenset({7}),
    )
    assert verify_dev_pi._probe_mount_is_supported(
        mount,
        root_device=8,
        protected_devices=frozenset({7}),
    )


def test_verifier_rejects_broadened_effective_write_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {
        "ActiveState": "active",
        "UnitFileState": "enabled",
        "User": "binnacle",
        "Group": "binnacle",
        "SupplementaryGroups": "binnacle-dev binnacle-executor-client",
        "Environment": "",
        "EnvironmentFiles": "",
        "ReadWritePaths": " ".join(
            sorted(verify_dev_pi.EXPECTED_READ_WRITE_PATHS | {"/srv/binnacle-dev/repo"})
        ),
        "ProtectSystem": "strict",
        "FragmentPath": "/etc/systemd/system/binnacle-dev.service",
        "DropInPaths": "",
        "KillMode": "control-group",
        "SendSIGKILL": "yes",
        "Delegate": "no",
    }
    monkeypatch.setattr(verify_dev_pi, "_systemd_properties", lambda _names: expected)
    service = pwd.struct_passwd(("binnacle", "x", 1200, 1200, "", "/", "/usr/sbin/nologin"))
    monkeypatch.setattr(pwd, "getpwnam", lambda _name: service)
    groups = {
        "binnacle": grp.struct_group(("binnacle", "x", 1200, [])),
        "binnacle-dev": grp.struct_group(("binnacle-dev", "x", 1201, [])),
        "binnacle-executor-client": grp.struct_group(("binnacle-executor-client", "x", 1202, [])),
    }
    monkeypatch.setattr(grp, "getgrnam", lambda name: groups[name])

    checks = {check.name: check for check in verify_dev_pi._systemd_service_checks()}

    assert checks["service-identity"].status == "pass"
    assert checks["service-write-boundary"].status == "fail"
    assert checks["service-process-lifecycle"].status == "pass"

    groups["binnacle-dev"] = grp.struct_group(("binnacle-dev", "x", 1200, []))
    aliased = {check.name: check for check in verify_dev_pi._systemd_service_checks()}
    assert aliased["service-identity"].status == "fail"
