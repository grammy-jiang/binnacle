"""Evidence-independent Phase 8 Git identities, profiles, plans, and result types."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final

_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_HEX_RE: Final = re.compile(r"[0-9a-f]+\Z")
_PROFILE_ID_RE: Final = re.compile(r"[a-z][a-z0-9._-]{0,95}\Z")
_HOST_RE: Final = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
)
_REMOTE_PATH_RE: Final = re.compile(r"[A-Za-z0-9._/-]{1,512}\Z")
_SERVICE_USER_RE: Final = re.compile(r"[a-z_][a-z0-9_-]{0,31}\Z")
_FORBIDDEN_REF_CHARACTERS: Final = frozenset(" ~^:?*[\\")
_MAX_REF_BYTES: Final = 255
_MAX_ARGUMENTS: Final = 256
_MAX_ARGUMENT_BYTES: Final = 16_384
_ALLOWED_ENVIRONMENT_NAMES: Final = frozenset(
    {
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_CONFIG_SYSTEM",
        "GIT_EXEC_PATH",
        "GIT_INDEX_FILE",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_OBJECT_DIRECTORY",
        "GIT_OPTIONAL_LOCKS",
        "GIT_PAGER",
        "GIT_PROTOCOL_FROM_USER",
        "GIT_TERMINAL_PROMPT",
        "HOME",
        "LC_ALL",
        "PATH",
        "XDG_CONFIG_HOME",
    }
)


class GitError(ValueError):
    """A Phase 8 Git value or state violates its closed contract."""


class GitObjectAlgorithm(StrEnum):
    SHA1 = "sha1"
    SHA256 = "sha256"

    @property
    def hexadecimal_length(self) -> int:
        return 40 if self is GitObjectAlgorithm.SHA1 else 64


@dataclass(frozen=True, slots=True)
class GitObjectId:
    """One full algorithm-tagged Git object identifier."""

    algorithm: GitObjectAlgorithm
    hex: str

    def __post_init__(self) -> None:
        if (
            len(self.hex) != self.algorithm.hexadecimal_length
            or _HEX_RE.fullmatch(self.hex) is None
        ):
            raise GitError("Git object ID is not full lowercase hexadecimal form")

    def to_wire(self) -> dict[str, str]:
        return {"algorithm": self.algorithm.value, "hex": self.hex}

    @classmethod
    def from_wire(cls, value: object) -> GitObjectId:
        if not isinstance(value, dict) or set(value) != {"algorithm", "hex"}:
            raise GitError("Git object ID fields are not exact")
        algorithm = value.get("algorithm")
        hexadecimal = value.get("hex")
        if not isinstance(algorithm, str) or not isinstance(hexadecimal, str):
            raise GitError("Git object ID fields are invalid")
        try:
            return cls(GitObjectAlgorithm(algorithm), hexadecimal)
        except ValueError as exc:
            raise GitError("Git object algorithm is unsupported") from exc


class GitOperationKind(StrEnum):
    STATUS = "status"
    DIFF = "diff"
    BRANCH_CREATE = "branch_create"
    SWITCH = "switch"
    COMMIT = "commit"
    FETCH = "fetch"
    PULL = "pull"
    PUSH = "push"


class GitCoordinationMode(StrEnum):
    CONTENT_READ = "content_read"
    CHANGE = "change"


class GitCredentialAction(StrEnum):
    NONE = "none"
    COMMIT_SIGN = "commit_sign"
    FETCH = "fetch"
    PUSH = "push"


class MainIndexPublicationState(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    COMPLETE = "complete"
    UNCERTAIN = "uncertain"


class GitStatusEntryKind(StrEnum):
    ORDINARY = "ordinary"
    RENAMED_OR_COPIED = "renamed_or_copied"
    UNMERGED = "unmerged"
    UNTRACKED = "untracked"
    IGNORED = "ignored"


class GitDiffMode(StrEnum):
    WORKTREE_TO_INDEX = "worktree_to_index"
    INDEX_TO_HEAD = "index_to_head"
    OBJECT_TO_OBJECT = "object_to_object"


class GitHeadState(StrEnum):
    SYMBOLIC = "symbolic"
    DETACHED = "detached"
    UNBORN = "unborn"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ProtectedRemoteProfile:
    """Owner-controlled remote authority; repository config cannot replace it."""

    profile_id: str
    version: str
    scheme: str
    host: str
    port: int
    repository_path: str
    service_user: str
    allowed_destination_prefix: str
    known_hosts_sha256: str
    credential_reference_sha256: str
    public_fingerprint: str

    def __post_init__(self) -> None:
        _require_profile_id(self.profile_id, "remote profile")
        _require_version(self.version)
        if self.scheme != "ssh":
            raise GitError("Bootstrap remote scheme must be ssh")
        if self.host != self.host.lower() or _HOST_RE.fullmatch(self.host) is None:
            raise GitError("protected remote host is invalid")
        if not 1 <= self.port <= 65_535:
            raise GitError("protected remote port is invalid")
        if (
            _REMOTE_PATH_RE.fullmatch(self.repository_path) is None
            or self.repository_path.startswith("/")
            or "//" in self.repository_path
            or ".." in PurePosixPath(self.repository_path).parts
        ):
            raise GitError("protected remote repository path is invalid")
        if _SERVICE_USER_RE.fullmatch(self.service_user) is None:
            raise GitError("protected remote service user is invalid")
        _require_ref_prefix(self.allowed_destination_prefix)
        _require_sha256(self.known_hosts_sha256, "known-hosts digest")
        _require_sha256(self.credential_reference_sha256, "credential reference")
        if (
            not self.public_fingerprint
            or len(self.public_fingerprint) > 160
            or not self.public_fingerprint.isascii()
            or any(
                ord(character) < 33 or ord(character) > 126 for character in self.public_fingerprint
            )
        ):
            raise GitError("credential public fingerprint is invalid")


@dataclass(frozen=True, slots=True)
class RegisteredGitRepositoryProfile:
    """Protected exact repository profile, never repository-controlled data."""

    repository_profile_id: str
    version: str
    workspace_id: str
    workspace_profile_sha256: str
    workspace_root: str
    workspace_root_identity_sha256: str
    workspace_mount_identity_sha256: str
    git_directory: str
    git_directory_identity_sha256: str
    common_directory: str
    common_directory_identity_sha256: str
    object_format: GitObjectAlgorithm
    allowed_branch_prefix: str
    protected_refs: tuple[str, ...]
    git_executable: str
    git_executable_sha256: str
    git_exec_path: str
    empty_home: str
    empty_hooks_directory: str
    git_version_profile: str
    author_name: str
    author_email: str
    committer_name: str
    committer_email: str
    signing_reference_sha256: str
    signing_public_fingerprint: str
    remote: ProtectedRemoteProfile
    safety_policy_version: str
    maximum_status_entries: int = 2_000
    maximum_diff_bytes: int = 2_000_000
    maximum_object_bytes: int = 128_000_000
    maximum_operation_seconds: int = 600
    active: bool = False

    def __post_init__(self) -> None:
        _require_profile_id(self.repository_profile_id, "repository profile")
        _require_version(self.version)
        if not self.workspace_id or len(self.workspace_id) > 160:
            raise GitError("workspace identity is invalid")
        for name, value in (
            ("workspace profile", self.workspace_profile_sha256),
            ("workspace root identity", self.workspace_root_identity_sha256),
            ("workspace mount identity", self.workspace_mount_identity_sha256),
            ("Git directory identity", self.git_directory_identity_sha256),
            ("Git common-directory identity", self.common_directory_identity_sha256),
            ("Git executable identity", self.git_executable_sha256),
            ("signing reference", self.signing_reference_sha256),
        ):
            _require_sha256(value, name)
        for name, value in (
            ("workspace root", self.workspace_root),
            ("Git directory", self.git_directory),
            ("Git common directory", self.common_directory),
            ("Git executable", self.git_executable),
            ("Git exec path", self.git_exec_path),
            ("empty Git home", self.empty_home),
            ("empty hooks directory", self.empty_hooks_directory),
        ):
            _require_absolute_path(value, name)
        root = PurePosixPath(self.workspace_root)
        git_directory = PurePosixPath(self.git_directory)
        common_directory = PurePosixPath(self.common_directory)
        if git_directory != root / ".git" or common_directory != git_directory:
            raise GitError("Bootstrap supports only one normal in-workspace Git directory")
        _require_ref_prefix(self.allowed_branch_prefix)
        if (
            not self.protected_refs
            or tuple(sorted(set(self.protected_refs))) != self.protected_refs
        ):
            raise GitError("protected refs must be unique and sorted")
        for ref in self.protected_refs:
            require_full_local_branch_ref(ref)
        if "refs/heads/master" not in self.protected_refs:
            raise GitError("protected refs must include master")
        _require_version(self.git_version_profile)
        _require_version(self.safety_policy_version)
        for identity in (
            self.author_name,
            self.author_email,
            self.committer_name,
            self.committer_email,
            self.signing_public_fingerprint,
        ):
            if (
                not identity
                or len(identity.encode("utf-8")) > 320
                or any(ord(character) < 32 or ord(character) == 127 for character in identity)
            ):
                raise GitError("protected Git identity is invalid")
        if not 1 <= self.maximum_status_entries <= 20_000:
            raise GitError("status entry ceiling is invalid")
        if not 1_024 <= self.maximum_diff_bytes <= 20_000_000:
            raise GitError("diff byte ceiling is invalid")
        if not 1_048_576 <= self.maximum_object_bytes <= 2_000_000_000:
            raise GitError("object byte ceiling is invalid")
        if not 1 <= self.maximum_operation_seconds <= 3_600:
            raise GitError("Git operation time ceiling is invalid")

    @property
    def profile_sha256(self) -> str:
        return canonical_sha256(asdict(self))

    def require_branch_allowed(self, branch: str) -> str:
        full_ref = normalize_development_branch(branch, allowed_prefix=self.allowed_branch_prefix)
        if full_ref in self.protected_refs:
            raise GitError("protected branch is not a normal development target")
        if not full_ref.startswith(self.allowed_branch_prefix):
            raise GitError("branch is outside the registered namespace")
        return full_ref


@dataclass(frozen=True, slots=True)
class GitStatusEntry:
    kind: GitStatusEntryKind
    index_status: str
    worktree_status: str
    path: str
    original_path: str | None = None

    def __post_init__(self) -> None:
        if len(self.index_status) != 1 or len(self.worktree_status) != 1:
            raise GitError("Git status codes must be one character")
        for value in (self.index_status, self.worktree_status):
            if value not in ". MTADRCU?!":
                raise GitError("Git status code is unsupported")
        _require_repository_path(self.path)
        renamed = self.kind is GitStatusEntryKind.RENAMED_OR_COPIED
        if renamed != (self.original_path is not None):
            raise GitError("Git status rename shape is contradictory")
        if self.original_path is not None:
            _require_repository_path(self.original_path)


@dataclass(frozen=True, slots=True)
class GitStatusResult:
    object_format: GitObjectAlgorithm
    head_state: GitHeadState
    head_ref: str | None
    head_oid: GitObjectId | None
    upstream_ref: str | None
    ahead: int | None
    behind: int | None
    entries: tuple[GitStatusEntry, ...]
    complete: bool
    raw_sha256: str

    def __post_init__(self) -> None:
        if self.head_ref is not None:
            require_full_local_branch_ref(self.head_ref)
        _require_head_shape(self.head_state, self.head_ref, self.head_oid, self.complete)
        if self.head_oid is not None and self.head_oid.algorithm is not self.object_format:
            raise GitError("Git status HEAD object format conflicts with repository")
        if self.upstream_ref is not None:
            _require_ref_name(self.upstream_ref)
        if (self.ahead is None) != (self.behind is None):
            raise GitError("Git status ahead/behind facts are incomplete")
        if self.ahead is not None and (self.ahead < 0 or (self.behind or 0) < 0):
            raise GitError("Git status ahead/behind facts cannot be negative")
        _require_sha256(self.raw_sha256, "Git status output")

    @property
    def status_sha256(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True, slots=True)
class GitDiffResult:
    mode: GitDiffMode
    byte_count: int
    line_count: int
    file_count: int
    binary_file_count: int
    truncated: bool
    raw_sha256: str

    def __post_init__(self) -> None:
        if min(self.byte_count, self.line_count, self.file_count, self.binary_file_count) < 0:
            raise GitError("Git diff counters cannot be negative")
        if self.binary_file_count > self.file_count:
            raise GitError("Git diff binary count exceeds file count")
        _require_sha256(self.raw_sha256, "Git diff output")

    @property
    def result_sha256(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True, slots=True)
class GitRepositorySnapshot:
    """Bounded exact observation used for staleness and final revalidation."""

    repository_profile_sha256: str
    workspace_root_identity_sha256: str
    workspace_mount_identity_sha256: str
    git_directory_identity_sha256: str
    common_directory_identity_sha256: str
    object_format: GitObjectAlgorithm
    head_state: GitHeadState
    head_ref: str | None
    head_oid: GitObjectId | None
    index_tree_oid: GitObjectId | None
    index_sha256: str
    worktree_status_sha256: str
    repository_safety_sha256: str
    staged_entries: int
    unstaged_entries: int
    untracked_entries: int
    unmerged_entries: int
    lock_files: tuple[str, ...]
    in_progress_operations: tuple[str, ...]
    complete: bool
    captured_at: datetime

    def __post_init__(self) -> None:
        for name, value in (
            ("repository profile", self.repository_profile_sha256),
            ("workspace root identity", self.workspace_root_identity_sha256),
            ("workspace mount identity", self.workspace_mount_identity_sha256),
            ("Git directory identity", self.git_directory_identity_sha256),
            ("Git common-directory identity", self.common_directory_identity_sha256),
            ("index", self.index_sha256),
            ("worktree status", self.worktree_status_sha256),
            ("repository safety", self.repository_safety_sha256),
        ):
            _require_sha256(value, name)
        if self.head_ref is not None:
            require_full_local_branch_ref(self.head_ref)
        _require_head_shape(self.head_state, self.head_ref, self.head_oid, self.complete)
        for oid in (self.head_oid, self.index_tree_oid):
            if oid is not None and oid.algorithm is not self.object_format:
                raise GitError("Git object format conflicts with repository snapshot")
        counts = (
            self.staged_entries,
            self.unstaged_entries,
            self.untracked_entries,
            self.unmerged_entries,
        )
        if any(value < 0 for value in counts):
            raise GitError("repository snapshot counts cannot be negative")
        if tuple(sorted(set(self.lock_files))) != self.lock_files:
            raise GitError("Git lock facts must be unique and sorted")
        if tuple(sorted(set(self.in_progress_operations))) != self.in_progress_operations:
            raise GitError("Git operation facts must be unique and sorted")
        if self.captured_at.tzinfo is None:
            raise GitError("repository snapshot time must be timezone-aware")

    @property
    def repository_state_binding_sha256(self) -> str:
        value = asdict(self)
        value["captured_at"] = canonical_timestamp(self.captured_at)
        return canonical_sha256(value)

    @property
    def is_clean(self) -> bool:
        return (
            self.complete
            and self.staged_entries == 0
            and self.unstaged_entries == 0
            and self.untracked_entries == 0
            and self.unmerged_entries == 0
            and not self.lock_files
            and not self.in_progress_operations
        )


@dataclass(frozen=True, slots=True)
class RepositorySafetyAssessment:
    safe: bool
    reason_codes: tuple[str, ...]
    repository_safety_sha256: str
    inspected_files: int
    inspected_bytes: int

    def __post_init__(self) -> None:
        if tuple(sorted(set(self.reason_codes))) != self.reason_codes:
            raise GitError("repository safety reasons must be unique and sorted")
        if self.safe == bool(self.reason_codes):
            raise GitError("repository safety outcome contradicts its reasons")
        _require_sha256(self.repository_safety_sha256, "repository safety")
        if self.inspected_files < 0 or self.inspected_bytes < 0:
            raise GitError("repository safety counters cannot be negative")


@dataclass(frozen=True, slots=True)
class GitReadPermit:
    request_id: str
    application_generation: int
    content_guard_epoch: int
    development_session_id: str
    development_session_state_version: int
    repository_profile_sha256: str
    repository_state_binding_sha256: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.request_id or len(self.request_id) > 160:
            raise GitError("Git read request identity is invalid")
        if (
            min(
                self.application_generation,
                self.content_guard_epoch,
                self.development_session_state_version,
            )
            < 1
        ):
            raise GitError("Git read generation facts must be positive")
        if not self.development_session_id:
            raise GitError("Git read session identity is invalid")
        _require_sha256(self.repository_profile_sha256, "repository profile")
        _require_sha256(self.repository_state_binding_sha256, "repository state binding")
        if self.expires_at.tzinfo is None:
            raise GitError("Git read permit expiry must be timezone-aware")

    @property
    def permit_sha256(self) -> str:
        value = asdict(self)
        value["expires_at"] = canonical_timestamp(self.expires_at)
        return canonical_sha256(value)


@dataclass(frozen=True, slots=True)
class GitExecutionPlan:
    """Closed, shell-free plan for one internal Phase 7 Git member."""

    operation: GitOperationKind
    executable: str
    argv: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]
    working_directory: str
    repository_profile_sha256: str
    repository_state_binding_sha256: str
    network_allowed: bool
    credential_action: GitCredentialAction
    credential_reference_sha256: str | None
    maximum_output_bytes: int
    timeout_seconds: int
    command_run_visible: bool = False

    def __post_init__(self) -> None:
        _require_absolute_path(self.executable, "Git executable")
        _require_absolute_path(self.working_directory, "Git working directory")
        if not self.argv or len(self.argv) > _MAX_ARGUMENTS:
            raise GitError("Git argv count is outside the reviewed limit")
        if sum(len(value.encode("utf-8")) for value in self.argv) > _MAX_ARGUMENT_BYTES:
            raise GitError("Git argv exceeds the reviewed byte limit")
        for value in self.argv:
            if not value or "\0" in value or "\n" in value:
                raise GitError("Git argv contains an invalid value")
        names = tuple(name for name, _ in self.environment)
        if names != tuple(sorted(set(names))):
            raise GitError("Git environment names must be unique and sorted")
        for name, value in self.environment:
            if name not in _ALLOWED_ENVIRONMENT_NAMES or "\0" in value or "\n" in value:
                raise GitError("Git environment is outside the closed allowlist")
        _require_sha256(self.repository_profile_sha256, "repository profile")
        _require_sha256(self.repository_state_binding_sha256, "repository state binding")
        if self.credential_action is GitCredentialAction.NONE:
            if self.credential_reference_sha256 is not None:
                raise GitError("credential-free plan carries credential authority")
        else:
            if self.credential_reference_sha256 is None:
                raise GitError("credential-bearing plan lacks an exact reference")
            _require_sha256(self.credential_reference_sha256, "credential reference")
        if self.credential_action is GitCredentialAction.COMMIT_SIGN and self.network_allowed:
            raise GitError("commit signing must be network denied")
        if self.operation in {GitOperationKind.STATUS, GitOperationKind.DIFF} and (
            self.network_allowed or self.credential_action is not GitCredentialAction.NONE
        ):
            raise GitError("read-only Git plan cannot receive network or credentials")
        if not 1_024 <= self.maximum_output_bytes <= 20_000_000:
            raise GitError("Git output ceiling is invalid")
        if not 1 <= self.timeout_seconds <= 3_600:
            raise GitError("Git timeout is invalid")
        if self.command_run_visible:
            raise GitError("internal semantic Git plan cannot be command-run visible")

    @property
    def plan_sha256(self) -> str:
        return canonical_sha256(asdict(self))


def normalize_development_branch(value: str, *, allowed_prefix: str) -> str:
    """Return one exact full local branch ref inside the protected namespace."""

    if unicodedata.normalize("NFC", value) != value or not value.isascii():
        raise GitError("branch name must be ASCII and NFC-normalized")
    full_ref = value if value.startswith("refs/heads/") else f"refs/heads/{value}"
    full_ref = require_full_local_branch_ref(full_ref)
    _require_ref_prefix(allowed_prefix)
    if not full_ref.startswith(allowed_prefix):
        raise GitError("branch is outside the registered namespace")
    return full_ref


def require_full_local_branch_ref(value: str) -> str:
    if not value.startswith("refs/heads/") or len(value.encode("ascii", "ignore")) > _MAX_REF_BYTES:
        raise GitError("local branch ref is invalid")
    if not value.isascii() or value.endswith(("/", ".", ".lock")):
        raise GitError("local branch ref is invalid")
    if "//" in value or ".." in value or "@{" in value:
        raise GitError("local branch ref is invalid")
    if any(
        character in _FORBIDDEN_REF_CHARACTERS or ord(character) < 32 or ord(character) == 127
        for character in value
    ):
        raise GitError("local branch ref is invalid")
    components = value.split("/")
    if any(
        not component
        or component in {".", ".."}
        or component.startswith(".")
        or component.endswith(".")
        or component.endswith(".lock")
        for component in components
    ):
        raise GitError("local branch ref is invalid")
    return value


def _require_ref_name(value: str) -> None:
    if not value.startswith("refs/"):
        raise GitError("Git ref name is not full form")
    suffix = value.removeprefix("refs/")
    require_full_local_branch_ref(f"refs/heads/{suffix}")


def _require_repository_path(value: str) -> None:
    if (
        not value
        or value.startswith(("/", "\\"))
        or "\\" in value
        or "\0" in value
        or "\r" in value
        or "\n" in value
        or unicodedata.normalize("NFC", value) != value
    ):
        raise GitError("Git repository path is invalid")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise GitError("Git repository path is invalid")
    if len(value.encode("utf-8")) > 4_096:
        raise GitError("Git repository path exceeds the reviewed bound")


def _require_head_shape(
    state: GitHeadState,
    head_ref: str | None,
    head_oid: GitObjectId | None,
    complete: bool,
) -> None:
    expected = {
        GitHeadState.SYMBOLIC: (True, True),
        GitHeadState.DETACHED: (False, True),
        GitHeadState.UNBORN: (True, False),
        GitHeadState.UNAVAILABLE: (False, False),
    }[state]
    if expected != (head_ref is not None, head_oid is not None):
        raise GitError("Git HEAD state has a contradictory shape")
    if state is GitHeadState.UNAVAILABLE and complete:
        raise GitError("complete Git state cannot omit HEAD")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=_json_default,
        ).encode("utf-8")
    ).hexdigest()


def canonical_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise GitError("timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _json_default(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return canonical_timestamp(value)
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"unsupported canonical Git value: {type(value)!r}")


def _require_profile_id(value: str, name: str) -> None:
    if _PROFILE_ID_RE.fullmatch(value) is None:
        raise GitError(f"{name} identity is invalid")


def _require_version(value: str) -> None:
    if _PROFILE_ID_RE.fullmatch(value) is None:
        raise GitError("profile version is invalid")


def _require_sha256(value: str, name: str) -> None:
    if _SHA256_RE.fullmatch(value) is None:
        raise GitError(f"{name} must be a lowercase SHA-256 digest")


def _require_absolute_path(value: str, name: str) -> None:
    path = PurePosixPath(value)
    if (
        not path.is_absolute()
        or str(path) != value
        or ".." in path.parts
        or "\0" in value
        or "\n" in value
    ):
        raise GitError(f"{name} must be canonical absolute POSIX form")


def _require_ref_prefix(value: str) -> None:
    if not value.endswith("/"):
        raise GitError("allowed branch prefix must end with a slash")
    require_full_local_branch_ref(f"{value}placeholder")


__all__ = [
    "GitCoordinationMode",
    "GitCredentialAction",
    "GitDiffMode",
    "GitDiffResult",
    "GitError",
    "GitExecutionPlan",
    "GitHeadState",
    "GitObjectAlgorithm",
    "GitObjectId",
    "GitOperationKind",
    "GitReadPermit",
    "GitRepositorySnapshot",
    "GitStatusEntry",
    "GitStatusEntryKind",
    "GitStatusResult",
    "MainIndexPublicationState",
    "ProtectedRemoteProfile",
    "RegisteredGitRepositoryProfile",
    "RepositorySafetyAssessment",
    "canonical_sha256",
    "normalize_development_branch",
    "require_full_local_branch_ref",
]
