"""Normalized evidence models and interval math for scheduling benchmarks."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolInterval(StrictModel):
    call_id: str
    node_id: str | None = None
    tool: str
    turn: str | None = None
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    args: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    is_error: bool = False
    tokenizer_tokens: int = Field(default=0, ge=0)
    result_bytes: int = Field(default=0, ge=0)
    blocking_start_s: float | None = None
    blocking_end_s: float | None = None

    @model_validator(mode="after")
    def validate_times(self) -> ToolInterval:
        if self.end_s < self.start_s:
            raise ValueError("tool end_s must not precede start_s")
        if (self.blocking_start_s is None) != (self.blocking_end_s is None):
            raise ValueError("blocking interval must provide both endpoints")
        if self.blocking_start_s is not None and self.blocking_end_s is not None:
            if self.blocking_start_s < self.start_s:
                raise ValueError("blocking interval starts before tool call")
            if self.blocking_end_s < self.blocking_start_s:
                raise ValueError("blocking interval end precedes start")
            if self.blocking_end_s > self.end_s + 0.05:
                raise ValueError("blocking interval extends beyond tool call")
        return self


class JobInterval(StrictModel):
    job_id: str
    start_s: float = Field(ge=0)
    end_s: float | None = Field(default=None, ge=0)
    exit_code: int | None = None
    signal: int | None = None

    @model_validator(mode="after")
    def validate_times(self) -> JobInterval:
        if self.end_s is not None and self.end_s < self.start_s:
            raise ValueError("job end_s must not precede start_s")
        return self


class TrialTrace(StrictModel):
    schema_version: Literal[1] = 1
    scenario_id: str
    run_id: str
    nonce: str
    fixture_root: str
    fixture_jobs: dict[str, str] = Field(default_factory=dict)
    arm: str | None = None
    wall_s: float | None = Field(default=None, ge=0)
    timing_status: Literal["complete", "timeout", "unknown"] = "unknown"
    final_reply: str = ""
    assistant_complete: bool = False
    interruption_kind: str | None = None
    budget_exhausted: bool = False
    external_input_required: bool = False
    unrecoverable_error: bool = False
    user_messages: int = Field(default=1, ge=0)
    tools: list[ToolInterval] = Field(default_factory=list)
    jobs: list[JobInterval] = Field(default_factory=list)
    explicit_completed_nodes: set[str] = Field(default_factory=set)
    relations: dict[str, bool] = Field(default_factory=dict)
    final_files: dict[str, str] = Field(default_factory=dict)
    mutation_scope_ok: bool | None = None
    production_unchanged: bool | None = None


class TrialMetrics(StrictModel):
    schema_version: Literal[1] = 1
    scenario_id: str
    run_id: str
    arm: str | None
    wall_s: float | None
    correctness_passed: bool
    oracle_failures: list[str]
    same_prompt_completion: bool
    premature_handoff: bool
    budget_exhaustion_handoff: bool
    manual_continuations_required: int
    interrupted: bool
    interruption_kind: str | None
    tool_calls: int
    duplicate_calls: int
    redundant_exact_calls: int
    job_status_calls: int
    positive_job_status_calls: int
    blocking_wall_s: float
    avoidable_idle_wall_s: float
    read_only_peak_inflight: int
    eligible_read_only_calls: int
    overlapped_eligible_read_only_calls: int
    eligible_read_only_overlap_ratio: float | None
    tool_result_tokens: int
    tool_result_bytes: int
    tool_errors: int


def interval_union(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Merge half-open intervals; touching intervals are treated as one window."""
    clean = sorted((a, b) for a, b in intervals if b > a)
    if not clean:
        return []
    merged = [clean[0]]
    for start, end in clean[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def interval_union_seconds(intervals: list[tuple[float, float]]) -> float:
    return round(sum(end - start for start, end in interval_union(intervals)), 6)


def intersection_seconds(
    left: list[tuple[float, float]],
    right: list[tuple[float, float]],
) -> float:
    """Length of the intersection of two interval unions."""
    a = interval_union(left)
    b = interval_union(right)
    i = j = 0
    total = 0.0
    while i < len(a) and j < len(b):
        start = max(a[i][0], b[j][0])
        end = min(a[i][1], b[j][1])
        if end > start:
            total += end - start
        if a[i][1] <= b[j][1]:
            i += 1
        else:
            j += 1
    return round(total, 6)


def peak_inflight(intervals: list[tuple[float, float]]) -> int:
    """Maximum number of overlapping half-open intervals."""
    points: list[tuple[float, int]] = []
    for start, end in intervals:
        if end <= start:
            continue
        points.append((start, 1))
        points.append((end, -1))
    # Ends sort before starts at the same timestamp: [start, end) semantics.
    points.sort(key=lambda item: (item[0], item[1]))
    current = peak = 0
    for _, delta in points:
        current += delta
        peak = max(peak, current)
    return peak


def calls_by_node(trace: TrialTrace) -> dict[str, list[ToolInterval]]:
    grouped: dict[str, list[ToolInterval]] = defaultdict(list)
    for call in trace.tools:
        if call.node_id is not None:
            grouped[call.node_id].append(call)
    for calls in grouped.values():
        calls.sort(key=lambda call: (call.start_s, call.end_s, call.call_id))
    return dict(grouped)


def exact_call_key(call: ToolInterval) -> tuple[str, str]:
    import json

    return call.tool, json.dumps(call.args, sort_keys=True, separators=(",", ":"))
