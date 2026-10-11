"""Path guard and glob matcher shared by every file-facing tool.

Design: docs/agent-toolset-design.md §6.7 (what this defends and what it
does not) and §7.11. Sanitization details: docs/tools/read_file.md §3.
"""

import fnmatch
import logging
import os
import re

# These bindings contain ordinary injected contracts, never host selection.
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path, PurePath, PurePosixPath
from threading import RLock
from uuid import uuid4

from binnacle.config import RootsSettings, get_settings
from binnacle.errors import CodedToolError
from binnacle.features.files.error_text import (
    DEFAULT_MISSING,
    MISSING_ERRORS,
    TERSE_OUTSIDE,
    TOOL,
    linux_error,
    outside_display,
    outside_error,
)
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

log = logging.getLogger(__name__)


def _canonical_roots(roots: RootsSettings) -> tuple[Path, ...]:
    """Resolve configured aliases exactly as candidate paths are resolved."""
    return roots.canonical_allowed


def resolve_path(raw: str, *, roots: RootsSettings | None = None) -> Path:
    """Sanitize a model-supplied path and resolve it inside the allowed roots."""
    roots = get_settings().roots if roots is None else roots
    cleaned = raw.replace("\0", "").strip()
    # Models occasionally emit a hallucinated "@" reference prefix.
    cleaned = cleaned.removeprefix("@")
    try:
        candidate = Path(cleaned).expanduser()
        if not candidate.is_absolute():
            candidate = roots.default_root / candidate
        resolved = candidate.resolve()
        allowed_roots = _canonical_roots(roots)
    except (RuntimeError, OSError) as e:
        # expanduser() raises RuntimeError for `~nosuchuser`; resolve() can
        # raise OSError on pathological names. Found by the property test
        # 2026-09-13: either would reach the client as an internal error.
        raise CodedToolError(
            "path_resolve_failed", f"Cannot resolve path {raw!r}: {e}"
        ) from None
    if not any(resolved.is_relative_to(root) for root in allowed_roots):
        allowed = ", ".join(str(r) for r in roots.allowed)
        shown = outside_display(candidate, resolved, allowed_roots)
        raise CodedToolError(
            "path_outside_root", f"Path outside allowed roots ({allowed}): {shown}"
        )
    return resolved


def _unwrap_fnmatch_translation(translated: str) -> str | None:
    """Return the regex body from fnmatch.translate's DOTALL wrapper.

    Python 3.14 changed the terminal anchor from ``\\Z`` to ``\\z``.
    Treat both as stdlib wrappers without compiling either anchor here, so this
    compatibility path itself also runs on Python 3.10-3.13.
    """
    prefix = "(?s:"
    for suffix in (r")\Z", r")\z"):
        if translated.startswith(prefix) and translated.endswith(suffix):
            return translated[len(prefix) : -len(suffix)]
    return None


def _class_regex(inner: str) -> str:
    """Regex fragment for the character class `[inner]`, exactly as fnmatch
    would emit it: a reversed range like `[a-.]` becomes the never-matching
    `(?!)` rather than a compile error, `^` is a literal (only `!` negates),
    and `\\` / `--` are escaped the stdlib's way. Found by the differential
    property test on 2026-09-13; delegating keeps every quirk identical."""
    translated = fnmatch.translate(f"[{inner}]")
    fragment = _unwrap_fnmatch_translation(translated)
    if fragment is not None:
        return fragment
    # Unknown wrapper format (a future Python): fall back to the class as is.
    return f"[{inner}]"


def _glob_segment_regex(seg: str) -> str:
    """One glob segment as a regex fragment; * and ? never cross a slash."""
    # glob.translate requires a character for a whole single-star segment.
    # Embedded stars and longer star runs may still match nothing.
    if seg == "*":
        return "[^/]+"
    res = []
    i = 0
    n = len(seg)
    while i < n:
        c = seg[i]
        if c == "*":
            res.append("[^/]*")
        elif c == "?":
            res.append("[^/]")
        elif c == "[":
            # The same boundary scan as fnmatch.translate: an optional `!`,
            # then a `]` that is part of the class, then up to the closing `]`.
            j = i + 1
            if j < n and seg[j] == "!":
                j += 1
            if j < n and seg[j] == "]":
                j += 1
            while j < n and seg[j] != "]":
                j += 1
            if j >= n:
                res.append(r"\[")  # unterminated class is a literal bracket
            else:
                res.append(_class_regex(seg[i + 1 : j]))
                i = j
        else:
            res.append(re.escape(c))
        i += 1
    return "".join(res)


@lru_cache(maxsize=256)
def _glob_regex(pattern: str) -> "re.Pattern[str]":
    # PurePath-normalize first, as the stdlib matcher does: doubled or
    # trailing slashes and "." segments vanish, so "**/" means "**".
    parts = str(PurePosixPath(pattern)).split("/")
    out = []
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if part == "**":
            # The stdlib's own translation (glob.translate): a trailing ** is
            # `.*`, any other is `(?:.+/)?` -- "nothing, or at least one
            # character then a slash". The `.+` may span the root of an
            # absolute path, so "/a/a" matches "**/a" but "/a" does not;
            # a per-segment `(?:[^/]+/)*` got the first case wrong
            # (found by the differential test under mutmut, 2026-09-13).
            out.append(".*" if last else "(?:.+/)?")
            continue
        out.append(_glob_segment_regex(part) + ("" if last else "/"))
    try:
        # DOTALL as the stdlib's `(?s:...)` wrapper: a newline in a name is
        # an ordinary character for `.*` and `.+`.
        return re.compile("".join(out), re.DOTALL)
    except re.error as e:
        raise ValueError(str(e)) from None


def full_match(path: "PurePath | str", pattern: str) -> bool:
    """PurePath.full_match for Python 3.10+ (the stdlib method needs 3.13).

    POSIX rules, case-sensitive: * and ? stay inside one segment, a
    whole-segment ** spans any number of segments, [seq] classes as in
    fnmatch, embedded ** degrades to *. Raises ValueError for a pattern
    whose character class does not compile, matching the callers'
    except ValueError -> ToolError contract.
    """
    # Normalize the path as the stdlib does ("a/." is "a", "./a" is "a").
    normalized = PurePosixPath(str(path))
    if not normalized.parts:
        # Only ** prefix segments can disappear with their slash. A final
        # star-only segment with at least two stars can match nothing; the
        # stdlib treats a single * as requiring a character.
        parts = PurePosixPath(pattern).parts
        return not parts or (
            all(part == "**" for part in parts[:-1])
            and len(parts[-1]) >= 2
            and not parts[-1].strip("*")
        )
    return _glob_regex(pattern).fullmatch(str(normalized)) is not None


def nearby_hint(parent: Path, *, roots: RootsSettings | None = None) -> str:
    """Not-found helper: up to 10 sibling names, when the parent is browsable."""
    roots = get_settings().roots if roots is None else roots
    try:
        canonical_parent = parent.expanduser().resolve()
        if not any(
            canonical_parent.is_relative_to(root) for root in _canonical_roots(roots)
        ):
            return ""
        names = sorted(
            p.name + ("/" if p.is_dir() else "") for p in canonical_parent.iterdir()
        )
    except (RuntimeError, OSError):
        return ""
    if not names:
        return f" Directory {parent} is empty."
    shown = ", ".join(names[:10])
    more = " …" if len(names) > 10 else ""
    return f" Files in {parent}: {shown}{more}. Use list_files for more."


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
            try:
                grant = self.files.grant(canonical, generation=generation)
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
            raise CodedToolError(exc.code, f"{exc.code}.") from exc

    def read(self, raw: str, max_bytes: int) -> tuple[Path, int, bytes]:
        # Only read_file and edit_file read through here; a stale tool name
        # from another call context must not change the wording.
        tool = "edit_file" if TOOL.get() == "edit_file" else "read_file"
        with self.operation(raw, tool) as (grant, relative, display):
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
