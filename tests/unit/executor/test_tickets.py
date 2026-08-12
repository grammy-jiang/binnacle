from __future__ import annotations

import errno
import os
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from tests.phase7_support import (
    BOOT_SHA,
    NOW,
    SHA_A,
    SHA_B,
    SHA_C,
    SHA_D,
    SHA_E,
    execution_ticket,
    resource_plan,
)

from binnacle.domain.execution import ExecutionTicket
from binnacle.executor import tickets as tickets_module
from binnacle.executor.tickets import (
    CommandProfileBinding,
    ExecutionTicketRejected,
    ExecutionTicketValidator,
    TicketValidationProfile,
    inspect_executable,
)


def _profile(executable: Path, identity: str) -> TicketValidationProfile:
    fixture = execution_ticket(
        executable_path=str(executable),
        executable_identity_sha256=identity,
    )
    return TicketValidationProfile(
        boot_id_digest=BOOT_SHA,
        command_profiles={
            "command-profile-v1": CommandProfileBinding(
                workspace_id="workspace-fixture",
                workspace_profile_sha256=SHA_C,
                workspace_root_identity_sha256=SHA_D,
                workspace_mount_identity_sha256=SHA_E,
                policy_sha256=SHA_B,
                mount_plan_id="mount-plan-v1",
                mount_plan_sha256=SHA_C,
                sandbox_profile_id="sandbox-profile-v1",
                sandbox_plan_sha256=SHA_D,
                process_isolation_profile_id="process-profile-v1",
                process_isolation_plan_sha256=SHA_E,
                network_profile_id="network-denied-v1",
                network_plan_sha256=SHA_A,
                listener_exposure="denied",
                environment_sha256=fixture.environment_sha256,
                permitted_cwd_sha256=frozenset({fixture.cwd_sha256}),
                permitted_argv_prefixes=(("python3", "-c"),),
                resource_maximum=resource_plan(),
                permitted_environment_names=frozenset({"LANG"}),
                permitted_input_modes=frozenset({"inline"}),
            )
        },
        permitted_executables={str(executable): identity},
        maximum_ticket_lifetime_seconds=600,
    )


def test_ticket_validator_reopens_exact_executable_and_detects_replacement(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "reviewed-command"
    executable.write_bytes(b"#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    identity = inspect_executable(executable)
    ticket = execution_ticket(
        executable_path=str(executable),
        executable_identity_sha256=identity.identity_sha256,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        monotonic_deadline_ns=10_000,
    )
    validator = ExecutionTicketValidator(
        _profile(executable, identity.identity_sha256),
        wall_clock=lambda: NOW + timedelta(seconds=1),
        monotonic_clock_ns=lambda: 1,
    )

    assert validator.validate(ticket) == identity
    executable.write_bytes(b"#!/bin/sh\nexit 1\n")
    with pytest.raises(ExecutionTicketRejected, match="identity changed"):
        validator.validate(ticket)


def test_ticket_validator_rejects_elapsed_deadlines(tmp_path: Path) -> None:
    executable = tmp_path / "reviewed-command"
    executable.write_bytes(b"fixture")
    executable.chmod(0o755)
    identity = inspect_executable(executable)
    ticket = execution_ticket(
        executable_path=str(executable),
        executable_identity_sha256=identity.identity_sha256,
        issued_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
        monotonic_deadline_ns=10,
    )
    validator = ExecutionTicketValidator(
        _profile(executable, identity.identity_sha256),
        wall_clock=lambda: NOW + timedelta(seconds=31),
        monotonic_clock_ns=lambda: 11,
    )

    with pytest.raises(ExecutionTicketRejected, match="not current"):
        validator.validate(ticket)


def test_executable_symlink_is_rejected(tmp_path: Path) -> None:
    executable = tmp_path / "reviewed-command"
    executable.write_bytes(b"fixture")
    executable.chmod(0o755)
    alias = tmp_path / "alias"
    alias.symlink_to(executable)

    with pytest.raises(ExecutionTicketRejected, match="opened safely"):
        inspect_executable(alias)


def test_ticket_validator_rejects_unselected_environment_and_plan(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "reviewed-command"
    executable.write_bytes(b"fixture")
    executable.chmod(0o755)
    identity = inspect_executable(executable)
    profile = _profile(executable, identity.identity_sha256)
    validator = ExecutionTicketValidator(
        profile,
        wall_clock=lambda: NOW + timedelta(seconds=1),
        monotonic_clock_ns=lambda: 1,
    )
    environment_ticket = execution_ticket(
        executable_path=str(executable),
        executable_identity_sha256=identity.identity_sha256,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        monotonic_deadline_ns=10_000,
        environment={"CUSTOM_VAR": "local"},
    )
    with pytest.raises(ExecutionTicketRejected, match="environment"):
        validator.validate(environment_ticket)

    plan_ticket = execution_ticket(
        executable_path=str(executable),
        executable_identity_sha256=identity.identity_sha256,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        monotonic_deadline_ns=10_000,
        network_plan_sha256=SHA_B,
    )
    with pytest.raises(ExecutionTicketRejected, match="authority plan"):
        validator.validate(plan_ticket)


def _validation_fixture(
    tmp_path: Path,
) -> tuple[Path, str, ExecutionTicket, TicketValidationProfile]:
    executable = tmp_path / "reviewed-command"
    executable.write_bytes(b"#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    identity = inspect_executable(executable)
    ticket = execution_ticket(
        executable_path=str(executable),
        executable_identity_sha256=identity.identity_sha256,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        monotonic_deadline_ns=10_000,
    )
    return (
        executable,
        identity.identity_sha256,
        ticket,
        _profile(
            executable,
            identity.identity_sha256,
        ),
    )


def _validator(profile: TicketValidationProfile) -> ExecutionTicketValidator:
    return ExecutionTicketValidator(
        profile,
        wall_clock=lambda: NOW + timedelta(seconds=1),
        monotonic_clock_ns=lambda: 1,
    )


def test_profile_construction_rejects_empty_authority_and_invalid_modes(
    tmp_path: Path,
) -> None:
    _, _, _, profile = _validation_fixture(tmp_path)
    binding = profile.command_profiles["command-profile-v1"]

    with pytest.raises(ExecutionTicketRejected, match="allowlist is empty"):
        replace(binding, permitted_environment_names=frozenset())
    with pytest.raises(ExecutionTicketRejected, match="input modes are invalid"):
        replace(binding, permitted_input_modes=frozenset({"pipe"}))
    with pytest.raises(ExecutionTicketRejected, match="lifetime ceiling"):
        replace(profile, maximum_ticket_lifetime_seconds=0)
    with pytest.raises(ExecutionTicketRejected, match="no reviewed executable"):
        replace(profile, permitted_executables={})


def test_validator_rejects_untrusted_time_boot_lifetime_and_profile_selection(
    tmp_path: Path,
) -> None:
    _, _, ticket, profile = _validation_fixture(tmp_path)

    with pytest.raises(ExecutionTicketRejected, match="not timezone-aware"):
        ExecutionTicketValidator(
            profile,
            wall_clock=lambda: NOW.replace(tzinfo=None),
            monotonic_clock_ns=lambda: 1,
        ).validate(ticket)

    with pytest.raises(ExecutionTicketRejected, match="boot identity is stale"):
        _validator(replace(profile, boot_id_digest=SHA_A)).validate(ticket)

    with pytest.raises(ExecutionTicketRejected, match="monotonic deadline elapsed"):
        ExecutionTicketValidator(
            profile,
            wall_clock=lambda: NOW + timedelta(seconds=1),
            monotonic_clock_ns=lambda: ticket.monotonic_deadline_ns,
        ).validate(ticket)

    with pytest.raises(ExecutionTicketRejected, match="lifetime exceeds"):
        _validator(replace(profile, maximum_ticket_lifetime_seconds=60)).validate(ticket)

    binding = profile.command_profiles["command-profile-v1"]
    missing_profile = replace(profile, command_profiles={"other-profile": binding})
    with pytest.raises(ExecutionTicketRejected, match="not promoted"):
        _validator(missing_profile).validate(ticket)


def test_validator_rejects_each_receiver_owned_command_constraint(
    tmp_path: Path,
) -> None:
    _, executable_identity, ticket, profile = _validation_fixture(tmp_path)
    binding = profile.command_profiles["command-profile-v1"]

    smaller_resources = replace(resource_plan(), output_bytes=1)
    resource_profile = replace(
        profile,
        command_profiles={
            "command-profile-v1": replace(
                binding,
                resource_maximum=smaller_resources,
            )
        },
    )
    with pytest.raises(ExecutionTicketRejected, match="resources exceed"):
        _validator(resource_profile).validate(ticket)

    cwd_profile = replace(
        profile,
        command_profiles={
            "command-profile-v1": replace(
                binding,
                permitted_cwd_sha256=frozenset({SHA_A}),
            )
        },
    )
    with pytest.raises(ExecutionTicketRejected, match="cwd is not selected"):
        _validator(cwd_profile).validate(ticket)

    argv_profile = replace(
        profile,
        command_profiles={
            "command-profile-v1": replace(
                binding,
                permitted_argv_prefixes=(("unselected-command",),),
            )
        },
    )
    with pytest.raises(ExecutionTicketRejected, match="argv is outside"):
        _validator(argv_profile).validate(ticket)

    input_profile = replace(
        profile,
        command_profiles={
            "command-profile-v1": replace(
                binding,
                permitted_input_modes=frozenset({"none"}),
            )
        },
    )
    with pytest.raises(ExecutionTicketRejected, match="input mode is not selected"):
        _validator(input_profile).validate(ticket)

    executable_profile = replace(
        profile,
        permitted_executables={"/usr/bin/unselected": executable_identity},
    )
    with pytest.raises(ExecutionTicketRejected, match="executable is not selected"):
        _validator(executable_profile).validate(ticket)


def test_input_mode_classifier_covers_each_domain_validated_source() -> None:
    reference = execution_ticket(operation_id="op-reference", ticket_id="ticket-reference")
    object.__setattr__(reference, "inline_stdin", None)
    object.__setattr__(reference, "stdin_sha256", None)
    object.__setattr__(reference, "stdin_reference_sha256", SHA_A)
    assert tickets_module._ticket_input_mode(reference) == "reference"

    workspace_script = execution_ticket(
        operation_id="op-workspace-script",
        ticket_id="ticket-workspace-script",
    )
    object.__setattr__(workspace_script, "inline_stdin", None)
    object.__setattr__(workspace_script, "stdin_sha256", None)
    object.__setattr__(workspace_script, "workspace_script_sha256", SHA_B)
    assert tickets_module._ticket_input_mode(workspace_script) == "workspace_script"

    absent = execution_ticket(operation_id="op-no-input", ticket_id="ticket-no-input")
    object.__setattr__(absent, "inline_stdin", None)
    object.__setattr__(absent, "stdin_sha256", None)
    assert tickets_module._ticket_input_mode(absent) == "none"


def test_executable_inspection_rejects_directory_setid_and_nonexecutable(
    tmp_path: Path,
) -> None:
    with pytest.raises(ExecutionTicketRejected, match="not a regular file"):
        inspect_executable(tmp_path)

    setid = tmp_path / "setid-command"
    setid.write_bytes(b"fixture")
    setid.chmod(0o4755)
    with pytest.raises(ExecutionTicketRejected, match="set-id"):
        inspect_executable(setid)

    nonexecutable = tmp_path / "nonexecutable-command"
    nonexecutable.write_bytes(b"fixture")
    nonexecutable.chmod(0o644)
    with pytest.raises(ExecutionTicketRejected, match="not executable"):
        inspect_executable(nonexecutable)


def test_executable_inspection_rejects_capabilities_and_uninspectable_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "reviewed-command"
    executable.write_bytes(b"fixture")
    executable.chmod(0o755)

    monkeypatch.setattr(os, "getxattr", lambda *_args: b"capability")
    with pytest.raises(ExecutionTicketRejected, match="capability-bearing"):
        inspect_executable(executable)

    def reject_inspection(*_args: object) -> bytes:
        raise OSError(errno.EACCES, "permission denied")

    monkeypatch.setattr(os, "getxattr", reject_inspection)
    with pytest.raises(ExecutionTicketRejected, match="cannot be inspected"):
        inspect_executable(executable)

    monkeypatch.setattr(os, "getxattr", lambda *_args: b"")
    assert inspect_executable(executable).path == str(executable)
