"""Bounded, side-effect-free validation of repository-controlled Git surfaces."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass, field
from typing import Final

from binnacle.domain.git import (
    RegisteredGitRepositoryProfile,
    RepositorySafetyAssessment,
    canonical_sha256,
)

_SECTION_RE: Final = re.compile(r'^\[\s*([A-Za-z][A-Za-z0-9.-]*)(?:\s+"([^"\r\n]*)")?\s*\]$')
_KEY_RE: Final = re.compile(r"([A-Za-z][A-Za-z0-9.-]*)(?:\s*=\s*(.*))?$")
_ATTRIBUTE_HELPERS: Final = frozenset({"diff", "filter", "merge"})
_SAFE_CORE_KEYS: Final = frozenset(
    {
        "bare",
        "filemode",
        "ignorecase",
        "logallrefupdates",
        "precomposeunicode",
        "repositoryformatversion",
        "symlinks",
    }
)
_FORBIDDEN_EXACT_KEYS: Final = frozenset(
    {
        "core.alternaterefscommand",
        "core.askpass",
        "core.attributesfile",
        "core.editor",
        "core.excludesfile",
        "core.fsmonitor",
        "core.gitproxy",
        "core.hookspath",
        "core.pager",
        "core.sshcommand",
        "core.worktree",
        "diff.external",
        "gpg.program",
        "sequence.editor",
        "ssh.variant",
        "user.signingkey",
    }
)
_FORBIDDEN_PREFIXES: Final = (
    "alias.",
    "credential.",
    "filter.",
    "http.",
    "https.",
    "include.",
    "includeif.",
    "pager.",
    "protocol.",
    "submodule.",
    "url.",
)
_RELEVANT_WORKTREE_NAMES: Final = frozenset({".gitattributes", ".gitmodules", ".lfsconfig"})


@dataclass(slots=True)
class _Inspection:
    maximum_files: int
    maximum_bytes: int
    reasons: set[str] = field(default_factory=set)
    facts: list[tuple[str, str, int]] = field(default_factory=list)
    inspected_files: int = 0
    inspected_bytes: int = 0

    def add_file(self, relative_path: str, content: bytes) -> None:
        self.inspected_files += 1
        self.inspected_bytes += len(content)
        if self.inspected_files > self.maximum_files or self.inspected_bytes > self.maximum_bytes:
            self.reasons.add("inspection_limit")
            return
        self.facts.append((relative_path, hashlib.sha256(content).hexdigest(), len(content)))


@dataclass(frozen=True, slots=True)
class _DirectoryEntry:
    name: str
    is_symlink: bool
    is_directory: bool


class BoundedGitRepositoryProfileValidator:
    """Reject helper-bearing or indeterminate repository shapes without running Git."""

    def __init__(
        self,
        *,
        maximum_files: int = 512,
        maximum_bytes: int = 2_000_000,
        maximum_tree_entries: int = 20_000,
    ) -> None:
        if min(maximum_files, maximum_bytes, maximum_tree_entries) < 1:
            raise ValueError("Git validation limits must be positive")
        self._maximum_files = maximum_files
        self._maximum_bytes = maximum_bytes
        self._maximum_tree_entries = maximum_tree_entries

    def validate(
        self,
        profile: RegisteredGitRepositoryProfile,
    ) -> RepositorySafetyAssessment:
        inspection = _Inspection(self._maximum_files, self._maximum_bytes)
        try:
            root_fd = os.open(
                profile.workspace_root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
            )
        except OSError:
            inspection.reasons.add("repository_shape")
            return self._result(profile, inspection)

        try:
            self._inspect(root_fd, profile, inspection)
        except OSError:
            inspection.reasons.add("inspection_error")
        finally:
            os.close(root_fd)
        return self._result(profile, inspection)

    def _inspect(
        self,
        root_fd: int,
        profile: RegisteredGitRepositoryProfile,
        inspection: _Inspection,
    ) -> None:
        try:
            git_fd = os.open(
                ".git",
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=root_fd,
            )
        except OSError:
            inspection.reasons.add("repository_shape")
            return

        try:
            config = self._read_file(
                git_fd,
                ("config",),
                inspection,
                required=True,
                missing_reason="config_missing",
            )
            if config is not None:
                self._inspect_config(config, profile, inspection)

            worktree_config = self._read_file(
                git_fd,
                ("config.worktree",),
                inspection,
                required=False,
            )
            if worktree_config is not None:
                inspection.reasons.add("linked_worktrees_present")
                self._inspect_config(worktree_config, profile, inspection)

            info_attributes = self._read_file(
                git_fd,
                ("info", "attributes"),
                inspection,
                required=False,
            )
            if info_attributes is not None:
                self._inspect_repository_control_file(
                    ".gitattributes",
                    info_attributes,
                    inspection,
                )

            self._inspect_git_markers(git_fd, inspection)
            self._scan_worktree(root_fd, inspection)
        finally:
            os.close(git_fd)

    def _inspect_config(
        self,
        content: bytes,
        profile: RegisteredGitRepositoryProfile,
        inspection: _Inspection,
    ) -> None:
        try:
            text = content.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            inspection.reasons.add("config_malformed")
            return

        section: tuple[str, str | None] | None = None
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith(("#", ";")):
                continue
            section_match = _SECTION_RE.fullmatch(line)
            if section_match is not None:
                section = (section_match.group(1).lower(), section_match.group(2))
                if section[0] in {"include", "includeif"}:
                    inspection.reasons.add("forbidden_config")
                continue
            if section is None or (raw_line[:1].isspace() and "=" not in raw_line):
                inspection.reasons.add("config_malformed")
                continue
            key_match = _KEY_RE.fullmatch(line)
            if key_match is None:
                inspection.reasons.add("config_malformed")
                continue
            key = key_match.group(1).lower()
            value = (key_match.group(2) or "true").strip()
            self._classify_config(section, key, value, profile, inspection)

    def _classify_config(
        self,
        section: tuple[str, str | None],
        key: str,
        value: str,
        profile: RegisteredGitRepositoryProfile,
        inspection: _Inspection,
    ) -> None:
        section_name, subsection = section
        qualified_section = section_name if subsection is None else f"{section_name}.{subsection}"
        qualified_key = f"{qualified_section}.{key}".lower()
        if qualified_key in _FORBIDDEN_EXACT_KEYS or qualified_key.startswith(_FORBIDDEN_PREFIXES):
            inspection.reasons.add("forbidden_config")
            return

        if section_name == "core":
            if key not in _SAFE_CORE_KEYS:
                inspection.reasons.add("unsupported_config")
            elif key == "bare" and value.lower() not in {"false", "no", "off", "0"}:
                inspection.reasons.add("repository_shape")
            return

        if section_name == "extensions":
            if key == "objectformat":
                if value.lower() != profile.object_format.value:
                    inspection.reasons.add("object_format_mismatch")
            elif key == "worktreeconfig":
                if value.lower() not in {"false", "no", "off", "0"}:
                    inspection.reasons.add("linked_worktrees_present")
            elif key == "partialclone":
                inspection.reasons.add("promisor_repository")
            else:
                inspection.reasons.add("unsupported_config")
            return

        if section_name == "remote":
            if subsection is None:
                inspection.reasons.add("config_malformed")
            elif key in {"promisor", "partialclonefilter"}:
                inspection.reasons.add("promisor_repository")
            elif key == "url":
                if value != _protected_remote_url(profile):
                    inspection.reasons.add("remote_mismatch")
            elif key == "fetch":
                if value != f"+refs/heads/*:refs/remotes/{subsection}/*":
                    inspection.reasons.add("unsupported_config")
            else:
                inspection.reasons.add("forbidden_config")
            return

        if section_name == "branch":
            if (
                subsection is None
                or key not in {"merge", "remote"}
                or (key == "merge" and not value.startswith("refs/heads/"))
            ):
                inspection.reasons.add("unsupported_config")
            return

        if section_name in {"diff", "merge"}:
            inspection.reasons.add("forbidden_config")
            return
        inspection.reasons.add("unsupported_config")

    def _inspect_git_markers(self, git_fd: int, inspection: _Inspection) -> None:
        marker_files = {
            ("shallow",): "shallow_repository",
            ("info", "grafts"): "grafts_present",
            ("info", "sparse-checkout"): "sparse_repository",
            ("objects", "info", "alternates"): "alternate_object_store",
            ("objects", "info", "http-alternates"): "alternate_object_store",
        }
        for parts, reason in marker_files.items():
            content = self._read_file(git_fd, parts, inspection, required=False)
            if content is not None:
                inspection.reasons.add(reason)

        marker_directories = {
            ("modules",): "submodules_present",
            ("refs", "replace"): "replace_refs_present",
            ("worktrees",): "linked_worktrees_present",
        }
        for parts, reason in marker_directories.items():
            if self._directory_has_entries(git_fd, parts):
                inspection.reasons.add(reason)

        hooks = self._directory_entries(git_fd, ("hooks",), inspection)
        if hooks is not None and any(not entry.endswith(".sample") for entry in hooks):
            inspection.reasons.add("hooks_present")

    def _scan_worktree(self, root_fd: int, inspection: _Inspection) -> None:
        pending: list[tuple[tuple[str, ...], str]] = [((), "")]
        entries_seen = 0
        while pending:
            parts, relative_directory = pending.pop()
            directory_fd = self._open_directory(root_fd, parts)
            try:
                remaining_entries = self._maximum_tree_entries - entries_seen
                entries, overflow = _bounded_directory_entries(directory_fd, remaining_entries)
                if overflow:
                    inspection.reasons.add("inspection_limit")
                    return
                entries_seen += len(entries)
                for entry in entries:
                    if entry.name == ".git" and not relative_directory:
                        continue
                    relative_path = (
                        entry.name
                        if not relative_directory
                        else f"{relative_directory}/{entry.name}"
                    )
                    if entry.name in _RELEVANT_WORKTREE_NAMES:
                        if entry.is_symlink:
                            inspection.reasons.add("unsafe_attributes")
                            continue
                        content = self._read_file(
                            directory_fd,
                            (entry.name,),
                            inspection,
                            required=True,
                            fact_path=relative_path,
                        )
                        if content is not None:
                            self._inspect_repository_control_file(
                                entry.name,
                                content,
                                inspection,
                            )
                    elif entry.is_directory:
                        pending.append(((*parts, entry.name), relative_path))
            finally:
                os.close(directory_fd)

    @staticmethod
    def _open_directory(root_fd: int, parts: tuple[str, ...]) -> int:
        directory_fd = os.dup(root_fd)
        try:
            for part in parts:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                    dir_fd=directory_fd,
                )
                os.close(directory_fd)
                directory_fd = next_fd
        except BaseException:
            os.close(directory_fd)
            raise
        return directory_fd

    def _inspect_repository_control_file(
        self,
        name: str,
        content: bytes,
        inspection: _Inspection,
    ) -> None:
        if name in {".gitmodules", ".lfsconfig"}:
            if content.strip():
                inspection.reasons.add(
                    "submodules_present" if name == ".gitmodules" else "lfs_present"
                )
            return
        try:
            text = content.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            inspection.reasons.add("unsafe_attributes")
            return
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            attributes = stripped.split()[1:]
            if any(
                token.lstrip("-!").split("=", 1)[0].lower() in _ATTRIBUTE_HELPERS
                for token in attributes
            ):
                inspection.reasons.add("unsafe_attributes")

    def _read_file(
        self,
        parent_fd: int,
        parts: tuple[str, ...],
        inspection: _Inspection,
        *,
        required: bool,
        fact_path: str | None = None,
        missing_reason: str = "repository_shape",
    ) -> bytes | None:
        directory_fd = os.dup(parent_fd)
        try:
            for part in parts[:-1]:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                    dir_fd=directory_fd,
                )
                os.close(directory_fd)
                directory_fd = next_fd
            try:
                file_fd = os.open(
                    parts[-1],
                    os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                    dir_fd=directory_fd,
                )
            except FileNotFoundError:
                if required:
                    inspection.reasons.add(missing_reason)
                return None
            try:
                metadata = os.fstat(file_fd)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    inspection.reasons.add("repository_shape")
                    return None
                remaining = self._maximum_bytes - inspection.inspected_bytes
                if metadata.st_size > remaining:
                    inspection.reasons.add("inspection_limit")
                    return None
                content = _read_bounded(file_fd, metadata.st_size, remaining)
            finally:
                os.close(file_fd)
        except FileNotFoundError:
            if required:
                inspection.reasons.add(missing_reason)
            return None
        except OSError:
            inspection.reasons.add("repository_shape")
            return None
        finally:
            os.close(directory_fd)
        inspection.add_file(fact_path or "/".join((".git", *parts)), content)
        return content

    def _directory_entries(
        self,
        parent_fd: int,
        parts: tuple[str, ...],
        inspection: _Inspection,
    ) -> tuple[str, ...] | None:
        directory_fd = os.dup(parent_fd)
        try:
            for part in parts:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                    dir_fd=directory_fd,
                )
                os.close(directory_fd)
                directory_fd = next_fd
            entries, overflow = _bounded_directory_entries(
                directory_fd,
                self._maximum_tree_entries,
            )
            if overflow:
                inspection.reasons.add("inspection_limit")
            return tuple(entry.name for entry in entries)
        except FileNotFoundError:
            return None
        except OSError:
            return ("<unsafe>",)
        finally:
            os.close(directory_fd)

    def _directory_has_entries(self, parent_fd: int, parts: tuple[str, ...]) -> bool:
        directory_fd = os.dup(parent_fd)
        try:
            for part in parts:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                    dir_fd=directory_fd,
                )
                os.close(directory_fd)
                directory_fd = next_fd
            with os.scandir(directory_fd) as iterator:
                return next(iterator, None) is not None
        except FileNotFoundError:
            return False
        except OSError:
            return True
        finally:
            os.close(directory_fd)

    @staticmethod
    def _result(
        profile: RegisteredGitRepositoryProfile,
        inspection: _Inspection,
    ) -> RepositorySafetyAssessment:
        facts = {
            "repository_profile_sha256": profile.profile_sha256,
            "files": sorted(inspection.facts),
            "reason_codes": sorted(inspection.reasons),
            "policy_version": profile.safety_policy_version,
        }
        return RepositorySafetyAssessment(
            safe=not inspection.reasons,
            reason_codes=tuple(sorted(inspection.reasons)),
            repository_safety_sha256=canonical_sha256(facts),
            inspected_files=inspection.inspected_files,
            inspected_bytes=inspection.inspected_bytes,
        )


def _protected_remote_url(profile: RegisteredGitRepositoryProfile) -> str:
    remote = profile.remote
    return f"ssh://{remote.service_user}@{remote.host}:{remote.port}/{remote.repository_path}"


def _read_bounded(file_fd: int, expected_size: int, maximum_bytes: int) -> bytes:
    chunks: list[bytes] = []
    byte_count = 0
    while True:
        chunk = os.read(file_fd, min(65_536, maximum_bytes + 1 - byte_count))
        if not chunk:
            break
        byte_count += len(chunk)
        if byte_count > maximum_bytes:
            raise OSError("repository control file exceeds the configured limit")
        chunks.append(chunk)
    content = b"".join(chunks)
    if len(content) != expected_size:
        raise OSError("repository control file changed during inspection")
    return content


def _bounded_directory_entries(
    directory_fd: int,
    maximum_entries: int,
) -> tuple[tuple[_DirectoryEntry, ...], bool]:
    entries: list[_DirectoryEntry] = []
    with os.scandir(directory_fd) as iterator:
        for entry in iterator:
            if len(entries) >= maximum_entries:
                return tuple(sorted(entries, key=lambda item: item.name)), True
            entries.append(
                _DirectoryEntry(
                    name=entry.name,
                    is_symlink=entry.is_symlink(),
                    is_directory=entry.is_dir(follow_symlinks=False),
                )
            )
    return tuple(sorted(entries, key=lambda item: item.name)), False


__all__ = ["BoundedGitRepositoryProfileValidator"]
