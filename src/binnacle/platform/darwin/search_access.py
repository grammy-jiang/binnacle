"""Bounded ripgrep stdin search over opened Files capabilities.

Only root-local .ignore/.rgignore positive excludes are supported. Git/global
and ancestor ignore discovery is unavailable, never performed outside a grant.
NUL-containing input is explicitly unsupported: rg stdin binary semantics differ
from recursive-file search. The helper owns one direct rg child, closes pipes and reaps on every exit. This
is not general process-tree control. B0 alone enables reviewed tool wiring.
"""

from __future__ import annotations

import base64
import json
import os
import selectors
import subprocess
import time
from collections.abc import Mapping
from contextlib import closing

from binnacle.platform.contracts.capability_contracts import BudgetExceeded, UnsafePath
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
    require_positive,
    unavailable,
    validate_relative_path,
)


def _command(rg_bin: str, request: SearchRequest) -> list[str]:
    argv = [rg_bin, "--no-config", "--json", "--smart-case"]
    if request.fixed_strings:
        argv.append("--fixed-strings")
    if request.context_lines:
        argv += ["--context", str(request.context_lines)]
    return [*argv, "--regexp", request.pattern, "--", "-"]


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


class DarwinSearchAccess:
    def __init__(self, files: FileAccess, *, rg_bin: str) -> None:
        self._files = files
        self._rg_bin = rg_bin

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
                request.max_files,
                MAX_VISITED,
                request.timeout_s,
            ),
        )
        return [
            entry.relative_path for entry in listing.entries if entry.kind == "file"
        ], listing.truncated

    def search(self, grant: RootGrant, request: SearchRequest) -> SearchBatch:
        require_positive(request.max_bytes, MAX_BYTES)
        require_positive(request.max_files, MAX_VISITED)
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
        files_searched = 0
        input_left = output_left = request.max_bytes
        # Invalid expressions and missing rg must fail even for an empty tree.
        if not paths:
            _run_rg(argv, b"", deadline, output_left)
        for path in paths:
            if time.monotonic() >= deadline:
                raise BudgetExceeded("rg_timeout", capability("rg_timeout"))
            if input_left <= 0 or output_left <= 0:
                truncated = True
                break
            with closing(self._files.open_read(grant, path)) as opened:
                data = opened.read(input_left + 1)
            if len(data) > input_left:
                # Never search a cut line and report a false regex/end anchor hit.
                truncated = True
                break
            if b"\0" in data:
                raise unavailable("darwin_binary_search_unavailable")
            input_left -= len(data)
            output, capped = _run_rg(argv, data, deadline, output_left)
            output_left -= len(output)
            events.extend(_events(output, path, capped))
            files_searched += 1
            if capped:
                truncated = True
                break
        return SearchBatch(
            events, truncated, files_searched, capability("darwin_search_limited")
        )
