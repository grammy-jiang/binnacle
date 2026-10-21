"""E2.1: verify opaque E2 selection and restore private call-sequence metadata.

All raw MCP source, command, workdir, request hashes, identifiers and result
text remain on their originating host. Neither user task nor historic source
state is inferred from command fragments. Original commands are NEVER run.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import datetime as dt
import hashlib
import hmac
import itertools
import json
import os
import re
import stat
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

if __package__:
    from .lsp_e01_patterns import LABELS
    from .lsp_e01_trace import (
        Corpus,
        _events,
        _observer,
        _resolve_terminals,
        _time,
    )
    from .lsp_e02_private import (
        DIR_FLAGS,
        _atomic_publish,
        _owned_directory,
        _read_owned_file,
    )
    from .lsp_e02_selection import STRATA, episodes
    from .lsp_e21_evidence import (
        _case_fingerprint,
        _content_commitments,
        _git_evidence,
        _task_fields,
    )
else:
    from lsp_e01_patterns import LABELS
    from lsp_e01_trace import (
        Corpus,
        _events,
        _observer,
        _resolve_terminals,
        _time,
    )
    from lsp_e02_private import (
        DIR_FLAGS,
        _atomic_publish,
        _owned_directory,
        _read_owned_file,
    )
    from lsp_e02_selection import STRATA, episodes
    from lsp_e21_evidence import (
        _case_fingerprint,
        _content_commitments,
        _git_evidence,
        _task_fields,
    )

BATCH_SCHEMA = "binnacle-development-intelligence-e2-local-manifest/1"
REVIEW_SCHEMA = "binnacle-development-intelligence-e21-private/2"
VALID_OUTCOMES = frozenset(
    {
        "unfinished",
        "error",
        "result",
        "invalid_chronology",
        "ambiguous_terminal",
        "invalid_result",
    }
)
KEY_NAME = "e02-local-key.bin"


@contextlib.contextmanager
def existing_owner_private(directory: Path) -> Iterator[int]:
    """Open existing directory without writes, symlink follow or creation."""
    root = directory.expanduser()
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("invalid private directory")
    fd = os.open("/", DIR_FLAGS)
    try:
        for part in root.parts[1:]:
            info = os.fstat(fd)
            if info.st_mode & 0o022 and not (
                info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            ):
                raise PermissionError("untrusted E2 parent")
            newfd = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = newfd
        info = os.fstat(fd)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
        ):
            raise PermissionError("untrusted E2 directory")
        yield fd
    finally:
        os.close(fd)


def _validate_manifest(data: Any, batch: str) -> tuple[dt.datetime, list[dict]]:
    if not isinstance(data, dict) or data.get("schema") != BATCH_SCHEMA:
        raise ValueError("E2 manifest schema mismatch")
    cutoff = _time(data.get("cutoff_utc"))
    if cutoff is None or type(data.get("seed")) is not int:
        raise ValueError("E2 metadata missing frozen cutoff/seed")
    records = data.get("cases")
    if not isinstance(records, list) or not 1 <= len(records) <= 100:
        raise ValueError("E2 invalid case population")
    seen = set()
    for i, entry in enumerate(records, 1):
        if not isinstance(entry, dict):
            raise TypeError("E2 invalid case shape")
        ref = entry.get("host_local_lookup")
        if not isinstance(ref, str) or re.fullmatch(r"[0-9a-f]{32}", ref) is None:
            raise ValueError("E2 malformed opaque ref")
        if (
            ref in seen
            or type(entry.get("case_index")) is not int
            or entry["case_index"] != i
        ):
            raise ValueError("E2 duplicate/misordered case")
        if (
            entry.get("schema") != BATCH_SCHEMA
            or entry.get("batch") != batch
            or entry.get("stratum") not in STRATA
            or type(entry.get("group_call_count")) is not int
            or entry["group_call_count"] < 1
            or type(entry.get("partial_subgoal_hint")) is not bool
            or entry.get("source_quality")
            not in ("complete_tool_inputs", "incomplete_tool_inputs")
            or entry.get("result_quality") not in ("delivered_only", "incomplete")
            or not isinstance(entry.get("call_start_windows"), dict)
            or entry.get("annotation_status") != "pending_independent_review"
        ):
            raise ValueError("E2 case schema/type mismatch")
        if any(
            not isinstance(name, str) or type(count) is not int or count < 0
            for name, count in entry["call_start_windows"].items()
        ):
            raise ValueError("E2 case window type mismatch")
        if (
            entry.get("replayability") != "R0_unverified"
            or entry.get("actual_user_task_verified") is not False
            or entry.get("independent_gold_verified") is not False
            or entry.get("original_source_snapshot_verified") is not False
        ):
            raise ValueError("E2 must not silently upgrade unreviewed evidence")
        seen.add(ref)
    return cutoff, records


def _host_reference(secret: bytes, group: tuple, key: tuple) -> str:
    # Identical to E2 writer's exact JSON canonicalization. Never exported.
    value = json.dumps([group, key], separators=(",", ":")).encode("utf-8")
    return hmac.new(secret, value, hashlib.sha256).hexdigest()[:32]


def _sequence(
    episode: Any,
    observed: list[Any],
    request_times: dict,
    excluded_unorderable: bool,
) -> dict:
    ordered = sorted(
        observed,
        key=lambda c: (float("inf") if c.when is None else c.when, c.key),
    )
    first_time = next((c.when for c in ordered if c.when is not None), None)
    allowed = {c.key for c in episode.calls}
    uncertain = (
        excluded_unorderable
        or any(c.when is None for c in observed)
        or any(c1.when == c2.when for c1, c2 in itertools.pairwise(ordered))
    )
    items = []
    for index, call in enumerate(ordered, 1):
        request_at = request_times.get(call.request_key)
        before_call = (
            request_at is not None and call.when is not None and request_at <= call.when
        )
        if not before_call:
            uncertain = True
        offset = (
            round(call.when - first_time, 3)
            if call.when is not None and first_time is not None
            else None
        )
        duration = (
            round(call.end_when - call.when, 3)
            if (
                call.end_when is not None
                and call.when is not None
                and call.end_when >= call.when
            )
            else None
        )
        items.append(
            {
                "index": index,
                "tool": call.tool,  # fixed tool label or "other", not private name
                "category_labels": sorted(call.categories & set(LABELS)),
                "request_tool_pair_verified": call.key in allowed and before_call,
                "request_arguments_matched": call.key in allowed,
                "request_time_precedes_call": before_call,
                "start_offset_s": offset,
                "result_duration_s": duration,
                "outcome": call.status if call.status in VALID_OUTCOMES else "unknown",
                "result_truncated": call.result_truncated,
                "exit_nonzero": (
                    None if call.result_exit is None else call.result_exit != 0
                ),
            }
        )
    return {
        "observed_calls": len(ordered),
        "paired_calls": len(allowed),
        "chronology_unambiguous": not uncertain,
        "excluded_undated_group_event": excluded_unorderable,
        "request_chronology_anomalies": sum(
            not item["request_time_precedes_call"] for item in items
        ),
        "tool_call_sequence": items,
    }


def recover(
    capture_dir: Path,
    observer_db: Path | None,
    private_dir: Path,
    batch: str,
    *,
    write_local_review: bool = False,
    require_existing_checkpoint: bool = False,
) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", batch):
        raise ValueError("invalid E2 batch label")
    with existing_owner_private(private_dir) as fd:
        secret = _read_owned_file(fd, KEY_NAME, max_bytes=32)
        if len(secret) != 32:
            raise ValueError("invalid E2 lookup key")
        raw = _read_owned_file(fd, f"{batch}.json", max_bytes=1024 * 1024)
        manifest = json.loads(raw)
    cutoff, cases = _validate_manifest(manifest, batch)
    mapping, ambiguous = _observer(observer_db)
    corpus = Corpus()
    _events(capture_dir, corpus, mapping, ambiguous, cutoff)
    _resolve_terminals(corpus)
    candidates, _missing = episodes(corpus)
    resolved: dict[str, Any] = {}
    for episode in candidates:
        ref = _host_reference(secret, episode.group, episode.calls[0].key)
        if ref in resolved:
            raise ValueError("ambiguous local E2 ref collision")
        resolved[ref] = episode
    counters = collections.Counter()
    records = []
    observed = collections.defaultdict(list)
    for call in corpus.calls.values():
        if call.group is not None:
            observed[call.group].append(call)
    # Request/tool arguments can agree even if two distinct tool calls
    # consumed one request identifier. Refuse that cardinality ambiguity.
    cardinality = collections.Counter(
        c.request_key for c in corpus.calls.values() if c.request_key is not None
    )
    selected_pairs = []
    for case in cases:
        ep = resolved.get(case["host_local_lookup"])
        if ep is None:
            raise ValueError("E2 case identity cannot be relinked")
        if (
            case["stratum"] != ep.stratum
            or case["group_call_count"] != len(ep.calls)
            or case["call_start_windows"] != dict(ep.window_counts)
            or case["source_quality"] != ep.source_quality
            or case["result_quality"] != ep.outcome_quality
            or case["partial_subgoal_hint"] is not ep.partial_goal_hint
            or case["evaluation_role"]
            != (
                "negative_control"
                if ep.stratum.startswith("negative_")
                else "candidate"
            )
        ):
            raise ValueError("E2 case metadata changed since selection")
        if any(cardinality[c.request_key] != 1 for c in ep.calls):
            raise ValueError("E2 request/call cardinality ambiguous")
        selected_pairs.append((case, ep))

    all_req_keys = {
        c.request_key
        for _, ep in selected_pairs
        for c in ep.calls
        if c.request_key is not None
    }
    selected_call_keys = {c.key for _, ep in selected_pairs for c in observed[ep.group]}
    taskfields, request_times = _task_fields(capture_dir, all_req_keys, cutoff)
    request_hmacs, result_hmacs = _content_commitments(
        capture_dir, selected_call_keys, all_req_keys, cutoff, secret
    )
    git_evidence = _git_evidence(
        capture_dir, {ep.group: ep for _, ep in selected_pairs}, cutoff
    )
    for case, ep in selected_pairs:
        ref = case["host_local_lookup"]
        counters["exact_case_recovered"] += 1
        counters[f"stratum:{ep.stratum}"] += 1
        seq = _sequence(
            ep,
            observed[ep.group],
            request_times,
            ep.group in corpus.unorderable_groups,
        )
        counters["request_chronology_anomalies"] += seq["request_chronology_anomalies"]
        if not seq["chronology_unambiguous"]:
            counters["sequence_order_uncertain"] += 1
        for call in observed[ep.group]:
            if call.status == "unfinished":
                counters["unfinished_calls"] += 1
            if call.status == "error" or (
                call.result_exit is not None and call.result_exit != 0
            ):
                counters["error_or_nonzero_calls"] += 1
            if call.result_truncated:
                counters["truncated_tool_outputs"] += 1
        if seq["observed_calls"] != seq["paired_calls"]:
            counters["group_contains_unpaired_calls"] += 1
        git = git_evidence.get(ep.group, {})
        counters["explicit_git_revision_query_results"] += git.get(
            "standalone_git_head_results", 0
        )
        counters["explicit_git_clean_status_results"] += git.get(
            "empty_git_porcelain_results", 0
        )
        records.append(
            {
                "case_index": case["case_index"],
                "host_local_lookup": ref,
                "stratum": ep.stratum,
                "candidate_only": True,
                "original_task_goal_verified": False,
                "historical_source_snapshot_verified": False,
                "independent_gold_verified": False,
                "replayability": "R0_unverified",
                "provisional_subgoal_hint": ep.partial_goal_hint,
                "source_input_quality": ep.source_quality,
                "tool_result_quality": ep.outcome_quality,
                "git_observation_only": git,
                # HMAC commits to the re-found input/outcome evidence without
                # printing identifiers, plaintext or a bare predictable hash.
                "local_evidence_fingerprint": _case_fingerprint(
                    secret, observed[ep.group], request_hmacs, result_hmacs
                ),
                **seq,
            }
        )
    if len(records) != len(cases):
        raise ValueError("E2 local manifest recovery incomplete")
    # User task field presence is not independent goal verification.
    flags = {
        "schema": REVIEW_SCHEMA,
        "batch": batch,
        "cutoff_utc": cutoff.isoformat(),
        "case_count": len(records),
        "task_field_presence": taskfields,
        "cases": records,
    }
    if write_local_review or require_existing_checkpoint:
        data = (
            json.dumps(flags, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode()
        filename = f"{batch}-e21-v2-review.json"
        if require_existing_checkpoint:
            with existing_owner_private(private_dir) as fd:
                saved = _read_owned_file(fd, filename, max_bytes=len(data))
            if not hmac.compare_digest(saved, data):
                raise ValueError("existing E2.1 checkpoint differs")
        if write_local_review:
            with _owned_directory(private_dir) as fd:
                _atomic_publish(fd, filename, data, allow_existing=True)

    return {
        "schema": REVIEW_SCHEMA,
        "scope": "read_only_original_mcp_trace_reconciliation",
        "privacy": "counts_only",
        "manifest_cases": len(cases),
        "exact_cases_recovered": counters["exact_case_recovered"],
        "sequence_order_uncertain": counters["sequence_order_uncertain"],
        "request_chronology_anomalies": counters["request_chronology_anomalies"],
        "groups_with_unpaired_calls": counters["group_contains_unpaired_calls"],
        "unfinished_calls": counters["unfinished_calls"],
        "error_or_nonzero_calls": counters["error_or_nonzero_calls"],
        "truncated_tool_outputs": counters["truncated_tool_outputs"],
        "explicit_git_revision_query_results": counters[
            "explicit_git_revision_query_results"
        ],
        "explicit_git_clean_status_results": counters[
            "explicit_git_clean_status_results"
        ],
        "selected_requests_with_nonempty_task_field": taskfields.get(
            "nonempty_task", 0
        ),
        "source_snapshots_verified": 0,
        "independent_task_goals_verified": 0,
        "gold_answers_verified": 0,
        "r2_r3_ready": 0,
        "sample_strata": {
            stratum: counters[f"stratum:{stratum}"]
            for stratum in sorted({case["stratum"] for case in cases})
        },
        "excluded_from_full_task_replay": len(records),
        "result_evidence": "as_delivered_mcp_only",
        "original_E2_source_content_integrity_unproven": True,
        "local_detailed_review_created": write_local_review,
        "limits": [
            "restored_sequence_is_not_original_user_task",
            "explicit_git_commit_output_is_not_clean_snapshot_certification",
            "original_uncommitted_state_not_recoverable_from_mcp_only",
            "opaque_linkage_is_not_proof_original_E2_input_bytes_unchanged",
            "no_historic_commands_executed",
            "no_model_step_or_token_causality",
        ],
    }


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, "E21_ARGUMENT_ERROR\n")


def main() -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--observer-db", type=Path)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--write-local-review", action="store_true")
    args = parser.parse_args()
    try:
        report = recover(
            args.capture_dir,
            args.observer_db,
            args.private_dir,
            args.batch,
            write_local_review=args.write_local_review,
        )
    except Exception as exc:  # noqa: BLE001 - no raw path/source in CLI errors
        print(f"E21_RECONCILIATION_FAILED:{type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
