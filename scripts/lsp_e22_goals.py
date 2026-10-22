"""E2.2 independent source availability for host-local historical task goals.

Tool-call patterns and co-temporal files do NOT establish a human task.
The E2.1 evidence checkpoint must survive an identical retry before use.
Only aggregate counts and privacy-safe local classifications are produced.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING or __package__:
    from .lsp_e01_trace import Corpus, _events, _observer, _resolve_terminals
    from .lsp_e02_private import _atomic_publish, _owned_directory, _read_owned_file
    from .lsp_e02_selection import episodes
    from .lsp_e21_recovery import (
        KEY_NAME,
        _host_reference,
        _validate_manifest,
        existing_owner_private,
        recover,
    )
    from .lsp_e22_sessions import scan_independent_sessions
    from .lsp_e22_sources import available_documents, inputs_by_call
else:
    from lsp_e01_trace import Corpus, _events, _observer, _resolve_terminals
    from lsp_e02_private import _atomic_publish, _owned_directory, _read_owned_file
    from lsp_e02_selection import episodes
    from lsp_e21_recovery import (
        KEY_NAME,
        _host_reference,
        _validate_manifest,
        existing_owner_private,
        recover,
    )
    from lsp_e22_sessions import scan_independent_sessions
    from lsp_e22_sources import available_documents, inputs_by_call

REVIEW_SCHEMA = "binnacle-development-intelligence-e22-private/2"
PACKET_SUFFIX = "-e22-v2-goal-sources.json"
REASON_NAMES = (
    "no_original_chatmode_task_payload",
    "no_exact_independent_agent_session_link",
    "same_repo_documents_not_original_user_instruction",
    "historical_worktree_snapshot_unproven",
    "mtime_is_not_historical_authorship_proof",
)


def inspect_goals(
    capture_dir: Path,
    observer_db: Path | None,
    private_dir: Path,
    batch: str,
    *,
    home: Path | None = None,
    write_local_review: bool = False,
) -> dict:
    if re.fullmatch(r"[A-Za-z0-9_-]{1,48}", batch) is None:
        raise ValueError("invalid private batch label")
    home = home or Path.home()

    # This compare-and-retry operation checks the complete E2.1 request/result
    # HMAC checkpoint against its preexisting final private packet. If the
    # original packet is missing, do not silently establish a new E2.1 baseline.
    previous = private_dir / f"{batch}-e21-v2-review.json"
    with existing_owner_private(private_dir) as directory:
        checkpoint_bytes = _read_owned_file(
            directory, previous.name, max_bytes=2 * 1024 * 1024
        )
        key = _read_owned_file(directory, KEY_NAME, max_bytes=32)
        raw = _read_owned_file(directory, f"{batch}.json", max_bytes=1024 * 1024)
    if len(key) != 32:
        raise ValueError("invalid local case key")
    if not isinstance(json.loads(checkpoint_bytes), dict):
        raise TypeError("invalid E2.1 checkpoint packet")
    manifest = json.loads(raw)
    cutoff, cases = _validate_manifest(manifest, batch)
    previous_report = recover(
        capture_dir,
        observer_db,
        private_dir,
        batch,
        require_existing_checkpoint=True,
    )
    if previous_report["exact_cases_recovered"] != len(cases):
        raise ValueError("E2.1 checkpoint unavailable for all selected cases")

    mapping, ambiguous = _observer(observer_db)
    corpus = Corpus()
    _events(capture_dir, corpus, mapping, ambiguous, cutoff)
    _resolve_terminals(corpus)
    full, _missing = episodes(corpus)
    ref_to_episode = {_host_reference(key, e.group, e.calls[0].key): e for e in full}
    selected_pairs = []
    for entry in cases:
        candidate = ref_to_episode.get(entry["host_local_lookup"])
        if candidate is None or entry["stratum"] != candidate.stratum:
            raise ValueError("unreconciled private case")
        selected_pairs.append((entry, candidate))

    selected_calls = {c.key: c for _, episode in selected_pairs for c in episode.calls}
    arguments, input_counts = inputs_by_call(capture_dir, selected_calls, cutoff, home)
    agent_links, agent_counts = scan_independent_sessions(
        home, list(selected_calls.values()), cutoff
    )
    totals: collections.Counter[str] = collections.Counter()
    reason_counts: collections.Counter[str] = collections.Counter()
    records = []
    cache: dict = {}
    for case, episode in selected_pairs:
        repos = set()
        for call in episode.calls:
            evidence = arguments.get(call.key)
            if evidence:
                repos.update(evidence["repositories"])
        anchored = len(repos) == 1
        ambiguous_repo = len(repos) > 1
        docs = 0
        matched_id = False
        if anchored:
            repo = next(iter(repos))
            first = min(c.when for c in episode.calls if c.when is not None)
            context = (repo, first)
            if context not in cache:
                cache[context] = available_documents(repo, first)
            docs, document_refs, doc_errors = cache[context]
            totals["local_doc_scan_errors"] += sum(doc_errors.values())
            taskrefs = set()
            for c in episode.calls:
                evidence = arguments.get(c.key)
                if evidence and evidence["repositories"] == {repo}:
                    taskrefs.update(evidence["task_refs"])
            matched_id = bool(taskrefs & document_refs)
        unique_links = [
            agent_links[c.key] for c in episode.calls if c.key in agent_links
        ]
        exact_external = bool(unique_links)
        preceding_user = any(x["preceded_by_session_user_role"] for x in unique_links)
        if anchored:
            totals["cases_with_single_project_repository_anchor"] += 1
        if ambiguous_repo:
            totals["cases_with_multiple_project_repositories"] += 1
        if docs:
            totals["cases_with_mtime_window_document_leads"] += 1
        if matched_id:
            totals["cases_with_same_literal_task_id_in_mtime_window_document"] += 1
        if exact_external:
            totals["cases_with_compatible_local_agent_tool_signature"] += 1
        if preceding_user:
            totals["cases_with_agent_user_role_before_linked_tool"] += 1
        totals["selected_case_groups"] += 1
        reason_counts["missing_independent_human_task_statement"] += 1
        if not anchored:
            reason_counts["no_single_explicit_repository_anchor"] += 1
        if not exact_external:
            reason_counts["no_compatible_agent_tool_signature"] += 1
        records.append(
            {
                "case_index": case["case_index"],
                "host_local_lookup": case["host_local_lookup"],
                "stratum": episode.stratum,
                "project_repository_anchor": (
                    "unique"
                    if anchored
                    else "ambiguous"
                    if ambiguous_repo
                    else "absent"
                ),
                "mtime_window_document_candidate": bool(docs),
                "literal_task_id_in_document": matched_id,
                "compatible_agent_tool_signature_candidate": exact_external,
                "agent_user_role_before_tool": preceding_user,
                "independent_human_task_goal_verified": False,
                "original_chatmode_goal_available": False,
                "independent_gold_verified": False,
                "historical_source_snapshot_verified": False,
                "replayability": "R0_unverified",
                "classification": "independent_evidence_leads_only",
            }
        )
    if len(records) != len(cases):
        raise ValueError("E2.2 selection population mismatch")

    private_report = {
        "schema": REVIEW_SCHEMA,
        "batch": batch,
        "cutoff_utc": cutoff.isoformat(),
        "cases": records,
        "source_evidence_is_not_task_goal": True,
        "original_e2_bytes_not_frozen": True,
    }
    if write_local_review:
        body = (
            json.dumps(
                private_report,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        with _owned_directory(private_dir) as directory:
            _atomic_publish(directory, batch + PACKET_SUFFIX, body, allow_existing=True)
    return {
        "schema": REVIEW_SCHEMA,
        "scope": "independent_task_source_availability_not_replay",
        "privacy": "anonymous_aggregates_only",
        "cutoff_utc": cutoff.isoformat(),
        "selected_case_groups": len(records),
        "e21_checkpoint_revalidated": True,
        "local_source_leads": dict(sorted(totals.items())),
        "agent_session_corpus": dict(sorted(agent_counts.items())),
        "captured_input_quality": dict(sorted(input_counts.items())),
        "task_goal_evidence_reasons": dict(sorted(reason_counts.items())),
        "independent_human_task_goals_verified": 0,
        "source_snapshots_verified": 0,
        "gold_answers_verified": 0,
        "r2_r3_ready": 0,
        "original_e2_raw_content_integrity_unproven": True,
        "local_private_source_packet_created": write_local_review,
        "limits": list(REASON_NAMES),
    }


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, "E22_ARGUMENT_ERROR\n")


def main() -> int:
    p = SafeParser(description=__doc__)
    p.add_argument("--capture-dir", type=Path, required=True)
    p.add_argument("--observer-db", type=Path)
    p.add_argument("--private-dir", type=Path, required=True)
    p.add_argument("--batch", required=True)
    p.add_argument("--write-local-review", action="store_true")
    args = p.parse_args()
    try:
        report = inspect_goals(
            args.capture_dir,
            args.observer_db,
            args.private_dir,
            args.batch,
            write_local_review=args.write_local_review,
        )
    except Exception as exc:  # noqa: BLE001 - never print exception data paths/text
        print(f"E22_GOAL_SOURCE_FAILED:{type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
