"""Binary streaming ripgrep JSONL runner for exact search.

The runner owns only process lifetime and JSONL decoding. Search semantics, glob
filtering, result caps, context shaping, and adaptive ranking live above it.
"""

from __future__ import annotations

import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Self

import orjson

from binnacle.errors import CodedToolError


@dataclass
class RgStreamStats:
    stdout_bytes: int = 0
    events: int = 0
    match_events: int = 0
    context_events: int = 0
    begin_events: int = 0
    bad_json: int = 0
    wall_ms: float = 0.0
    stream_cpu_ms: float = 0.0
    timed_out: bool = False


class RgJsonStream:
    """Context-managed iterator over one ``rg --json`` process.

    ``stderr`` is redirected to a temporary file so an unread stderr pipe cannot
    deadlock stdout consumption. A watchdog preserves the previous absolute
    timeout contract while the caller processes stdout incrementally.
    """

    def __init__(
        self,
        root: Path,
        pattern: str,
        fixed_strings: bool,
        context: int,
        *,
        rg_bin: str,
        timeout_s: float,
    ) -> None:
        self.root = root
        self.pattern = pattern
        self.fixed_strings = fixed_strings
        self.context = context
        self.rg_bin = rg_bin
        self.timeout_s = timeout_s
        self.stats = RgStreamStats()
        self.no_match = False
        self._proc: subprocess.Popen[bytes] | None = None
        self._stderr: BinaryIO | None = None
        self._timer: threading.Timer | None = None
        self._timeout_fired = threading.Event()
        self._started_ns = 0
        self._cpu_started_ns = 0
        self._finished = False

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    def _command(self) -> list[str]:
        cmd = [self.rg_bin, "--json", "--smart-case"]
        if self.fixed_strings:
            cmd.append("--fixed-strings")
        if self.context > 0:
            cmd += ["--context", str(self.context)]
        cmd += ["--regexp", self.pattern, str(self.root)]
        return cmd

    def __enter__(self) -> Self:
        self._stderr = tempfile.TemporaryFile(mode="w+b")
        self._started_ns = time.perf_counter_ns()
        self._cpu_started_ns = time.thread_time_ns()
        try:
            self._proc = subprocess.Popen(
                self._command(),
                stdout=subprocess.PIPE,
                stderr=self._stderr,
                text=False,
            )
        except FileNotFoundError:
            self._stderr.close()
            self._stderr = None
            raise CodedToolError(
                "rg_missing",
                "ripgrep (rg) is not available; use run_command (grep -rn) instead.",
            ) from None
        self._timer = threading.Timer(self.timeout_s, self._on_timeout)
        self._timer.daemon = True
        self._timer.start()
        return self

    def _on_timeout(self) -> None:
        self._timeout_fired.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    def __iter__(self) -> Iterator[dict]:
        proc = self._proc
        if proc is None or proc.stdout is None:
            raise RuntimeError("RgJsonStream must be entered before iteration")
        try:
            for raw in proc.stdout:
                self.stats.stdout_bytes += len(raw)
                try:
                    event = orjson.loads(raw)
                except orjson.JSONDecodeError:
                    self.stats.bad_json += 1
                    continue
                self.stats.events += 1
                kind = event.get("type")
                if kind == "match":
                    self.stats.match_events += 1
                elif kind == "context":
                    self.stats.context_events += 1
                elif kind == "begin":
                    self.stats.begin_events += 1
                yield event
            self._finish()
        except BaseException:
            self._abort()
            raise

    def _stderr_tail(self, limit: int = 300) -> str:
        if self._stderr is None:
            return ""
        self._stderr.flush()
        size = self._stderr.seek(0, 2)
        self._stderr.seek(max(0, size - 2_048))
        return self._stderr.read().decode("utf-8", errors="replace").strip()[-limit:]

    def _record_timing(self) -> None:
        if self._started_ns:
            self.stats.wall_ms = (time.perf_counter_ns() - self._started_ns) / 1_000_000
        if self._cpu_started_ns:
            self.stats.stream_cpu_ms = (
                time.thread_time_ns() - self._cpu_started_ns
            ) / 1_000_000

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        if self._timer is not None:
            self._timer.cancel()
        proc = self._proc
        if proc is None:
            return
        returncode = proc.wait()
        self._record_timing()
        self.stats.timed_out = self._timeout_fired.is_set()
        if self.stats.timed_out:
            raise CodedToolError(
                "rg_timeout",
                f"Search timed out after {self.timeout_s:g} s. Narrow the scope "
                "with a more specific path or a glob filter.",
            )
        self.no_match = returncode == 1
        stderr = self._stderr_tail()
        if returncode == 2 or (returncode not in (0, 1) and stderr):
            raise CodedToolError(
                "rg_rejected",
                f"ripgrep rejected the search: {stderr or 'unknown error'}. "
                "Fix the pattern, or use fixed_strings for literal text.",
            )

    def _abort(self) -> None:
        if self._finished:
            return
        self._finished = True
        if self._timer is not None:
            self._timer.cancel()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        if proc is not None:
            proc.wait()
        self._record_timing()
        self.stats.timed_out = self._timeout_fired.is_set()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if exc_type is None and not self._finished:
                # The consumer stopped before EOF; never leave rg behind.
                self._abort()
            elif exc_type is not None:
                self._abort()
        finally:
            if self._timer is not None:
                self._timer.cancel()
            if self._proc is not None and self._proc.stdout is not None:
                self._proc.stdout.close()
            if self._stderr is not None:
                self._stderr.close()
