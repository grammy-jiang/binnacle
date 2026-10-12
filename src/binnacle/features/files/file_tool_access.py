"""Opened-grant file access for the Darwin file and search tools.

Split behavior-neutrally out of features/files/paths.py (r6 W3 PX1b): the
grant selection (select_root_grant), the application-owned grants
(FileToolAccess) and the provider-less focused access. paths.py keeps the
Linux path guard and the glob matcher and re-exports these names.
"""

import logging
import os

# These bindings contain ordinary injected contracts, never host selection.
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path, PurePath
from threading import RLock
from uuid import uuid4

from binnacle.config import RootsSettings
from binnacle.errors import CodedToolError
from binnacle.features.files.error_text import (
    DEFAULT_MISSING,
    MISSING_ERRORS,
    TERSE_OUTSIDE,
    TOOL,
    followed,
    linux_error,
    outside_error,
)
from binnacle.features.files.fd_walk import path_changed
from binnacle.features.files.textio import human_size
from binnacle.platform.contracts.capability_contracts import (
    Capability,
    CapabilityState,
    NativeCapabilityError,
)
from binnacle.platform.contracts.file_access_contracts import (
    FileAccess,
    RootGrant,
    SearchAccess,
)

# The journal keeps the logger name it had before the split (event=root_skipped).
log = logging.getLogger("binnacle.features.files.paths")


def select_root_grant(
    raw: str, *, default_root: Path, grants: Mapping[Path, RootGrant]
) -> tuple[RootGrant, str, Path]:
    """Lexical mapping only: request paths never resolve or inspect the filesystem."""
    cleaned = raw.strip().removeprefix("@")
    if "\0" in cleaned or ".." in PurePath(cleaned).parts:
        raise CodedToolError("path_outside_root", "Unsafe relative path.")
    candidate = Path(cleaned).expanduser()
    if not candidate.is_absolute():
        candidate = default_root / candidate
    for root in sorted(grants, key=lambda p: len(p.parts), reverse=True):
        if candidate.is_relative_to(root):
            return grants[root], candidate.relative_to(root).as_posix(), candidate
    raise CodedToolError("path_outside_root", "Path outside opened roots.")


class FileToolAccess:
    """Application-owned grants; LIMITED injection is for reviewed scope only.

    Production composition supplies UNAVAILABLE until exact-source review. There
    is no environment/configuration flag to turn review into an accepted grant.
    """

    def __init__(
        self,
        *,
        roots: RootsSettings,
        files: FileAccess | None,
        search: SearchAccess | None,
        generation: str,
        capability: Capability,
        capabilities: Mapping[str, Capability] | None = None,
        provider_factory: Callable[[], tuple[FileAccess, SearchAccess | None]]
        | None = None,
    ) -> None:
        self.files = files
        self.search = search
        self.capability = capability
        self.capabilities = dict(capabilities) if capabilities is not None else None
        self.default_root = roots.default_root.expanduser()
        self._allowed = roots.allowed
        # alias/canonical -> (canonical, reason) for roots skipped at entry.
        self.skipped: dict[Path, tuple[Path, str]] = {}
        self.grants: dict[Path, RootGrant] = {}
        self.closed = False
        self._lock = RLock()
        self._active = 0
        self._factory = provider_factory
        self._generation = generation
        self._pairs: tuple[tuple[Path, Path], ...] = ()
        if capability.state != CapabilityState.LIMITED or (
            files is None and provider_factory is None
        ):
            return
        # Roots are captured once; later lifespans reopen exactly these
        # canonical directories, never a re-resolved alias.
        self._pairs = tuple(
            (alias.expanduser(), canonical)
            for alias, canonical in zip(
                roots.allowed, roots.canonical_allowed, strict=True
            )
        )
        if provider_factory is not None:
            # Provider-backed access serves only inside an active lifespan.
            self.files = self.search = None
            self.closed = True
            return
        try:
            self._open_grants(generation)
        except BaseException:
            self.close()
            raise

    def _open_grants(self, generation: str) -> None:
        if self.files is None:
            raise CodedToolError(
                "native_capability_unavailable", "File provider missing."
            )
        for alias, canonical in self._pairs:
            # Alias prefixes are configured root strings only (LP, SD-74).
            aliases = tuple(a for a, c in self._pairs if c == canonical and a != c)
            try:
                grant = self.files.grant(
                    canonical, generation=generation, aliases=aliases
                )
            except (NativeCapabilityError, OSError) as exc:
                if self._factory is None:
                    raise
                # A missing/unopenable root has no grant this generation; it is
                # retried only at the next lifespan entry, never live.
                reason = getattr(exc, "code", None) or type(exc).__name__
                self.skipped[alias] = (canonical, reason)
                self.skipped[canonical] = (canonical, reason)
                log.warning("event=root_skipped root=%s reason=%s", canonical, reason)
                continue
            self.grants[alias] = grant
            self.grants[canonical] = grant

    def enter(self) -> None:
        """Start (or join) an application generation; the first entry opens grants."""
        with self._lock:
            if self._factory is not None and self._active == 0 and self._pairs:
                files, search = self._factory()
                self.files, self.search, self.grants = files, search, {}
                self.skipped = {}
                try:
                    self._open_grants(f"{self._generation}-{uuid4().hex}")
                except BaseException:
                    self._close_locked()
                    raise
                self.closed = False
            self._active += 1

    def exit(self) -> None:
        """Leave a generation; the last exit closes every grant."""
        with self._lock:
            self._active = max(0, self._active - 1)
            if self._active == 0:
                self._close_locked()

    def require(self, tool: str) -> None:
        TOOL.set(tool)
        capability = (
            self.capability if self.capabilities is None else self.capabilities[tool]
        )
        if capability.state != CapabilityState.LIMITED:
            raise CodedToolError(
                "native_capability_unavailable",
                f"{tool} is unavailable on macOS.",
            )

    @property
    def provider(self) -> FileAccess:
        if self.files is None:
            raise CodedToolError(
                "native_capability_unavailable", "File provider missing."
            )
        return self.files

    def _unopened_root_error(self, raw: str, tool: str) -> CodedToolError | None:
        """Linux-equivalent error for a request that no opened grant covers."""
        cleaned = raw.strip().removeprefix("@")
        candidate = Path(cleaned).expanduser()
        if not candidate.is_absolute():
            candidate = self.default_root / candidate
        display = candidate = Path(os.path.normpath(candidate))
        inside = False
        for root, (canonical, _reason) in self.skipped.items():
            if candidate.is_relative_to(root):
                display = canonical / candidate.relative_to(root)
                inside = True
                break
        if inside and self.grants:
            code, text = MISSING_ERRORS.get(tool, DEFAULT_MISSING)
            return CodedToolError(code, f"{text}: {display}.")
        if any(candidate.is_relative_to(root) for root in self.grants):
            return None  # a `..` that normalizes back inside keeps the terse refusal
        return outside_error(self._allowed, display)

    def select(self, raw: str, tool: str | None = None) -> tuple[RootGrant, str, Path]:
        tool = TOOL.get() if tool is None else tool
        with self._lock:
            if self.closed:
                raise CodedToolError(
                    "native_access_closed", "Opened grants are closed."
                )
            if self.files is None or self.capability.state != CapabilityState.LIMITED:
                raise CodedToolError(
                    "native_capability_unavailable",
                    "native_capability_unavailable: Files and search are unavailable on macOS.",
                )
            try:
                return select_root_grant(
                    raw, default_root=self.default_root, grants=dict(self.grants)
                )
            except CodedToolError as exc:
                if (
                    str(exc) in TERSE_OUTSIDE
                    and "\0" not in raw
                    and (err := self._unopened_root_error(raw, tool)) is not None
                ):
                    raise err from None
                raise

    @contextmanager
    def operation(
        self, raw: str, tool: str | None = None
    ) -> Iterator[tuple[RootGrant, str, Path]]:
        if tool is None:
            tool = TOOL.get()
        grant, relative, display = self.select(raw, tool)
        try:
            yield grant, relative, display
        except NativeCapabilityError as exc:
            mapped = linux_error(
                exc,
                tool,
                files=self.files,
                grants=self.grants,
                allowed=self._allowed,
                grant=grant,
                rel=relative,
                display=display,
            )
            if mapped is not None:
                raise mapped from exc
            if exc.code == "symlink_or_wrong_path_type":
                # A link met after the one followed hop: the path changed
                # between the resolve and the walk. Never the bare code (PX1b).
                raise path_changed(display, tool) from exc
            raise CodedToolError(exc.code, f"{exc.code}.") from exc

    def read(self, raw: str, max_bytes: int) -> tuple[Path, int, bytes]:
        # Only read_file and edit_file read through here; a stale tool name
        # from another call context must not change the wording.
        tool = "edit_file" if TOOL.get() == "edit_file" else "read_file"

        def step(
            grant: RootGrant, relative: str, display: Path
        ) -> tuple[Path, int, bytes]:
            opened = self.provider.open_read(grant, relative)
            try:
                size = opened.metadata().size_bytes
                if size > max_bytes:
                    if tool == "read_file":
                        raise CodedToolError(
                            "file_too_large",
                            f"File is {human_size(size)}; the limit is "
                            f"{max_bytes // (1024 * 1024)} MB. "
                            f"Use run_command (tail, sed -n, grep) to sample it.",
                        )
                    raise CodedToolError(
                        "file_too_large", "File exceeds read byte limit."
                    )
                data = opened.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise CodedToolError(
                        "file_too_large", "File grew beyond read byte limit."
                    )
                return display, len(data), data
            finally:
                opened.close()

        # An in-root symlink reads its target, as on Linux (R-OS1-F3).
        return followed(self.operation, raw, tool, dict(self.grants), step)

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        if self.closed:
            return
        self.closed = True
        for grant in self.grants.values():
            grant.close()
        files = self.files
        if self._factory is not None:
            # A closed generation keeps no descriptor-bearing provider.
            self.files = self.search = None
            self.grants = {}
        if files is not None:
            files.close()


def focused_file_access(roots: RootsSettings) -> FileToolAccess | None:
    """Provider-less access for a focused Files/Search child.

    Only the file rows are consulted, so a missing provider surfaces as a
    Files/Search native_capability_unavailable outcome, never a Commands error.
    Linux returns None (legacy path); the Commands invariant stays in
    composition.native_file_capability.
    """
    from binnacle.platform.composition import host_os_family
    from binnacle.platform.contracts.darwin_release_scope import (
        DARWIN_RELEASE_SCOPE,
        FILE_TOOLS,
    )

    if host_os_family() == "linux":
        return None
    rows = [DARWIN_RELEASE_SCOPE[tool].capability for tool in FILE_TOOLS]
    capability = max(rows, key=lambda cap: cap.state == CapabilityState.LIMITED)
    return FileToolAccess(
        roots=roots,
        files=None,
        search=None,
        generation="unavailable",
        capability=capability,
    )
