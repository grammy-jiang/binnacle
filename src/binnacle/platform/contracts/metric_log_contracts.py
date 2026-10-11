"""Scoped measurements and bounded generation-aware private log contracts.

UNKNOWN and UNAVAILABLE measurements have value None, never an invented zero.
Direct-child statistics come from the sole owning reaper and do not imply whole
job totals. Log generation, stream epoch and inode changes invalidate cursors or
report gaps; absent records never prove event absence. Readers bound bytes and
lines, and writers redact before persistence in private directories and files.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from binnacle.platform.contracts.capability_contracts import Capability


@dataclass(frozen=True)
class MetricValue:
    capability: Capability
    value: int | float | None
    unit: str
    scope: Literal["self", "direct_child", "job"]
    sampled_at_epoch: float | None
    final: bool


@dataclass(frozen=True)
class LogCursor:
    service_generation: str
    stream_epoch: str
    device: int
    inode: int
    offset: int


@dataclass(frozen=True)
class LogBatch:
    data: bytes
    next_cursor: LogCursor
    capability: Capability
    gap: bool
    truncated: bool


class ScopedMetrics(Protocol):
    def snapshot_scoped(
        self, job_id: str | None = None
    ) -> Mapping[str, MetricValue]: ...


class CursorLogSource(Protocol):
    def read_cursor(
        self, service: str, cursor: LogCursor | None, *, max_bytes: int, max_lines: int
    ) -> LogBatch: ...
