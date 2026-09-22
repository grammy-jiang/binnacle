"""Low-overhead exact-search telemetry accumulator and terminal event logger."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Literal

Strategy = Literal["normal", "names_only", "adaptive"]


@dataclass
class AdaptiveWork:
    match_events_scanned: int = 0
    glob_checks: int = 0
    glob_rejected: int = 0


@dataclass
class ExactSearchMetrics:
    call: str
    scope: str
    context_requested: str
    started_ns: int = 0
    strategy: Strategy = "normal"
    budget_outcome: str = "none"
    outcome: str = "ok"
    error_code: str = "-"
    rg_calls: int = 0
    auto_context: bool = False
    effective_context: int = 0
    rg_subprocess_ms: float = 0.0
    rg_parse_ms: float = 0.0
    collect_ms: float = 0.0
    context_attach_ms: float = 0.0
    adaptive_ms: float = 0.0
    budget_ms: float = 0.0
    rg_stdout_chars: int = 0
    rg_events: int = 0
    rg_match_events: int = 0
    rg_context_events: int = 0
    rg_begin_events: int = 0
    rg_bad_json: int = 0
    collect_event_candidates: int = 0
    collect_glob_checks: int = 0
    collect_glob_rejected: int = 0
    accepted_matches: int = 0
    accepted_files: int = 0
    retained_matches: int = 0
    match_cap_hit: bool = False
    adaptive_attempted: bool = False
    adaptive_selected: bool = False
    adaptive_budget_trimmed: bool = False
    adaptive_match_events: int = 0
    adaptive_glob_checks: int = 0
    adaptive_glob_rejected: int = 0
    pre_budget_bytes: int = 0
    returned_entries: int = 0
    result_bytes: int = 0
    final_truncated: bool = False
    _logged: bool = False

    def start(self) -> None:
        self.started_ns = time.perf_counter_ns()

    @staticmethod
    def elapsed_ms(started_ns: int) -> float:
        return (time.perf_counter_ns() - started_ns) / 1_000_000

    def mark_result(self, payload: dict, *, strategy: Strategy) -> None:
        self.strategy = strategy
        entries = payload.get("entries")
        self.returned_entries = len(entries) if isinstance(entries, list) else 0
        self.final_truncated = bool(payload.get("truncated"))

    def log_terminal(
        self, logger: logging.Logger, exc: BaseException | None = None
    ) -> None:
        if self._logged:
            return
        self._logged = True
        if exc is not None:
            self.outcome = "error"
            self.error_code = str(getattr(exc, "telemetry_code", "-"))
        impl_ms = self.elapsed_ms(self.started_ns) if self.started_ns else 0.0
        logger.info(
            "event=search_exact call=%s outcome=%s error_code=%s strategy=%s "
            "budget_outcome=%s scope=%s rg_calls=%d auto_context=%s context_requested=%s "
            "effective_context=%d rg_subprocess_ms=%.2f rg_parse_ms=%.2f "
            "collect_ms=%.2f context_attach_ms=%.2f adaptive_ms=%.2f "
            "budget_ms=%.2f impl_ms=%.2f rg_stdout_chars=%d rg_events=%d "
            "rg_match_events=%d rg_context_events=%d rg_begin_events=%d "
            "rg_bad_json=%d collect_event_candidates=%d collect_glob_checks=%d "
            "collect_glob_rejected=%d accepted_matches=%d accepted_files=%d "
            "retained_matches=%d match_cap_hit=%s adaptive_attempted=%s "
            "adaptive_selected=%s adaptive_budget_trimmed=%s "
            "adaptive_match_events=%d adaptive_glob_checks=%d "
            "adaptive_glob_rejected=%d pre_budget_bytes=%d returned_entries=%d "
            "result_bytes=%d final_truncated=%s",
            self.call,
            self.outcome,
            self.error_code,
            self.strategy,
            self.budget_outcome,
            self.scope,
            self.rg_calls,
            str(self.auto_context).lower(),
            self.context_requested,
            self.effective_context,
            self.rg_subprocess_ms,
            self.rg_parse_ms,
            self.collect_ms,
            self.context_attach_ms,
            self.adaptive_ms,
            self.budget_ms,
            impl_ms,
            self.rg_stdout_chars,
            self.rg_events,
            self.rg_match_events,
            self.rg_context_events,
            self.rg_begin_events,
            self.rg_bad_json,
            self.collect_event_candidates,
            self.collect_glob_checks,
            self.collect_glob_rejected,
            self.accepted_matches,
            self.accepted_files,
            self.retained_matches,
            str(self.match_cap_hit).lower(),
            str(self.adaptive_attempted).lower(),
            str(self.adaptive_selected).lower(),
            str(self.adaptive_budget_trimmed).lower(),
            self.adaptive_match_events,
            self.adaptive_glob_checks,
            self.adaptive_glob_rejected,
            self.pre_budget_bytes,
            self.returned_entries,
            self.result_bytes,
            str(self.final_truncated).lower(),
        )
