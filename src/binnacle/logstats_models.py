"""Data models for journal usage statistics."""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Record:
    event: str
    body: str
    day: str | None = None
    time: str | None = None
    timestamp: str | None = None


@dataclass
class IndexedContextStats:
    successes: int = 0
    errors: int = 0
    error_phases: Counter = field(default_factory=Counter)
    pilot_versions: Counter = field(default_factory=Counter)
    schema_versions: Counter = field(default_factory=Counter)
    parser_versions: Counter = field(default_factory=Counter)
    cold_opens: int = 0
    changed_files: int = 0
    evidence_opened: int = 0
    evidence_reads: int = 0
    evidence_file_searches: int = 0
    result_tokens: list[int] = field(default_factory=list)
    package_est_tokens: list[int] = field(default_factory=list)
    package_bytes: list[int] = field(default_factory=list)
    package_items: list[int] = field(default_factory=list)
    total_ms: list[float] = field(default_factory=list)
    reconcile_ms: list[float] = field(default_factory=list)
    query_ms: list[float] = field(default_factory=list)
    followup_calls: list[int] = field(default_factory=list)
    followup_exact_searches: list[int] = field(default_factory=list)
    followup_reads: list[int] = field(default_factory=list)
    followup_result_tokens: list[int] = field(default_factory=list)
    investigation_result_tokens: list[int] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AdaptiveDiscoveryStats:
    calls: int = 0
    budget_trimmed: int = 0
    candidate_opened: int = 0
    detailed_opened: int = 0
    candidate_reads: int = 0
    candidate_file_searches: int = 0
    detailed_reads: int = 0
    detailed_file_searches: int = 0
    trigger_bytes: list[int] = field(default_factory=list)
    result_bytes: list[int] = field(default_factory=list)
    result_tokens: list[int] = field(default_factory=list)
    total_matches: list[int] = field(default_factory=list)
    matching_files: list[int] = field(default_factory=list)
    detailed_files: list[int] = field(default_factory=list)
    candidate_files: list[int] = field(default_factory=list)
    representative_entries: list[int] = field(default_factory=list)
    tail_entries: list[int] = field(default_factory=list)
    followup_calls: list[int] = field(default_factory=list)
    followup_exact_searches: list[int] = field(default_factory=list)
    followup_reads: list[int] = field(default_factory=list)
    followup_result_tokens: list[int] = field(default_factory=list)
    investigation_result_tokens: list[int] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class JobTelemetryStats:
    dispatches: int = 0
    dispatch_errors: int = 0
    owners: Counter = field(default_factory=Counter)
    handoffs: Counter = field(default_factory=Counter)
    owner_roundtrip_ms: list[float] = field(default_factory=list)
    requested_wait_s: list[float] = field(default_factory=list)
    effective_wait_s: list[float] = field(default_factory=list)
    manager_launch_ms: list[float] = field(default_factory=list)
    manager_start_impl_ms: list[float] = field(default_factory=list)
    owner_transport_overhead_ms: list[float] = field(default_factory=list)
    manager_stop_impl_ms: list[float] = field(default_factory=list)
    job_runtime_s: list[float] = field(default_factory=list)
    exit_reasons: Counter = field(default_factory=Counter)
    stop_requests: int = 0
    stop_escalations: int = 0
    interruptions: Counter = field(default_factory=Counter)
    manager_starts: int = 0
    manager_recovered: int = 0
    manager_disconnects: int = 0
    disconnect_ops: Counter = field(default_factory=Counter)
    manager_invalid_requests: int = 0
    manager_request_errors: int = 0
    job_status_calls: int = 0
    job_status_wait_calls: int = 0
    job_status_running_after_wait: int = 0
    job_status_state_ms: list[float] = field(default_factory=list)
    job_status_wait_state_ms: list[float] = field(default_factory=list)


@dataclass
class RunCommandWorkflowStats:
    """Cross-event run_command policy/lifecycle analysis."""

    tool_calls: int = 0
    tool_results: int = 0
    result_errors: int = 0
    successful_dispatches: int = 0
    dispatch_errors: int = 0
    not_dispatched_errors: int = 0
    policy_modes: Counter = field(default_factory=Counter)
    outcomes: Counter = field(default_factory=Counter)
    not_dispatched_error_reasons: Counter = field(default_factory=Counter)

    dispatch_result_linked: int = 0
    dispatch_job_start_linked: int = 0
    dispatch_owner_timing_linked: int = 0
    synchronous_exit_linked: int = 0
    synchronous_exit_expected: int = 0
    result_without_call: int = 0
    dispatch_without_call: int = 0
    call_without_result: int = 0

    auto_matches: int = 0
    auto_warmup_finished: int = 0
    auto_handed_off: int = 0
    auto_terminal_observed: int = 0
    auto_terminal_analysis_eligible: int = 0
    auto_would_finish_within_original_wait: int = 0
    auto_would_timeout_anyway: int = 0
    auto_initial_wait_released_s: float = 0.0
    auto_jobs_with_status: int = 0
    auto_status_calls: int = 0
    auto_first_status_states: Counter = field(default_factory=Counter)
    auto_first_status_same_turn: int = 0
    auto_first_status_different_turn: int = 0
    auto_first_status_unknown_turn: int = 0
    auto_jobs_with_intervening_non_status_calls: int = 0
    auto_intervening_tools: Counter = field(default_factory=Counter)
    auto_terminal_collection_lag_s: list[float] = field(default_factory=list)
    auto_status_state_ms: list[float] = field(default_factory=list)
    auto_status_waited_s: list[float] = field(default_factory=list)

    output_shaping_reasons: Counter = field(default_factory=Counter)
    output_shaping_legacy_unclassified: int = 0
    auto_rule_matches: Counter = field(default_factory=Counter)
    auto_rule_handoffs: Counter = field(default_factory=Counter)


@dataclass
class ExactSearchStats:
    dispatches: int = 0
    summaries: int = 0
    pipelines: Counter = field(default_factory=Counter)
    errors: int = 0
    strategies: Counter = field(default_factory=Counter)
    budget_outcomes: Counter = field(default_factory=Counter)
    error_codes: Counter = field(default_factory=Counter)
    rg_calls_total: int = 0
    auto_context: int = 0
    impl_ms: list[float] = field(default_factory=list)
    rg_subprocess_ms: list[float] = field(default_factory=list)
    rg_parse_ms: list[float] = field(default_factory=list)
    collect_ms: list[float] = field(default_factory=list)
    context_attach_ms: list[float] = field(default_factory=list)
    adaptive_ms: list[float] = field(default_factory=list)
    budget_ms: list[float] = field(default_factory=list)
    rg_stdout_chars: list[int] = field(default_factory=list)
    rg_stdout_bytes: list[int] = field(default_factory=list)
    rg_wall_ms: list[float] = field(default_factory=list)
    stream_cpu_ms: list[float] = field(default_factory=list)
    glob_cache_hits: list[int] = field(default_factory=list)
    glob_cache_misses: list[int] = field(default_factory=list)
    glob_rejected_files: list[int] = field(default_factory=list)
    glob_rejected_events: list[int] = field(default_factory=list)
    adaptive_retained_match_events: list[int] = field(default_factory=list)
    rg_events: list[int] = field(default_factory=list)
    rg_match_events: list[int] = field(default_factory=list)
    rg_context_events: list[int] = field(default_factory=list)
    collect_glob_checks: list[int] = field(default_factory=list)
    collect_glob_rejected: list[int] = field(default_factory=list)
    accepted_matches: list[int] = field(default_factory=list)
    accepted_files: list[int] = field(default_factory=list)
    returned_entries: list[int] = field(default_factory=list)
    adaptive_match_events: list[int] = field(default_factory=list)
    adaptive_glob_checks: list[int] = field(default_factory=list)
    events_per_accepted_match: list[float] = field(default_factory=list)
    chars_per_returned_entry: list[float] = field(default_factory=list)
    bytes_per_returned_entry: list[float] = field(default_factory=list)


@dataclass
class Stats:
    records: int = 0
    startups: int = 0
    events: Counter = field(default_factory=Counter)
    methods: Counter = field(default_factory=Counter)
    tools: Counter = field(default_factory=Counter)
    clients: Counter = field(default_factory=Counter)
    commands: Counter = field(default_factory=Counter)
    areas: Counter = field(default_factory=Counter)
    per_day: Counter = field(default_factory=Counter)
    per_hour: Counter = field(default_factory=Counter)
    durations: dict = field(default_factory=lambda: defaultdict(list))
    errors: list = field(default_factory=list)
    # From the single-line tool_call / tool_result / job_exit records
    # (2026-09-13 on; earlier windows leave these empty).
    results: Counter = field(default_factory=Counter)  # tool -> sized results
    result_tokens: dict = field(default_factory=lambda: defaultdict(list))
    call_durations: dict = field(default_factory=lambda: defaultdict(list))
    truncated: Counter = field(default_factory=Counter)  # tool -> truncated=true
    tool_errors: Counter = field(default_factory=Counter)  # "tool: class" -> n
    error_codes: Counter = field(default_factory=Counter)  # "tool: stable_code" -> n
    read_file_requests: Counter = field(default_factory=Counter)
    read_file_outcomes: Counter = field(default_factory=Counter)
    read_file_lines_clipped: int = 0
    list_files_requests: Counter = field(default_factory=Counter)
    tool_config_variants: dict = field(default_factory=lambda: defaultdict(Counter))
    tool_config_latest: dict[str, str] = field(default_factory=dict)
    background_jobs: int = 0
    job_exits: Counter = field(default_factory=Counter)  # exit code / signal -> n
    turn_calls: Counter = field(default_factory=Counter)  # tunnel turn -> calls
    indexed: IndexedContextStats = field(default_factory=IndexedContextStats)
    adaptive: AdaptiveDiscoveryStats = field(default_factory=AdaptiveDiscoveryStats)
    jobs: JobTelemetryStats = field(default_factory=JobTelemetryStats)
    run_command: RunCommandWorkflowStats = field(
        default_factory=RunCommandWorkflowStats
    )
    exact_search: ExactSearchStats = field(default_factory=ExactSearchStats)
