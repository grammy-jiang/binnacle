"""Opened-object file and search contracts; display paths are never authority.

Grants retain the originally opened directory across rename, not a replacement
pathname. Implementations own descriptor traversal, no-follow validation and
bounded reads, listings, parent creation, diagnostics and search. Denial must not
be represented as an empty result. Close is idempotent; use after close fails.

Write receipts describe the verified destination at the write step. The expected
digest detects observed conflicts, not atomic compare-and-swap against hostile
writers. Search supplies only authorized open files to bounded rg stdin; missing
adapters or unsupported policies must fail explicitly without pathname fallback.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from binnacle.platform.contracts.capability_contracts import Capability


class RootGrant(Protocol):
    @property
    def generation(self) -> str: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class FileMetadata:
    size_bytes: int
    device: int
    inode: int
    modified_ns: int


class OpenedFile(Protocol):
    @property
    def display_path(self) -> str: ...
    def metadata(self) -> FileMetadata: ...
    def read(self, max_bytes: int) -> bytes: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class FileEntry:
    relative_path: str
    kind: Literal["file", "directory", "other"]
    size_bytes: int | None
    modified_ns: int | None
    # Set only for a symlink whose target resolves inside the opened root.
    target_kind: Literal["file", "directory"] | None = None


@dataclass(frozen=True)
class ListRequest:
    relative_path: str
    glob: str | None
    include_hidden: bool
    max_entries: int
    max_visited: int
    timeout_s: float


@dataclass(frozen=True)
class FileListing:
    entries: Sequence[FileEntry]
    truncated: bool


@dataclass(frozen=True)
class WriteReceipt:
    bytes_written: int
    previous_bytes: int | None
    action: Literal["created", "overwritten"]


class FileAccess(Protocol):
    def grant(self, root: Path, *, generation: str) -> RootGrant: ...
    def open_read(self, grant: RootGrant, relative_path: str) -> OpenedFile: ...
    def list_entries(self, grant: RootGrant, request: ListRequest) -> FileListing: ...
    def nearby_hint(
        self, grant: RootGrant, relative_path: str, *, max_entries: int
    ) -> Sequence[str]: ...
    def write_bytes(
        self,
        grant: RootGrant,
        relative_path: str,
        data: bytes,
        *,
        create_parents: bool = False,
        max_new_parents: int = 32,
        expected_sha256: str | None = None,
    ) -> WriteReceipt: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class SearchRequest:
    relative_path: str
    pattern: str
    fixed_strings: bool
    context_lines: int
    glob: str | None
    timeout_s: float
    max_bytes: int
    max_files: int


@dataclass(frozen=True)
class SearchBatch:
    events: Sequence[Mapping[str, object]]
    truncated: bool
    files_searched: int
    capability: Capability


class SearchAccess(Protocol):
    def search(self, grant: RootGrant, request: SearchRequest) -> SearchBatch: ...
