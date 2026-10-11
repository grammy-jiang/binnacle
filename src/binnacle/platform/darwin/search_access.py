"""Bounded ripgrep stdin search over opened Files capabilities.

Ignore discovery is confined to the grant: .gitignore/.ignore/.rgignore above
it and global policies are never read. Search treats NUL-containing files as
text (rg --text, as on Linux); binary_files_skipped stays in the summary stats
at 0. Files skipped for size or concurrent change are counted in those stats but
never set ``truncated``: only caps (file, input or output budgets) do.
Files use deterministic path order (rg --sort path); default rg order is unspecified. Listing includes
binary files, matching rg --files. The helper owns one direct rg child, closes
pipes and reaps on every exit. This is not general process-tree control.
B0 alone enables reviewed tool wiring; full macOS parity remains unavailable.
"""

from __future__ import annotations

import base64
import json
import os
import selectors
import shutil
import subprocess
import time
from collections.abc import Mapping
from contextlib import closing

from binnacle.platform.contracts.capability_contracts import (
    BudgetExceeded,
    PermissionDenied,
    UnsafePath,
)
from binnacle.platform.contracts.file_access_contracts import (
    FileAccess,
    ListRequest,
    RootGrant,
    SearchBatch,
    SearchRequest,
)
from binnacle.platform.darwin.file_traversal import (
    MAX_BYTES,
    MAX_VISITED,
    capability,
    deadline_after,
    glob_matches,
    native_errors,
    require_positive,
    unavailable,
    validate_relative_path,
)


def _command(rg_bin: str, request: SearchRequest) -> list[str]:
    argv = [rg_bin, "--no-config", "--json", "--smart-case", "--text"]
    if request.fixed_strings:
        argv.append("--fixed-strings")
    if request.context_lines:
        argv += ["--context", str(request.context_lines)]
    return [*argv, "--regexp", request.pattern, "--", "-"]


@native_errors()
def _pump(
    child: subprocess.Popen[bytes], data: bytes, deadline: float, max_output: int
) -> tuple[bytes, bool]:
    """Concurrent bounded input/output; no communicate() allocation escape."""
    if child.stdin is None or child.stdout is None or child.stderr is None:
        raise unavailable("rg_pipes_unavailable")
    output = bytearray()
    offset = 0
    with selectors.DefaultSelector() as selector:
        for stream in (child.stdin, child.stdout, child.stderr):
            os.set_blocking(stream.fileno(), False)
        if data:
            selector.register(child.stdin, selectors.EVENT_WRITE)
        else:
            child.stdin.close()
        selector.register(child.stdout, selectors.EVENT_READ)
        selector.register(child.stderr, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BudgetExceeded("rg_timeout", capability("rg_timeout"))
            for key, _ in selector.select(min(remaining, 0.1)):
                pipe = key.fileobj
                if pipe is child.stdin:
                    try:
                        offset += os.write(key.fd, data[offset : offset + 65536])
                    except BrokenPipeError:
                        offset = len(data)
                    if offset == len(data):
                        selector.unregister(pipe)
                        child.stdin.close()
                else:
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(pipe)
                    elif pipe is child.stdout:
                        room = max_output - len(output)
                        output.extend(chunk[:room])
                        if len(chunk) > room:
                            return bytes(output), True
                    # stderr is drained but never exposed or accumulated.
    return bytes(output), False


@native_errors()
def _run_rg(
    argv: list[str], data: bytes, deadline: float, max_output: int
) -> tuple[bytes, bool]:
    try:
        child = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
        )
    except OSError:
        raise unavailable("rg_unavailable") from None
    try:
        output, truncated = _pump(child, data, deadline, max_output)
        if truncated:
            return output, True
        try:
            returncode = child.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise BudgetExceeded("rg_timeout", capability("rg_timeout")) from None
        if returncode not in (0, 1):
            raise unavailable("rg_rejected")
        return output, False
    finally:
        # Popen owns the unreaped direct child; never signal a saved numeric PID.
        if child.poll() is None:
            child.kill()
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            raise unavailable("rg_cleanup_failed") from None
        finally:
            for pipe in (child.stdin, child.stdout, child.stderr):
                if pipe is not None:
                    pipe.close()


def _events(output: bytes, display: str, truncated: bool) -> list[Mapping[str, object]]:
    events: list[Mapping[str, object]] = []
    # A bounded helper may finish partway through its last JSON line.
    lines = output.splitlines(keepends=True)
    for line in lines:
        if truncated and not line.endswith(b"\n"):
            break
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            raise unavailable("rg_invalid_output") from None
        if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
            raise unavailable("rg_invalid_output")
        payload = event["data"]
        if "path" in payload:
            try:
                display.encode("utf-8")
                payload["path"] = {"text": display}
            except UnicodeError:
                payload["path"] = {
                    "bytes": base64.b64encode(os.fsencode(display)).decode("ascii")
                }
        events.append(event)
    return events


def _duration(nanos: int) -> dict[str, int | str]:
    return {
        "secs": nanos // 10**9,
        "nanos": nanos % 10**9,
        "human": f"{nanos / 10**9:.6f}s",
    }


def _aggregate(
    events: list[Mapping[str, object]], elapsed: int, counts: dict[str, int]
) -> list[Mapping[str, object]]:
    """Reduce child summaries once; match/context/end records retain rg shape."""
    totals = dict.fromkeys(
        (
            "searches",
            "searches_with_match",
            "bytes_searched",
            "bytes_printed",
            "matched_lines",
            "matches",
        ),
        0,
    )
    kept: list[Mapping[str, object]] = []
    search_nanos = 0
    for event in events:
        if event["type"] != "summary":
            kept.append(event)
            continue
        payload = event["data"]
        if not isinstance(payload, dict) or not isinstance(payload.get("stats"), dict):
            raise unavailable("rg_invalid_output")
        stats = payload["stats"]
        for key in totals:
            value = stats.get(key)
            if not isinstance(value, int) or value < 0:
                raise unavailable("rg_invalid_output")
            totals[key] += value
        duration = stats.get("elapsed", {})
        if isinstance(duration, dict):
            search_nanos += int(duration.get("secs", 0)) * 10**9 + int(
                duration.get("nanos", 0)
            )
    kept.append(
        {
            "type": "summary",
            "data": {
                "elapsed_total": _duration(elapsed),
                "stats": {**totals, "elapsed": _duration(search_nanos), **counts},
            },
        }
    )
    return kept


class DarwinSearchAccess:
    def __init__(self, files: FileAccess, *, rg_bin: str) -> None:
        self._files = files
        resolved = rg_bin if os.path.isabs(rg_bin) else shutil.which(rg_bin)
        if resolved is None:
            raise unavailable("rg_unavailable")
        # Composition captures PATH once; calls never resolve it again.
        self._rg_bin = os.path.abspath(resolved)

    def _paths(
        self, grant: RootGrant, request: SearchRequest
    ) -> tuple[list[str], bool]:
        parts = validate_relative_path(request.relative_path)
        if parts:
            try:
                with closing(self._files.open_read(grant, request.relative_path)):
                    paths = ["/".join(parts)]
                    if request.glob and not glob_matches(parts[-1], request.glob):
                        paths = []
                    return paths, False
            except UnsafePath as exc:
                if exc.code != "path_is_directory":
                    raise
        listing = self._files.list_entries(
            grant,
            ListRequest(
                request.relative_path,
                request.glob or "**/*",
                False,
                MAX_VISITED,
                MAX_VISITED,
                request.timeout_s,
            ),
        )
        paths = sorted(
            (entry.relative_path for entry in listing.entries if entry.kind == "file"),
            key=os.fsencode,
        )
        return paths[: request.max_files], listing.truncated or len(
            paths
        ) > request.max_files

    def search(self, grant: RootGrant, request: SearchRequest) -> SearchBatch:
        require_positive(request.max_bytes, MAX_BYTES)
        require_positive(request.max_files, MAX_VISITED)
        started = time.monotonic_ns()
        deadline = deadline_after(request.timeout_s)
        if not 0 <= request.context_lines <= 10000 or len(request.pattern) > 65536:
            raise BudgetExceeded(
                "invalid_search_budget", capability("invalid_search_budget")
            )
        if "\0" in request.pattern:
            raise unavailable("rg_invalid_pattern")
        argv = _command(self._rg_bin, request)
        paths, truncated = self._paths(grant, request)
        events: list[Mapping[str, object]] = []
        files_searched = unreadable_files_skipped = 0
        binary_files_skipped = 0  # NUL files are searched as text
        skipped_oversize = skipped_changed = 0
        input_budget_exhausted = output_budget_exhausted = 0
        input_left = output_left = request.max_bytes
        for path in paths:
            if time.monotonic() >= deadline:
                raise BudgetExceeded("rg_timeout", capability("rg_timeout"))
            if input_left <= 0 or output_left <= 0:
                input_budget_exhausted = int(input_left <= 0)
                output_budget_exhausted = int(output_left <= 0)
                truncated = True
                break
            try:
                with closing(self._files.open_read(grant, path)) as opened:
                    data = opened.read(min(input_left + 1, 65536))
                    if b"\0" not in data and len(data) <= input_left:
                        data += opened.read(input_left + 1 - len(data))
            except PermissionDenied:
                if path == request.relative_path:
                    raise
                unreadable_files_skipped += 1
                continue
            except UnsafePath as exc:
                if path == request.relative_path or exc.code not in {
                    "path_not_found",
                    "symlink_or_wrong_path_type",
                    "entry_changed",
                    "special_file_unsupported",
                    "path_is_directory",
                }:
                    raise
                skipped_changed += 1
                continue
            if len(data) > input_left:
                # Never search a cut line and report a false regex/end anchor hit.
                # Reported through skipped_oversize; not a capped result set.
                skipped_oversize += 1
                continue
            input_left -= len(data)
            output, capped = _run_rg(argv, data, deadline, output_left)
            output_left -= len(output)
            events.extend(_events(output, path, capped))
            files_searched += 1
            if capped:
                output_budget_exhausted = 1
                truncated = True
                break
        # Binary-only, unreadable-only and empty trees still validate rg/pattern.
        if files_searched == 0:
            _run_rg(argv, b"", deadline, max(1, output_left))
        events = _aggregate(
            events,
            time.monotonic_ns() - started,
            {
                "files_searched": files_searched,
                "input_budget_exhausted": input_budget_exhausted,
                "output_budget_exhausted": output_budget_exhausted,
                "skipped_oversize": skipped_oversize,
                "skipped_changed": skipped_changed,
                "binary_files_skipped": binary_files_skipped,
                "unreadable_files_skipped": unreadable_files_skipped,
            },
        )
        return SearchBatch(
            events, truncated, files_searched, capability("darwin_search_limited")
        )
