"""Deterministic, task-agnostic E2 stratification over verified E1 call groups.

Never interprets a request group as a distinct development task or a model step.
The original group reference remains on the originating host only.
"""

from __future__ import annotations

import collections
import hashlib
from dataclasses import dataclass
from typing import Any

if __package__:
    from .lsp_e01_patterns import _windows
else:
    from lsp_e01_patterns import _windows


@dataclass(frozen=True)
class Episode:
    group: tuple[str, str]
    calls: tuple[Any, ...]
    stratum: str
    window_counts: tuple[tuple[str, int], ...]
    source_quality: str
    outcome_quality: str
    partial_goal_hint: bool
    snapshot_verified: bool = False
    task_goal_verified: bool = False


STRATA = (
    "change_navigation_chain",
    "search_read_chain",
    "structure_query",
    "change_inspection",
    "diagnostics",
    "testing",
    "navigation",
    "negative_polling",
    "negative_misc",
)
NEGATIVES = frozenset({"negative_polling", "negative_misc"})
PRIORITIES = {name: index for index, name in enumerate(STRATA)}


def reliable(call: Any, corpus: Any) -> bool:
    """Request fields and terminal evidence must not contradict the tool call."""
    if call.key in corpus.duplicate_calls or call.key in corpus.duplicate_terminals:
        return False
    if call.request_key is None or call.request_key in corpus.duplicate_requests:
        return False
    req = corpus.requests.get(call.request_key)
    if req is None or req != (call.raw_tool_name, call.arguments_sha):
        return False
    return call.status not in (
        "invalid_chronology",
        "ambiguous_terminal",
        "invalid_result",
    )


def episodes(corpus: Any) -> tuple[list[Episode], dict[str, int]]:
    observed: dict[tuple[str, str], list[Any]] = collections.defaultdict(list)
    verified: dict[tuple[str, str], list[Any]] = collections.defaultdict(list)
    missingness = collections.Counter()
    for call in corpus.calls.values():
        if call.group is None:
            missingness["unattributed_calls"] += 1
            continue
        observed[call.group].append(call)
        if reliable(call, corpus):
            verified[call.group].append(call)
        else:
            missingness["excluded_invalid_calls"] += 1

    results: list[Episode] = []
    for group, all_calls in observed.items():
        included = sorted(
            verified.get(group, []),
            key=lambda c: (float("inf") if c.when is None else c.when, c.key),
        )
        if not included:
            missingness["groups_without_valid_calls"] += 1
            continue
        if group in corpus.unorderable_groups or any(
            call.when is None for call in all_calls
        ):
            missingness["groups_unorderable"] += 1
            # Such a group may be examined for local category-level demand,
            # but cannot contribute positive sequence windows.
            windows = {}
        else:
            windows = _windows(included, all_calls).copy()
        window_counts = tuple(
            (key, value["windows"])
            for key, value in sorted(windows.items())
            if value["windows"]
        )
        labels = {label for call in included for label in call.categories}
        if any(k == "git_change_then_inspect" for k, _ in window_counts):
            label = "change_navigation_chain"
        elif any(k == "search_then_read" for k, _ in window_counts):
            label = "search_read_chain"
        elif "code_structure_query" in labels:
            label = "structure_query"
        elif "git_change" in labels:
            label = "change_inspection"
        elif "lint_typecheck" in labels:
            label = "diagnostics"
        elif "test" in labels:
            label = "testing"
        elif labels & {"text_search", "source_read_shell"} or any(
            c.tool in ("read_file", "search_text") for c in included
        ):
            label = "navigation"
        elif all(c.tool in ("job_status", "stop_job") for c in included):
            label = "negative_polling"
        else:
            label = "negative_misc"

        # Missing/shortened tool results cannot substantiate complete output
        # or query correctness. A nonzero exit is not independent task gold.
        quality = (
            "incomplete"
            if any(c.status != "result" or c.result_truncated for c in included)
            else "delivered_only"
        )
        source = (
            "complete_tool_inputs"
            if all(
                c.raw_state not in ("missing", "incomplete", "redacted")
                for c in included
            )
            else "incomplete_tool_inputs"
        )
        # This is only a proposed R1 annotation candidate, never an accepted
        # R1 task. A query can reveal a local subgoal, not the user prompt.
        hint = any(
            c.raw_state == "present"
            and c.tool in ("search_text", "run_command")
            and c.categories
            for c in included
        )
        results.append(
            Episode(group, tuple(included), label, window_counts, source, quality, hint)
        )
    return results, dict(sorted(missingness.items()))


def _ordering(group: tuple[str, str], seed: int) -> str:
    # Stable internal order; do not expose the digest or group values.
    value = repr((seed, group)).encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def sample(
    cases: list[Episode],
    *,
    limit: int = 20,
    minimum_negatives: int = 4,
    seed: int = 20261021,
) -> list[Episode]:
    if not 1 <= limit <= 100 or not 0 <= minimum_negatives <= limit:
        raise ValueError("invalid E2 sample limits")
    buckets: dict[str, list[Episode]] = {label: [] for label in STRATA}
    seen_groups = set()
    for item in cases:
        if item.group in seen_groups:
            raise ValueError("duplicate E2 request group")
        seen_groups.add(item.group)
        buckets[item.stratum].append(item)
    for seq in buckets.values():
        seq.sort(key=lambda item: _ordering(item.group, seed))

    selected: list[Episode] = []
    used: set[tuple[str, str]] = set()

    def choose(name: str) -> bool:
        for episode in buckets[name]:
            if episode.group not in used:
                selected.append(episode)
                used.add(episode.group)
                return True
        return False

    # Deliberately preserve negative controls when available; their absence
    # must not be made up by re-labeling a weak positive as a negative.
    for _ in range(minimum_negatives):
        for name in ("negative_polling", "negative_misc"):
            if len(selected) < limit and choose(name):
                break
    while len(selected) < limit:
        progressed = False
        for name in STRATA:
            if len(selected) >= limit:
                break
            progressed |= choose(name)
        if not progressed:
            break
    return selected


def summary(
    full: list[Episode], selected: list[Episode], missing: dict[str, int]
) -> dict:
    all_counts = collections.Counter(e.stratum for e in full)
    chosen_counts = collections.Counter(e.stratum for e in selected)
    source = collections.Counter(e.source_quality for e in selected)
    outcome = collections.Counter(e.outcome_quality for e in selected)
    return {
        "schema": "binnacle-development-intelligence-e2/1",
        "evidence": "retrospective_sampling_not_manual_task_validation",
        "privacy": "aggregate_only",
        "population_request_groups": len(full),
        "sample_request_groups": len(selected),
        "total_negative_controls": sum(all_counts[s] for s in NEGATIVES),
        "selected_negative_controls": sum(chosen_counts[s] for s in NEGATIVES),
        "population_strata": dict(sorted(all_counts.items())),
        "sample_strata": dict(sorted(chosen_counts.items())),
        "sample_input_quality": dict(sorted(source.items())),
        "sample_result_quality": dict(sorted(outcome.items())),
        "provisional_subgoal_hints": sum(e.partial_goal_hint for e in selected),
        "independent_task_goals_verified": sum(e.task_goal_verified for e in selected),
        "source_snapshots_verified": sum(e.snapshot_verified for e in selected),
        "r2_r3_replay_ready": 0,
        "missingness": missing,
        "limits": [
            "request_groups_are_not_independent_tasks",
            "labels_are_lexical_not_manual_ground_truth",
            "no_exact_historical_uncommitted_source_state",
            "no_agent_step_token_or_causal_savings_evidence",
            "r1_hints_are_provisional_not_verified_task_labels",
        ],
    }
