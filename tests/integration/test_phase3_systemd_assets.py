"""Static and safe functional checks for Phase 3 development-Pi assets."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts import setup_dev_pi, verify_dev_pi


def test_systemd_unit_has_exact_unprivileged_source_checkout_shape(repo_root: Path) -> None:
    unit = (repo_root / "deploy/systemd/binnacle-dev.service").read_text(encoding="utf-8")

    required_lines = {
        "User=binnacle",
        "Group=binnacle",
        "SupplementaryGroups=binnacle-dev",
        "WorkingDirectory=/srv/binnacle-dev/repo",
        (
            "ExecStart=/srv/binnacle-dev/repo/.venv/bin/binnacle serve "
            "--config /etc/binnacle/dev.toml"
        ),
        "NoNewPrivileges=yes",
        "ProtectSystem=strict",
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


def test_verifier_keeps_external_live_gates_explicitly_blocked(tmp_path: Path) -> None:
    checks = verify_dev_pi.verify_deployment(
        config_path=tmp_path / "missing-dev.toml",
        controller_profile_path=tmp_path / "missing-controller.toml",
        repo=tmp_path / "missing-repo",
    )
    by_name = {check.name: check for check in checks}

    assert by_name["application-config"].status == "fail"
    assert by_name["selected-auth-profile"].status == "blocked"
    assert by_name["authenticated-catalogue"].status == "blocked"
    assert by_name["tunnel-identity"].status == "blocked"


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
