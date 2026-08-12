"""Framework-independent Phase 7 execution identities and state invariants."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

EXECUTOR_PROTOCOL_ID: Final = "binnacle-executor"
EXECUTOR_PROTOCOL_VERSION: Final = "1.0"
MAX_EXECUTOR_FRAME_BYTES: Final = 1_048_576
MAX_INLINE_STDIN_BYTES: Final = 65_536
MAX_OUTPUT_CHUNK_BYTES: Final = 262_144
MAX_ARGV_ITEMS: Final = 256
MAX_ARGUMENT_BYTES: Final = 16_384
MAX_ENVIRONMENT_ITEMS: Final = 64
MAX_ENVIRONMENT_VALUE_BYTES: Final = 8_192

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ENVIRONMENT_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_ABSOLUTE_EXECUTABLE = re.compile(r"^/(?:[^/\x00\r\n]+/)*[^/\x00\r\n]+$")
_FORBIDDEN_ENVIRONMENT_NAMES: Final = frozenset(
    {
        "BASH_ENV",
        "ALL_PROXY",
        "DOCKER_HOST",
        "ENV",
        "GPG_AGENT_INFO",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "KUBECONFIG",
        "NO_PROXY",
        "PYTHONHOME",
        "PYTHONPATH",
        "SSH_AUTH_SOCK",
    }
)
_FORBIDDEN_ENVIRONMENT_PREFIXES: Final = (
    "BINNACLE_",
    "AWS_",
    "AZURE_",
    "DOCKER_",
    "DYLD_",
    "GIT_",
    "GOOGLE_",
    "LD_",
    "OCI_",
)


class ExecutionError(ValueError):
    """An execution value or state transition violates the Phase 7 contract."""


class ExecutionConflictError(ExecutionError):
    """A retained execution identity conflicts with a replayed request."""


class DispatchCommitKnowledge(StrEnum):
    PRE_COMMIT_CURRENT_RUNTIME = "pre_commit_current_runtime"
    COMMITTED_CURRENT_RUNTIME = "committed_current_runtime"
    UNKNOWN_AFTER_RUNTIME_LOSS = "unknown_after_runtime_loss"


class ExecutorEvidenceState(StrEnum):
    ACCEPTED = "accepted"
    LAUNCH_PREPARING = "launch_preparing"
    LAUNCH_COMMITTED = "launch_committed"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLING = "cancelling"
    EXITED = "exited"
    CLEANUP_PENDING = "cleanup_pending"
    CLOSED = "closed"
    EXECUTOR_UNCERTAIN = "executor_uncertain"


class ExecutionStartDisposition(StrEnum):
    ACCEPTED_EXECUTION = "accepted_execution"
    NO_ACCEPT_PROVEN = "no_accept_proven"


class CancelRoutingDisposition(StrEnum):
    PENDING_PREACCEPT = "pending_preaccept"
    ACCEPTED_EXECUTION = "accepted_execution"
    NO_ACCEPT_PROVEN = "no_accept_proven"


class CancelDisposition(StrEnum):
    PENDING_PREACCEPT = "pending_preaccept"
    ATTACHED_PRELAUNCH = "attached_prelaunch"
    SIGNAL_PENDING = "signal_pending"
    SIGNAL_APPLIED = "signal_applied"
    TERMINAL_ALREADY_WON = "terminal_already_won"
    NO_ACCEPT_PROVEN = "no_accept_proven"
    UNCERTAIN = "uncertain"


class CreateReceiptDisposition(StrEnum):
    NOT_ATTEMPTED = "not_attempted"
    COMMITTED_PENDING = "committed_pending"
    DOMAIN_CREATED = "domain_created"
    NO_DOMAIN = "no_domain"
    AMBIGUOUS = "ambiguous"


class OutputStream(StrEnum):
    STDOUT = "stdout"
    STDERR = "stderr"


class OutputAvailability(StrEnum):
    AVAILABLE = "available"
    TRUNCATED = "truncated"
    EXPIRED = "expired"


class CommandAcceptanceState(StrEnum):
    UNRESOLVED = "unresolved"
    ACCEPTED_EXECUTION = "accepted_execution"
    NO_ACCEPT_PROVEN = "no_accept_proven"


class CommandClosureState(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class ExecutorHello:
    protocol_id: str
    protocol_version: str
    build_sha256: str
    profile_sha256: str
    supervisor_instance_id: str
    supervisor_generation: int
    backend_ready: bool
    readiness: str

    def __post_init__(self) -> None:
        if (
            self.protocol_id != EXECUTOR_PROTOCOL_ID
            or self.protocol_version != EXECUTOR_PROTOCOL_VERSION
        ):
            raise ExecutionError("executor hello protocol identity is incompatible")
        validate_sha256(self.build_sha256, name="build_sha256")
        validate_sha256(self.profile_sha256, name="profile_sha256")
        validate_identifier(self.supervisor_instance_id, name="supervisor_instance_id")
        if self.supervisor_generation < 1 or self.readiness not in {
            "ready",
            "recovering",
            "integrity_failed",
        }:
            raise ExecutionError("executor hello readiness is invalid")


@dataclass(frozen=True, slots=True)
class CommandExecutionSnapshot:
    operation_id: str
    session_id: str
    workspace_id: str
    ticket_identity: TicketRoutingIdentity
    ticket_correlation_sha256: str
    record_version: int
    acceptance_state: CommandAcceptanceState
    execution_id: str | None
    executor_reference: str | None
    accepted_receipt_sha256: str | None
    no_accept_reference: str | None
    no_accept_receipt_sha256: str | None
    cancel_generation: int
    acknowledged_cancel_generation: int
    cancel_disposition: CancelDisposition | None
    supervisor_evidence_generation: int
    supervisor_cancel_evidence_sha256: str | None
    last_executor_state: ExecutorEvidenceState | None
    terminal_evidence_sha256: str | None
    descendants_stopped: bool
    output_finalized: bool
    private_resources_cleaned: bool
    cleanup_evidence_sha256: str | None
    closure_state: CommandClosureState
    created_at: datetime
    updated_at: datetime
    last_reconciled_at: datetime | None

    def __post_init__(self) -> None:
        for name, identifier in (
            ("operation_id", self.operation_id),
            ("session_id", self.session_id),
            ("workspace_id", self.workspace_id),
        ):
            validate_identifier(identifier, name=name)
        validate_sha256(self.ticket_correlation_sha256, name="ticket_correlation_sha256")
        for name, digest in (
            ("accepted_receipt_sha256", self.accepted_receipt_sha256),
            ("no_accept_receipt_sha256", self.no_accept_receipt_sha256),
            ("supervisor_cancel_evidence_sha256", self.supervisor_cancel_evidence_sha256),
            ("terminal_evidence_sha256", self.terminal_evidence_sha256),
            ("cleanup_evidence_sha256", self.cleanup_evidence_sha256),
        ):
            if digest is not None:
                validate_sha256(digest, name=name)
        if (
            self.record_version < 1
            or self.cancel_generation < 0
            or self.acknowledged_cancel_generation < 0
            or self.acknowledged_cancel_generation > self.cancel_generation
            or self.supervisor_evidence_generation < 0
        ):
            raise ExecutionError("command execution generations are invalid")
        accepted = self.acceptance_state is CommandAcceptanceState.ACCEPTED_EXECUTION
        sealed = self.acceptance_state is CommandAcceptanceState.NO_ACCEPT_PROVEN
        if accepted != all(
            value is not None
            for value in (
                self.execution_id,
                self.executor_reference,
                self.accepted_receipt_sha256,
            )
        ):
            raise ExecutionError("command accepted evidence shape is invalid")
        if sealed != all(
            value is not None for value in (self.no_accept_reference, self.no_accept_receipt_sha256)
        ):
            raise ExecutionError("command no-accept evidence shape is invalid")
        if accepted and (self.no_accept_reference is not None or self.no_accept_receipt_sha256):
            raise ExecutionError("command acceptance carries contradictory no-accept evidence")
        if sealed and any(
            value is not None
            for value in (
                self.execution_id,
                self.executor_reference,
                self.accepted_receipt_sha256,
            )
        ):
            raise ExecutionError("command no-accept evidence carries execution evidence")
        if self.closure_state is CommandClosureState.COMPLETE and not (
            self.acceptance_state is not CommandAcceptanceState.UNRESOLVED
            and self.terminal_evidence_sha256 is not None
            and self.descendants_stopped
            and self.output_finalized
            and self.private_resources_cleaned
            and self.cleanup_evidence_sha256 is not None
            and self.acknowledged_cancel_generation == self.cancel_generation
        ):
            raise ExecutionError("command closure lacks exact terminal evidence")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ExecutionError("command execution timestamps must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ResourcePlan:
    wall_time_seconds: int
    cpu_time_seconds: int
    memory_bytes: int
    swap_bytes: int
    pids: int
    open_files: int
    output_bytes: int
    workspace_write_bytes: int
    workspace_inodes: int

    def __post_init__(self) -> None:
        values = (
            self.wall_time_seconds,
            self.cpu_time_seconds,
            self.memory_bytes,
            self.pids,
            self.open_files,
            self.output_bytes,
            self.workspace_write_bytes,
            self.workspace_inodes,
        )
        if any(value < 1 for value in values) or self.swap_bytes < 0:
            raise ExecutionError("resource limits must be positive and swap cannot be negative")
        if self.wall_time_seconds > 86_400 or self.cpu_time_seconds > 86_400:
            raise ExecutionError("execution time limit exceeds the Bootstrap ceiling")

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.to_wire())

    def to_wire(self) -> dict[str, int]:
        return {
            "cpu_time_seconds": self.cpu_time_seconds,
            "memory_bytes": self.memory_bytes,
            "open_files": self.open_files,
            "output_bytes": self.output_bytes,
            "pids": self.pids,
            "swap_bytes": self.swap_bytes,
            "wall_time_seconds": self.wall_time_seconds,
            "workspace_inodes": self.workspace_inodes,
            "workspace_write_bytes": self.workspace_write_bytes,
        }

    @classmethod
    def from_wire(cls, value: Mapping[str, object]) -> ResourcePlan:
        expected = frozenset(
            {
                "cpu_time_seconds",
                "memory_bytes",
                "open_files",
                "output_bytes",
                "pids",
                "swap_bytes",
                "wall_time_seconds",
                "workspace_inodes",
                "workspace_write_bytes",
            }
        )
        if frozenset(value) != expected:
            raise ExecutionError("resource plan fields are not exact")
        return cls(**{name: _require_int(value, name) for name in expected})


@dataclass(frozen=True, slots=True)
class TicketRoutingIdentity:
    """Bounded ticket facts needed to route cancel/seal before first acceptance."""

    operation_id: str
    ticket_id: str
    ticket_sha256: str
    nonce_sha256: str
    boot_id_digest: str
    expires_at: datetime
    monotonic_deadline_ns: int

    def __post_init__(self) -> None:
        validate_identifier(self.operation_id, name="operation_id")
        validate_identifier(self.ticket_id, name="ticket_id")
        validate_sha256(self.ticket_sha256, name="ticket_sha256")
        validate_sha256(self.nonce_sha256, name="nonce_sha256")
        validate_sha256(self.boot_id_digest, name="boot_id_digest")
        if self.expires_at.tzinfo is None or self.monotonic_deadline_ns < 0:
            raise ExecutionError("ticket routing deadline is invalid")


@dataclass(frozen=True, slots=True)
class ExecutionTicket:
    ticket_id: str
    operation_id: str
    ticket_sha256: str
    controller_identity_sha256: str
    controller_epoch: int
    device_id: str
    device_epoch: int
    development_session_id: str
    development_session_state_version: int
    development_session_closure_sha256: str
    command_profile_id: str
    workspace_id: str
    workspace_profile_sha256: str
    workspace_root_identity_sha256: str
    workspace_mount_identity_sha256: str
    workspace_fence_version: int
    executable_path: str
    executable_identity_sha256: str
    argv: tuple[str, ...]
    argv_sha256: str
    cwd_relative: str
    cwd_sha256: str
    environment: tuple[tuple[str, str], ...]
    environment_sha256: str
    inline_stdin: bytes | None
    stdin_sha256: str | None
    stdin_reference_sha256: str | None
    workspace_script_sha256: str | None
    policy_sha256: str
    resource_plan: ResourcePlan
    resource_plan_sha256: str
    mount_plan_id: str
    mount_plan_sha256: str
    sandbox_profile_id: str
    sandbox_plan_sha256: str
    process_isolation_profile_id: str
    process_isolation_plan_sha256: str
    network_profile_id: str
    network_plan_sha256: str
    listener_exposure: str
    admission_record_id: str
    issued_at: datetime
    expires_at: datetime
    boot_id_digest: str
    monotonic_deadline_ns: int
    single_use_nonce: str

    def __post_init__(self) -> None:
        for name, value in (
            ("ticket_id", self.ticket_id),
            ("operation_id", self.operation_id),
            ("device_id", self.device_id),
            ("development_session_id", self.development_session_id),
            ("command_profile_id", self.command_profile_id),
            ("workspace_id", self.workspace_id),
            ("admission_record_id", self.admission_record_id),
            ("single_use_nonce", self.single_use_nonce),
            ("mount_plan_id", self.mount_plan_id),
            ("sandbox_profile_id", self.sandbox_profile_id),
            ("process_isolation_profile_id", self.process_isolation_profile_id),
            ("network_profile_id", self.network_profile_id),
            ("listener_exposure", self.listener_exposure),
        ):
            validate_identifier(value, name=name)
        for name, value in (
            ("ticket_sha256", self.ticket_sha256),
            ("controller_identity_sha256", self.controller_identity_sha256),
            ("development_session_closure_sha256", self.development_session_closure_sha256),
            ("workspace_profile_sha256", self.workspace_profile_sha256),
            ("workspace_root_identity_sha256", self.workspace_root_identity_sha256),
            ("workspace_mount_identity_sha256", self.workspace_mount_identity_sha256),
            ("executable_identity_sha256", self.executable_identity_sha256),
            ("argv_sha256", self.argv_sha256),
            ("cwd_sha256", self.cwd_sha256),
            ("environment_sha256", self.environment_sha256),
            ("policy_sha256", self.policy_sha256),
            ("resource_plan_sha256", self.resource_plan_sha256),
            ("mount_plan_sha256", self.mount_plan_sha256),
            ("sandbox_plan_sha256", self.sandbox_plan_sha256),
            ("process_isolation_plan_sha256", self.process_isolation_plan_sha256),
            ("network_plan_sha256", self.network_plan_sha256),
            ("boot_id_digest", self.boot_id_digest),
        ):
            validate_sha256(value, name=name)
        if self.stdin_sha256 is not None:
            validate_sha256(self.stdin_sha256, name="stdin_sha256")
        if self.stdin_reference_sha256 is not None:
            validate_sha256(self.stdin_reference_sha256, name="stdin_reference_sha256")
        if self.workspace_script_sha256 is not None:
            validate_sha256(self.workspace_script_sha256, name="workspace_script_sha256")
        if (
            min(
                self.controller_epoch,
                self.device_epoch,
                self.development_session_state_version,
                self.workspace_fence_version,
            )
            < 1
        ):
            raise ExecutionError("ticket epoch/fence values must be positive")
        if self.monotonic_deadline_ns < 0:
            raise ExecutionError("ticket monotonic deadline cannot be negative")
        if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ExecutionError("ticket timestamps must be timezone-aware")
        if self.expires_at <= self.issued_at:
            raise ExecutionError("ticket expiry must follow issuance")
        validate_executable_path(self.executable_path)
        normalized_argv = normalize_argv(self.argv)
        if normalized_argv != self.argv or argv_sha256(normalized_argv) != self.argv_sha256:
            raise ExecutionError("ticket argv does not match its canonical digest")
        normalized_environment = normalize_environment(dict(self.environment))
        if (
            normalized_environment != self.environment
            or environment_sha256(normalized_environment) != self.environment_sha256
        ):
            raise ExecutionError("ticket environment does not match its canonical digest")
        normalize_relative_cwd(self.cwd_relative)
        if canonical_sha256(self.cwd_relative) != self.cwd_sha256:
            raise ExecutionError("ticket cwd does not match its canonical digest")
        if self.resource_plan.sha256 != self.resource_plan_sha256:
            raise ExecutionError("ticket resource plan does not match its canonical digest")
        if self.inline_stdin is None:
            if self.stdin_sha256 is not None:
                raise ExecutionError("absent stdin cannot carry a digest")
        else:
            if len(self.inline_stdin) > MAX_INLINE_STDIN_BYTES:
                raise ExecutionError("inline stdin exceeds the reviewed limit")
            if hashlib.sha256(self.inline_stdin).hexdigest() != self.stdin_sha256:
                raise ExecutionError("inline stdin does not match its digest")
        if (
            sum(
                item is not None
                for item in (
                    self.inline_stdin,
                    self.stdin_reference_sha256,
                    self.workspace_script_sha256,
                )
            )
            > 1
        ):
            raise ExecutionError("ticket input sources are mutually exclusive")
        if self.computed_sha256() != self.ticket_sha256:
            raise ExecutionError("execution ticket digest mismatch")

    def computed_sha256(self) -> str:
        return canonical_sha256(self._digest_document())

    def _digest_document(self) -> Mapping[str, object]:
        return {
            "admission_record_id": self.admission_record_id,
            "argv": list(self.argv),
            "argv_sha256": self.argv_sha256,
            "boot_id_digest": self.boot_id_digest,
            "command_profile_id": self.command_profile_id,
            "controller_epoch": self.controller_epoch,
            "controller_identity_sha256": self.controller_identity_sha256,
            "cwd_relative": self.cwd_relative,
            "cwd_sha256": self.cwd_sha256,
            "development_session_closure_sha256": self.development_session_closure_sha256,
            "development_session_id": self.development_session_id,
            "development_session_state_version": self.development_session_state_version,
            "device_epoch": self.device_epoch,
            "device_id": self.device_id,
            "environment": [[name, value] for name, value in self.environment],
            "environment_sha256": self.environment_sha256,
            "executable_identity_sha256": self.executable_identity_sha256,
            "executable_path": self.executable_path,
            "expires_at": canonical_timestamp(self.expires_at),
            "inline_stdin_base64": (
                None
                if self.inline_stdin is None
                else base64.b64encode(self.inline_stdin).decode("ascii")
            ),
            "issued_at": canonical_timestamp(self.issued_at),
            "monotonic_deadline_ns": self.monotonic_deadline_ns,
            "mount_plan_id": self.mount_plan_id,
            "mount_plan_sha256": self.mount_plan_sha256,
            "network_profile_id": self.network_profile_id,
            "network_plan_sha256": self.network_plan_sha256,
            "operation_id": self.operation_id,
            "policy_sha256": self.policy_sha256,
            "process_isolation_plan_sha256": self.process_isolation_plan_sha256,
            "process_isolation_profile_id": self.process_isolation_profile_id,
            "resource_plan": self.resource_plan.to_wire(),
            "resource_plan_sha256": self.resource_plan_sha256,
            "sandbox_profile_id": self.sandbox_profile_id,
            "sandbox_plan_sha256": self.sandbox_plan_sha256,
            "single_use_nonce": self.single_use_nonce,
            "stdin_sha256": self.stdin_sha256,
            "stdin_reference_sha256": self.stdin_reference_sha256,
            "ticket_id": self.ticket_id,
            "listener_exposure": self.listener_exposure,
            "workspace_fence_version": self.workspace_fence_version,
            "workspace_id": self.workspace_id,
            "workspace_mount_identity_sha256": self.workspace_mount_identity_sha256,
            "workspace_profile_sha256": self.workspace_profile_sha256,
            "workspace_root_identity_sha256": self.workspace_root_identity_sha256,
            "workspace_script_sha256": self.workspace_script_sha256,
        }

    def to_wire(self) -> dict[str, object]:
        return {**self._digest_document(), "ticket_sha256": self.ticket_sha256}

    @property
    def routing_identity(self) -> TicketRoutingIdentity:
        return TicketRoutingIdentity(
            operation_id=self.operation_id,
            ticket_id=self.ticket_id,
            ticket_sha256=self.ticket_sha256,
            nonce_sha256=hashlib.sha256(self.single_use_nonce.encode("utf-8")).hexdigest(),
            boot_id_digest=self.boot_id_digest,
            expires_at=self.expires_at,
            monotonic_deadline_ns=self.monotonic_deadline_ns,
        )

    @classmethod
    def from_wire(cls, value: Mapping[str, object]) -> ExecutionTicket:
        expected = frozenset(
            {
                "admission_record_id",
                "argv",
                "argv_sha256",
                "boot_id_digest",
                "command_profile_id",
                "controller_epoch",
                "controller_identity_sha256",
                "cwd_relative",
                "cwd_sha256",
                "development_session_closure_sha256",
                "development_session_id",
                "development_session_state_version",
                "device_epoch",
                "device_id",
                "environment",
                "environment_sha256",
                "executable_identity_sha256",
                "executable_path",
                "expires_at",
                "inline_stdin_base64",
                "issued_at",
                "monotonic_deadline_ns",
                "mount_plan_id",
                "mount_plan_sha256",
                "network_profile_id",
                "network_plan_sha256",
                "operation_id",
                "policy_sha256",
                "process_isolation_plan_sha256",
                "process_isolation_profile_id",
                "resource_plan",
                "resource_plan_sha256",
                "sandbox_profile_id",
                "sandbox_plan_sha256",
                "single_use_nonce",
                "stdin_sha256",
                "stdin_reference_sha256",
                "ticket_id",
                "ticket_sha256",
                "listener_exposure",
                "workspace_fence_version",
                "workspace_id",
                "workspace_mount_identity_sha256",
                "workspace_profile_sha256",
                "workspace_root_identity_sha256",
                "workspace_script_sha256",
            }
        )
        if frozenset(value) != expected:
            raise ExecutionError("execution ticket wire fields are not exact")
        argv_value = value["argv"]
        environment_value = value["environment"]
        resource_plan_value = value["resource_plan"]
        if not isinstance(argv_value, list) or not all(
            isinstance(item, str) for item in argv_value
        ):
            raise ExecutionError("ticket argv wire value is invalid")
        if not isinstance(environment_value, list) or not all(
            isinstance(item, list)
            and len(item) == 2
            and all(isinstance(part, str) for part in item)
            for item in environment_value
        ):
            raise ExecutionError("ticket environment wire value is invalid")
        if not isinstance(resource_plan_value, Mapping):
            raise ExecutionError("ticket resource plan wire value is invalid")
        raw_stdin = value["inline_stdin_base64"]
        if raw_stdin is not None and not isinstance(raw_stdin, str):
            raise ExecutionError("ticket stdin wire value is invalid")
        try:
            inline_stdin = None if raw_stdin is None else base64.b64decode(raw_stdin, validate=True)
            issued_at = datetime.fromisoformat(_require_string(value, "issued_at"))
            expires_at = datetime.fromisoformat(_require_string(value, "expires_at"))
        except (ValueError, TypeError) as exc:
            raise ExecutionError("ticket wire encoding is invalid") from exc
        return cls(
            ticket_id=_require_string(value, "ticket_id"),
            operation_id=_require_string(value, "operation_id"),
            ticket_sha256=_require_string(value, "ticket_sha256"),
            controller_identity_sha256=_require_string(value, "controller_identity_sha256"),
            controller_epoch=_require_int(value, "controller_epoch"),
            device_id=_require_string(value, "device_id"),
            device_epoch=_require_int(value, "device_epoch"),
            development_session_id=_require_string(value, "development_session_id"),
            development_session_state_version=_require_int(
                value, "development_session_state_version"
            ),
            development_session_closure_sha256=_require_string(
                value, "development_session_closure_sha256"
            ),
            command_profile_id=_require_string(value, "command_profile_id"),
            workspace_id=_require_string(value, "workspace_id"),
            workspace_profile_sha256=_require_string(value, "workspace_profile_sha256"),
            workspace_root_identity_sha256=_require_string(value, "workspace_root_identity_sha256"),
            workspace_mount_identity_sha256=_require_string(
                value, "workspace_mount_identity_sha256"
            ),
            workspace_fence_version=_require_int(value, "workspace_fence_version"),
            executable_path=_require_string(value, "executable_path"),
            executable_identity_sha256=_require_string(value, "executable_identity_sha256"),
            argv=tuple(argv_value),
            argv_sha256=_require_string(value, "argv_sha256"),
            cwd_relative=_require_string(value, "cwd_relative"),
            cwd_sha256=_require_string(value, "cwd_sha256"),
            environment=tuple((item[0], item[1]) for item in environment_value),
            environment_sha256=_require_string(value, "environment_sha256"),
            inline_stdin=inline_stdin,
            stdin_sha256=_optional_string(value, "stdin_sha256"),
            stdin_reference_sha256=_optional_string(value, "stdin_reference_sha256"),
            workspace_script_sha256=_optional_string(value, "workspace_script_sha256"),
            policy_sha256=_require_string(value, "policy_sha256"),
            resource_plan=ResourcePlan.from_wire(resource_plan_value),
            resource_plan_sha256=_require_string(value, "resource_plan_sha256"),
            mount_plan_id=_require_string(value, "mount_plan_id"),
            mount_plan_sha256=_require_string(value, "mount_plan_sha256"),
            sandbox_profile_id=_require_string(value, "sandbox_profile_id"),
            sandbox_plan_sha256=_require_string(value, "sandbox_plan_sha256"),
            process_isolation_profile_id=_require_string(value, "process_isolation_profile_id"),
            process_isolation_plan_sha256=_require_string(value, "process_isolation_plan_sha256"),
            network_profile_id=_require_string(value, "network_profile_id"),
            network_plan_sha256=_require_string(value, "network_plan_sha256"),
            listener_exposure=_require_string(value, "listener_exposure"),
            admission_record_id=_require_string(value, "admission_record_id"),
            issued_at=issued_at,
            expires_at=expires_at,
            boot_id_digest=_require_string(value, "boot_id_digest"),
            monotonic_deadline_ns=_require_int(value, "monotonic_deadline_ns"),
            single_use_nonce=_require_string(value, "single_use_nonce"),
        )


@dataclass(frozen=True, slots=True)
class ExecutionStartReceipt:
    disposition: ExecutionStartDisposition
    execution_id: str | None
    evidence_generation: int
    accepted_at: datetime | None
    executor_reference: str | None
    no_accept_reference: str | None
    receipt_sha256: str

    def __post_init__(self) -> None:
        if self.evidence_generation < 1:
            raise ExecutionError("start receipt evidence generation must be positive")
        validate_sha256(self.receipt_sha256, name="receipt_sha256")
        accepted = self.disposition is ExecutionStartDisposition.ACCEPTED_EXECUTION
        if accepted:
            if (
                self.execution_id is None
                or self.accepted_at is None
                or self.executor_reference is None
            ):
                raise ExecutionError("accepted start receipt lacks execution evidence")
            if self.no_accept_reference is not None:
                raise ExecutionError("accepted start receipt carries no-accept evidence")
            validate_identifier(self.execution_id, name="execution_id")
            validate_identifier(self.executor_reference, name="executor_reference")
        else:
            if (
                self.execution_id is not None
                or self.accepted_at is not None
                or self.executor_reference is not None
                or self.no_accept_reference is None
            ):
                raise ExecutionError("no-accept receipt has a contradictory shape")
            validate_identifier(self.no_accept_reference, name="no_accept_reference")


@dataclass(frozen=True, slots=True)
class ExecutorSnapshot:
    operation_id: str
    ticket_id: str
    ticket_sha256: str
    execution_id: str
    state: ExecutorEvidenceState
    state_version: int
    evidence_generation: int
    effective_cancel_generation: int
    acknowledged_cancel_generation: int
    cancel_disposition: CancelDisposition | None
    launch_generation: int
    launch_committed_at: datetime | None
    create_receipt_disposition: CreateReceiptDisposition
    backend_reference: str | None
    backend_domain_identity_sha256: str | None
    accepted_at: datetime
    exit_code: int | None = None
    exit_signal: int | None = None
    terminal_reason: str | None = None
    descendants_stopped: bool = False
    output_finalized: bool = False
    cleanup_complete: bool = False
    terminal_evidence_sha256: str | None = None
    cleanup_evidence_sha256: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("operation_id", self.operation_id),
            ("ticket_id", self.ticket_id),
            ("execution_id", self.execution_id),
        ):
            validate_identifier(value, name=name)
        validate_sha256(self.ticket_sha256, name="ticket_sha256")
        if (
            min(
                self.evidence_generation,
                self.state_version,
                self.effective_cancel_generation,
                self.acknowledged_cancel_generation,
                self.launch_generation,
            )
            < 0
            or self.evidence_generation < 1
            or self.state_version < 1
        ):
            raise ExecutionError("executor snapshot generations are invalid")
        if self.acknowledged_cancel_generation > self.effective_cancel_generation:
            raise ExecutionError("acknowledged cancellation exceeds effective cancellation")
        if self.accepted_at.tzinfo is None:
            raise ExecutionError("executor accepted_at must be timezone-aware")
        if self.backend_reference is not None:
            validate_identifier(self.backend_reference, name="backend_reference")
        if self.backend_domain_identity_sha256 is not None:
            validate_sha256(
                self.backend_domain_identity_sha256,
                name="backend_domain_identity_sha256",
            )
        if self.terminal_evidence_sha256 is not None:
            validate_sha256(self.terminal_evidence_sha256, name="terminal_evidence_sha256")
        if self.cleanup_evidence_sha256 is not None:
            validate_sha256(self.cleanup_evidence_sha256, name="cleanup_evidence_sha256")
        launch_committed = self.launch_committed_at is not None
        if launch_committed != (self.launch_generation > 0):
            raise ExecutionError("executor launch generation/time shape is inconsistent")
        if launch_committed != (
            self.create_receipt_disposition is not CreateReceiptDisposition.NOT_ATTEMPTED
        ):
            raise ExecutionError("executor launch/create receipt shape is inconsistent")
        if self.create_receipt_disposition is CreateReceiptDisposition.DOMAIN_CREATED and (
            self.backend_reference is None or self.backend_domain_identity_sha256 is None
        ):
            raise ExecutionError("created domain lacks exact backend identity")
        terminal_fields = (self.exit_code, self.exit_signal, self.terminal_reason)
        terminal_state = self.state in {
            ExecutorEvidenceState.EXITED,
            ExecutorEvidenceState.CLEANUP_PENDING,
            ExecutorEvidenceState.CLOSED,
        }
        if terminal_state != any(value is not None for value in terminal_fields):
            raise ExecutionError("executor terminal evidence shape is inconsistent")
        if terminal_state and self.terminal_evidence_sha256 is None:
            raise ExecutionError("executor terminal state lacks evidence")
        if self.state is ExecutorEvidenceState.CLOSED and not (
            self.descendants_stopped
            and self.output_finalized
            and self.cleanup_complete
            and self.cleanup_evidence_sha256 is not None
        ):
            raise ExecutionError("closed executor state lacks complete closure evidence")
        if self.cleanup_complete and self.state not in {
            ExecutorEvidenceState.CLOSED,
            ExecutorEvidenceState.EXECUTOR_UNCERTAIN,
        }:
            raise ExecutionError("cleanup completion is inconsistent with executor state")


@dataclass(frozen=True, slots=True)
class ExecutorEvidenceEvent:
    event_id: str
    operation_id: str
    expected_state: ExecutorEvidenceState
    expected_state_version: int
    target_state: ExecutorEvidenceState
    reason_code: str
    recorded_at: datetime
    backend_reference: str | None = None
    backend_domain_identity_sha256: str | None = None
    create_receipt_disposition: CreateReceiptDisposition | None = None
    exit_code: int | None = None
    exit_signal: int | None = None
    terminal_reason: str | None = None
    cancel_disposition: CancelDisposition | None = None
    descendants_stopped: bool | None = None
    output_finalized: bool | None = None
    cleanup_complete: bool | None = None
    terminal_evidence_sha256: str | None = None
    cleanup_evidence_sha256: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.event_id, name="event_id")
        validate_identifier(self.operation_id, name="operation_id")
        validate_identifier(self.reason_code, name="reason_code")
        if self.expected_state_version < 1 or self.recorded_at.tzinfo is None:
            raise ExecutionError("executor evidence event version/time is invalid")
        require_executor_transition(self.expected_state, self.target_state)
        for name, value in (
            ("backend_domain_identity_sha256", self.backend_domain_identity_sha256),
            ("terminal_evidence_sha256", self.terminal_evidence_sha256),
            ("cleanup_evidence_sha256", self.cleanup_evidence_sha256),
        ):
            if value is not None:
                validate_sha256(value, name=name)
        if self.backend_reference is not None:
            validate_identifier(self.backend_reference, name="backend_reference")

    @property
    def event_sha256(self) -> str:
        return canonical_sha256(
            {
                "backend_domain_identity_sha256": self.backend_domain_identity_sha256,
                "backend_reference": self.backend_reference,
                "cancel_disposition": (
                    None if self.cancel_disposition is None else self.cancel_disposition.value
                ),
                "cleanup_complete": self.cleanup_complete,
                "cleanup_evidence_sha256": self.cleanup_evidence_sha256,
                "create_receipt_disposition": (
                    None
                    if self.create_receipt_disposition is None
                    else self.create_receipt_disposition.value
                ),
                "descendants_stopped": self.descendants_stopped,
                "event_id": self.event_id,
                "exit_code": self.exit_code,
                "exit_signal": self.exit_signal,
                "expected_state": self.expected_state.value,
                "expected_state_version": self.expected_state_version,
                "operation_id": self.operation_id,
                "output_finalized": self.output_finalized,
                "reason_code": self.reason_code,
                "recorded_at": canonical_timestamp(self.recorded_at),
                "target_state": self.target_state.value,
                "terminal_evidence_sha256": self.terminal_evidence_sha256,
                "terminal_reason": self.terminal_reason,
            }
        )


@dataclass(frozen=True, slots=True)
class CancelRoutingResult:
    disposition: CancelRoutingDisposition
    acknowledged_cancel_generation: int
    evidence_generation: int
    snapshot: ExecutorSnapshot | None
    no_accept_reference: str | None = None

    def __post_init__(self) -> None:
        if self.acknowledged_cancel_generation < 1 or self.evidence_generation < 1:
            raise ExecutionError("cancel routing generations must be positive")
        if self.disposition is CancelRoutingDisposition.ACCEPTED_EXECUTION:
            if self.snapshot is None or self.no_accept_reference is not None:
                raise ExecutionError("accepted cancel routing lacks exact snapshot")
        elif self.disposition is CancelRoutingDisposition.NO_ACCEPT_PROVEN:
            if self.snapshot is not None or self.no_accept_reference is None:
                raise ExecutionError("no-accept cancel routing lacks exact seal")
            validate_identifier(self.no_accept_reference, name="no_accept_reference")
        elif self.snapshot is not None or self.no_accept_reference is not None:
            raise ExecutionError("pending cancel routing cannot carry terminal evidence")


@dataclass(frozen=True, slots=True)
class NoAcceptSealResult:
    disposition: ExecutionStartDisposition
    acknowledged_cancel_generation: int
    evidence_generation: int
    snapshot: ExecutorSnapshot | None
    seal_reference: str | None
    executor_reference: str | None
    receipt_sha256: str

    def __post_init__(self) -> None:
        if self.acknowledged_cancel_generation < 0 or self.evidence_generation < 1:
            raise ExecutionError("no-accept result generations are invalid")
        validate_sha256(self.receipt_sha256, name="receipt_sha256")
        if self.disposition is ExecutionStartDisposition.ACCEPTED_EXECUTION:
            if (
                self.snapshot is None
                or self.seal_reference is not None
                or self.executor_reference is None
            ):
                raise ExecutionError("accepted seal result lacks exact execution")
            validate_identifier(self.executor_reference, name="executor_reference")
        else:
            if (
                self.snapshot is not None
                or self.seal_reference is None
                or self.executor_reference is not None
            ):
                raise ExecutionError("no-accept seal result lacks exact reference")
            validate_identifier(self.seal_reference, name="seal_reference")


@dataclass(frozen=True, slots=True)
class ExecutorCancelReceipt:
    acknowledged_cancel_generation: int
    disposition: CancelDisposition
    evidence_generation: int
    execution_id: str | None
    receipt_sha256: str

    def __post_init__(self) -> None:
        if self.acknowledged_cancel_generation < 1 or self.evidence_generation < 1:
            raise ExecutionError("cancel receipt generations must be positive")
        validate_sha256(self.receipt_sha256, name="receipt_sha256")
        if self.execution_id is not None:
            validate_identifier(self.execution_id, name="execution_id")


@dataclass(frozen=True, slots=True)
class ExecutorOutputChunk:
    operation_id: str
    execution_id: str
    stream: OutputStream
    offset: int
    next_offset: int
    data: bytes
    eof: bool
    availability: OutputAvailability
    stream_sha256: str | None

    def __post_init__(self) -> None:
        validate_identifier(self.operation_id, name="operation_id")
        validate_identifier(self.execution_id, name="execution_id")
        if self.offset < 0 or self.next_offset != self.offset + len(self.data):
            raise ExecutionError("output cursor is inconsistent")
        if len(self.data) > MAX_OUTPUT_CHUNK_BYTES:
            raise ExecutionError("output chunk exceeds the reviewed limit")
        if self.stream_sha256 is not None:
            validate_sha256(self.stream_sha256, name="stream_sha256")
        if self.availability is OutputAvailability.EXPIRED and self.data:
            raise ExecutionError("expired output cannot return retained bytes")


def build_execution_ticket(
    *,
    ticket_id: str,
    operation_id: str,
    controller_identity_sha256: str,
    controller_epoch: int,
    device_id: str,
    device_epoch: int,
    development_session_id: str,
    development_session_state_version: int,
    development_session_closure_sha256: str,
    command_profile_id: str,
    workspace_id: str,
    workspace_profile_sha256: str,
    workspace_root_identity_sha256: str,
    workspace_mount_identity_sha256: str,
    workspace_fence_version: int,
    executable_path: str,
    executable_identity_sha256: str,
    argv: Sequence[object],
    cwd_relative: str,
    environment: Mapping[object, object],
    inline_stdin: bytes | None,
    stdin_reference_sha256: str | None,
    workspace_script_sha256: str | None,
    policy_sha256: str,
    resource_plan: ResourcePlan,
    mount_plan_id: str,
    mount_plan_sha256: str,
    sandbox_profile_id: str,
    sandbox_plan_sha256: str,
    process_isolation_profile_id: str,
    process_isolation_plan_sha256: str,
    network_profile_id: str,
    network_plan_sha256: str,
    listener_exposure: str,
    admission_record_id: str,
    issued_at: datetime,
    expires_at: datetime,
    boot_id_digest: str,
    monotonic_deadline_ns: int,
    single_use_nonce: str,
) -> ExecutionTicket:
    """Build one ticket while deriving every content digest and the final ticket digest."""

    normalized_argv = normalize_argv(argv)
    normalized_environment = normalize_environment(environment)
    normalized_argv_sha256 = argv_sha256(normalized_argv)
    normalized_environment_sha256 = environment_sha256(normalized_environment)
    normalized_stdin_sha256 = (
        None if inline_stdin is None else hashlib.sha256(inline_stdin).hexdigest()
    )
    normalized_cwd_sha256 = canonical_sha256(cwd_relative)
    digest_document = {
        "admission_record_id": admission_record_id,
        "argv": list(normalized_argv),
        "argv_sha256": normalized_argv_sha256,
        "boot_id_digest": boot_id_digest,
        "command_profile_id": command_profile_id,
        "controller_epoch": controller_epoch,
        "controller_identity_sha256": controller_identity_sha256,
        "cwd_relative": cwd_relative,
        "cwd_sha256": normalized_cwd_sha256,
        "development_session_closure_sha256": development_session_closure_sha256,
        "development_session_id": development_session_id,
        "development_session_state_version": development_session_state_version,
        "device_epoch": device_epoch,
        "device_id": device_id,
        "environment": [[name, value] for name, value in normalized_environment],
        "environment_sha256": normalized_environment_sha256,
        "executable_identity_sha256": executable_identity_sha256,
        "executable_path": executable_path,
        "expires_at": canonical_timestamp(expires_at),
        "inline_stdin_base64": (
            None if inline_stdin is None else base64.b64encode(inline_stdin).decode("ascii")
        ),
        "issued_at": canonical_timestamp(issued_at),
        "monotonic_deadline_ns": monotonic_deadline_ns,
        "mount_plan_id": mount_plan_id,
        "mount_plan_sha256": mount_plan_sha256,
        "network_profile_id": network_profile_id,
        "network_plan_sha256": network_plan_sha256,
        "operation_id": operation_id,
        "policy_sha256": policy_sha256,
        "process_isolation_plan_sha256": process_isolation_plan_sha256,
        "process_isolation_profile_id": process_isolation_profile_id,
        "resource_plan": resource_plan.to_wire(),
        "resource_plan_sha256": resource_plan.sha256,
        "sandbox_profile_id": sandbox_profile_id,
        "sandbox_plan_sha256": sandbox_plan_sha256,
        "single_use_nonce": single_use_nonce,
        "stdin_sha256": normalized_stdin_sha256,
        "stdin_reference_sha256": stdin_reference_sha256,
        "ticket_id": ticket_id,
        "listener_exposure": listener_exposure,
        "workspace_fence_version": workspace_fence_version,
        "workspace_id": workspace_id,
        "workspace_mount_identity_sha256": workspace_mount_identity_sha256,
        "workspace_profile_sha256": workspace_profile_sha256,
        "workspace_root_identity_sha256": workspace_root_identity_sha256,
        "workspace_script_sha256": workspace_script_sha256,
    }
    return ExecutionTicket(
        ticket_id=ticket_id,
        operation_id=operation_id,
        ticket_sha256=canonical_sha256(digest_document),
        controller_identity_sha256=controller_identity_sha256,
        controller_epoch=controller_epoch,
        device_id=device_id,
        device_epoch=device_epoch,
        development_session_id=development_session_id,
        development_session_state_version=development_session_state_version,
        development_session_closure_sha256=development_session_closure_sha256,
        command_profile_id=command_profile_id,
        workspace_id=workspace_id,
        workspace_profile_sha256=workspace_profile_sha256,
        workspace_root_identity_sha256=workspace_root_identity_sha256,
        workspace_mount_identity_sha256=workspace_mount_identity_sha256,
        workspace_fence_version=workspace_fence_version,
        executable_path=executable_path,
        executable_identity_sha256=executable_identity_sha256,
        argv=normalized_argv,
        argv_sha256=normalized_argv_sha256,
        cwd_relative=cwd_relative,
        cwd_sha256=normalized_cwd_sha256,
        environment=normalized_environment,
        environment_sha256=normalized_environment_sha256,
        inline_stdin=inline_stdin,
        stdin_sha256=normalized_stdin_sha256,
        stdin_reference_sha256=stdin_reference_sha256,
        workspace_script_sha256=workspace_script_sha256,
        policy_sha256=policy_sha256,
        resource_plan=resource_plan,
        resource_plan_sha256=resource_plan.sha256,
        mount_plan_id=mount_plan_id,
        mount_plan_sha256=mount_plan_sha256,
        sandbox_profile_id=sandbox_profile_id,
        sandbox_plan_sha256=sandbox_plan_sha256,
        process_isolation_profile_id=process_isolation_profile_id,
        process_isolation_plan_sha256=process_isolation_plan_sha256,
        network_profile_id=network_profile_id,
        network_plan_sha256=network_plan_sha256,
        listener_exposure=listener_exposure,
        admission_record_id=admission_record_id,
        issued_at=issued_at,
        expires_at=expires_at,
        boot_id_digest=boot_id_digest,
        monotonic_deadline_ns=monotonic_deadline_ns,
        single_use_nonce=single_use_nonce,
    )


def ticket_correlation_sha256(ticket: ExecutionTicket) -> str:
    """Digest immutable application/executor correlation without retaining raw authority."""

    return canonical_sha256(
        {
            "admission_record_id": ticket.admission_record_id,
            "argv_sha256": ticket.argv_sha256,
            "command_profile_id": ticket.command_profile_id,
            "controller_epoch": ticket.controller_epoch,
            "cwd_sha256": ticket.cwd_sha256,
            "development_session_closure_sha256": ticket.development_session_closure_sha256,
            "development_session_id": ticket.development_session_id,
            "development_session_state_version": ticket.development_session_state_version,
            "device_epoch": ticket.device_epoch,
            "environment_sha256": ticket.environment_sha256,
            "executable_identity_sha256": ticket.executable_identity_sha256,
            "mount_plan_sha256": ticket.mount_plan_sha256,
            "network_plan_sha256": ticket.network_plan_sha256,
            "policy_sha256": ticket.policy_sha256,
            "process_isolation_plan_sha256": ticket.process_isolation_plan_sha256,
            "resource_plan_sha256": ticket.resource_plan_sha256,
            "sandbox_plan_sha256": ticket.sandbox_plan_sha256,
            "stdin_reference_sha256": ticket.stdin_reference_sha256,
            "stdin_sha256": ticket.stdin_sha256,
            "workspace_fence_version": ticket.workspace_fence_version,
            "workspace_id": ticket.workspace_id,
            "workspace_mount_identity_sha256": ticket.workspace_mount_identity_sha256,
            "workspace_profile_sha256": ticket.workspace_profile_sha256,
            "workspace_root_identity_sha256": ticket.workspace_root_identity_sha256,
            "workspace_script_sha256": ticket.workspace_script_sha256,
        }
    )


def normalize_argv(values: Sequence[object]) -> tuple[str, ...]:
    if not 1 <= len(values) <= MAX_ARGV_ITEMS:
        raise ExecutionError("argv item count is outside the reviewed limit")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or "\x00" in value or "\r" in value or "\n" in value:
            raise ExecutionError("argv contains an invalid value")
        if unicodedata.normalize("NFC", value) != value:
            raise ExecutionError("argv must already be NFC-normalized")
        if len(value.encode("utf-8")) > MAX_ARGUMENT_BYTES:
            raise ExecutionError("argv item exceeds the reviewed limit")
        result.append(value)
    return tuple(result)


_EXECUTOR_TRANSITIONS: Final = frozenset(
    {
        (ExecutorEvidenceState.ACCEPTED, ExecutorEvidenceState.LAUNCH_PREPARING),
        (ExecutorEvidenceState.ACCEPTED, ExecutorEvidenceState.CANCEL_REQUESTED),
        (ExecutorEvidenceState.ACCEPTED, ExecutorEvidenceState.EXECUTOR_UNCERTAIN),
        (ExecutorEvidenceState.LAUNCH_PREPARING, ExecutorEvidenceState.LAUNCH_COMMITTED),
        (ExecutorEvidenceState.LAUNCH_PREPARING, ExecutorEvidenceState.CANCEL_REQUESTED),
        (ExecutorEvidenceState.LAUNCH_PREPARING, ExecutorEvidenceState.EXECUTOR_UNCERTAIN),
        (ExecutorEvidenceState.LAUNCH_COMMITTED, ExecutorEvidenceState.RUNNING),
        (ExecutorEvidenceState.LAUNCH_COMMITTED, ExecutorEvidenceState.CANCEL_REQUESTED),
        (ExecutorEvidenceState.LAUNCH_COMMITTED, ExecutorEvidenceState.EXITED),
        (ExecutorEvidenceState.LAUNCH_COMMITTED, ExecutorEvidenceState.EXECUTOR_UNCERTAIN),
        (ExecutorEvidenceState.RUNNING, ExecutorEvidenceState.CANCEL_REQUESTED),
        (ExecutorEvidenceState.RUNNING, ExecutorEvidenceState.EXITED),
        (ExecutorEvidenceState.RUNNING, ExecutorEvidenceState.EXECUTOR_UNCERTAIN),
        (ExecutorEvidenceState.CANCEL_REQUESTED, ExecutorEvidenceState.CANCELLING),
        (ExecutorEvidenceState.CANCEL_REQUESTED, ExecutorEvidenceState.EXITED),
        (ExecutorEvidenceState.CANCEL_REQUESTED, ExecutorEvidenceState.EXECUTOR_UNCERTAIN),
        (ExecutorEvidenceState.CANCELLING, ExecutorEvidenceState.EXITED),
        (ExecutorEvidenceState.CANCELLING, ExecutorEvidenceState.EXECUTOR_UNCERTAIN),
        (ExecutorEvidenceState.EXITED, ExecutorEvidenceState.CLEANUP_PENDING),
        (ExecutorEvidenceState.EXITED, ExecutorEvidenceState.EXECUTOR_UNCERTAIN),
        (ExecutorEvidenceState.CLEANUP_PENDING, ExecutorEvidenceState.CLOSED),
        (ExecutorEvidenceState.CLEANUP_PENDING, ExecutorEvidenceState.EXECUTOR_UNCERTAIN),
        (ExecutorEvidenceState.EXECUTOR_UNCERTAIN, ExecutorEvidenceState.EXITED),
        (ExecutorEvidenceState.EXECUTOR_UNCERTAIN, ExecutorEvidenceState.CLEANUP_PENDING),
        (ExecutorEvidenceState.EXECUTOR_UNCERTAIN, ExecutorEvidenceState.CLOSED),
    }
)


def require_executor_transition(
    current: ExecutorEvidenceState,
    target: ExecutorEvidenceState,
) -> None:
    if (current, target) not in _EXECUTOR_TRANSITIONS:
        raise ExecutionError(f"illegal executor evidence transition: {current} -> {target}")


def normalize_environment(values: Mapping[object, object]) -> tuple[tuple[str, str], ...]:
    if len(values) > MAX_ENVIRONMENT_ITEMS:
        raise ExecutionError("environment item count exceeds the reviewed limit")
    result: list[tuple[str, str]] = []
    for name, value in values.items():
        if not isinstance(name, str) or _ENVIRONMENT_NAME.fullmatch(name) is None:
            raise ExecutionError("environment name is not allowlist-shaped")
        if name in _FORBIDDEN_ENVIRONMENT_NAMES or name.startswith(_FORBIDDEN_ENVIRONMENT_PREFIXES):
            raise ExecutionError("environment name is not permitted in a command domain")
        if not isinstance(value, str) or any(
            character in value for character in ("\x00", "\r", "\n")
        ):
            raise ExecutionError("environment value is invalid")
        if unicodedata.normalize("NFC", value) != value:
            raise ExecutionError("environment value must already be NFC-normalized")
        if len(value.encode("utf-8")) > MAX_ENVIRONMENT_VALUE_BYTES:
            raise ExecutionError("environment value exceeds the reviewed limit")
        result.append((name, value))
    return tuple(sorted(result))


def normalize_relative_cwd(value: str) -> str:
    if value == ".":
        return value
    if not value or value.startswith(("/", "\\")) or "\\" in value:
        raise ExecutionError("command cwd must be relative POSIX form")
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise ExecutionError("command cwd contains a forbidden character")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts) or len(parts) > 64:
        raise ExecutionError("command cwd components are invalid")
    if len(value.encode("utf-8")) > 4_096:
        raise ExecutionError("command cwd exceeds the reviewed limit")
    return value


def validate_executable_path(value: str) -> None:
    if _ABSOLUTE_EXECUTABLE.fullmatch(value) is None or "/../" in value or "/./" in value:
        raise ExecutionError("executable path must be canonical absolute form")


def argv_sha256(values: Sequence[str]) -> str:
    return canonical_sha256(list(values))


def environment_sha256(values: Sequence[tuple[str, str]]) -> str:
    return canonical_sha256([[name, value] for name, value in values])


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ExecutionError("timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def validate_identifier(value: str, *, name: str) -> None:
    if _IDENTIFIER.fullmatch(value) is None:
        raise ExecutionError(f"{name} is invalid")


def validate_sha256(value: str, *, name: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ExecutionError(f"{name} must be a lowercase SHA-256 digest")


def _require_string(value: Mapping[str, object], name: str) -> str:
    result = value[name]
    if not isinstance(result, str):
        raise ExecutionError(f"{name} must be text")
    return result


def _optional_string(value: Mapping[str, object], name: str) -> str | None:
    result = value[name]
    if result is not None and not isinstance(result, str):
        raise ExecutionError(f"{name} must be text or null")
    return result


def _require_int(value: Mapping[str, object], name: str) -> int:
    result = value[name]
    if isinstance(result, bool) or not isinstance(result, int):
        raise ExecutionError(f"{name} must be an integer")
    return result


def _require_datetime(value: Mapping[str, object], name: str) -> datetime:
    result = value[name]
    if not isinstance(result, datetime):
        raise ExecutionError(f"{name} must be a datetime")
    return result


__all__ = [
    "EXECUTOR_PROTOCOL_ID",
    "EXECUTOR_PROTOCOL_VERSION",
    "MAX_EXECUTOR_FRAME_BYTES",
    "MAX_INLINE_STDIN_BYTES",
    "MAX_OUTPUT_CHUNK_BYTES",
    "CancelDisposition",
    "CancelRoutingDisposition",
    "CancelRoutingResult",
    "DispatchCommitKnowledge",
    "ExecutionConflictError",
    "ExecutionError",
    "ExecutionStartDisposition",
    "ExecutionStartReceipt",
    "ExecutionTicket",
    "ExecutorCancelReceipt",
    "ExecutorEvidenceState",
    "ExecutorOutputChunk",
    "ExecutorSnapshot",
    "NoAcceptSealResult",
    "OutputAvailability",
    "OutputStream",
    "ResourcePlan",
    "argv_sha256",
    "build_execution_ticket",
    "canonical_sha256",
    "environment_sha256",
    "normalize_argv",
    "normalize_environment",
    "normalize_relative_cwd",
    "validate_identifier",
    "validate_sha256",
]
