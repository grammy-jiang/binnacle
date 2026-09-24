"""Build deterministic Phase-3 replay corpus shards and merge them."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from binnacle.logstats import plain_fields

# fmt: off
TURN_FIELDS = ["source_id", "source_sha256", "trial_id", "scenario", "arm", "base_turn", "observed_blocking_wall_s", "waits", "observed_required_completions", "terminal_state", "correct", "same_prompt"]
WAIT_FIELDS = ["wait_index", "node_id", "job_id_hash", "requested_wait_s", "call_start_offset_s", "call_end_offset_s", "blocking_start_offset_s", "blocking_end_offset_s", "waited_s", "state", "job_exit_offset_s", "required_completion", "observed_completion"]
class CorpusError(RuntimeError):
    pass
class JournalWindowUnavailable(CorpusError):
    pass
def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CorpusError(f"missing JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise CorpusError(f"expected JSON object: {path}")
    return value
def _dump(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"
def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except FileNotFoundError as exc:
        raise CorpusError(f"missing source file: {path}") from exc
    return digest.hexdigest()
def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
def _num(value: Any, label: str) -> float:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError) as exc:
        raise CorpusError(f"{label} is not numeric") from exc
def _base(value: Any) -> str | None:
    return value.split("/", 1)[0] if isinstance(value, str) and value else None
def _off(value: float | None, origin: float) -> float | None:
    return None if value is None else round(value - origin, 6)
def _union(intervals: list[tuple[float, float]]) -> float:
    merged: list[list[float]] = []
    for start, end in sorted(x for x in intervals if x[1] > x[0]):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return round(sum(end - start for start, end in merged), 6)
def _contract(inventory: dict[str, Any]) -> None:
    contract = inventory.get("replay_contract")
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise CorpusError("inventory replay contract is not schema version 1")
    if contract.get("turn_fields") != TURN_FIELDS:
        raise CorpusError("inventory turn fields differ from frozen schema")
    if contract.get("wait_fields") != WAIT_FIELDS:
        raise CorpusError("inventory wait fields differ from frozen schema")
def _resolve(inventory_path: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw:
        raise CorpusError("inventory path value is missing")
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    roots = (Path.cwd(), *inventory_path.resolve().parents)
    return next(
        (root / path for root in roots if (root / path).exists()), Path.cwd() / path
    )
def _row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return tuple(
        str(row.get(key) or "") for key in ("source_id", "trial_id", "base_turn")
    )  # type: ignore[return-value]
def _slots(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = report.get("canonical_slots")
    if not isinstance(raw, list):
        raise CorpusError("canonical report has no canonical_slots list")
    out: dict[str, dict[str, Any]] = {}
    for slot in raw:
        if not isinstance(slot, dict) or not isinstance(slot.get("run_id"), str):
            raise CorpusError("canonical report has invalid slot")
        run_id = slot["run_id"]
        if run_id in out:
            raise CorpusError(f"duplicate canonical report run_id: {run_id}")
        out[run_id] = slot
    return out
def _canonical_rows(
    source_id: str,
    source_sha: str,
    frozen: dict[str, Any],
    slot: dict[str, Any],
    trial: dict[str, Any],
    trace: dict[str, Any],
) -> list[dict[str, Any]]:
    trial_id, scenario, arm = (frozen[k] for k in ("trial_id", "scenario", "arm"))
    for name, doc in (("trial.json", trial), ("trace.json", trace)):
        expected = (trial_id, scenario, arm)
        actual = (doc.get("run_id"), doc.get("scenario_id"), doc.get("arm"))
        if actual != expected:
            raise CorpusError(f"{trial_id}: {name} identity mismatch")
    tools = [x for x in trace.get("tools", []) if isinstance(x, dict)]
    jobs = {
        x["job_id"]: x
        for x in trace.get("jobs", [])
        if isinstance(x, dict) and isinstance(x.get("job_id"), str)
    }
    positive = []
    for call in tools:
        args = _mapping(call.get("args"))
        if (
            call.get("tool") == "job_status"
            and _num(args.get("wait_seconds", 0) or 0, f"{trial_id}: requested wait")
            > 0
        ):
            positive.append(call)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for call in positive:
        groups[_base(call.get("turn")) or "trial"].append(call)
    if not groups:
        groups[
            next((_base(x.get("turn")) for x in tools if _base(x.get("turn"))), None)
            or "trial"
        ] = []
    rows: list[dict[str, Any]] = []
    for turn, calls in sorted(groups.items()):
        same_turn = [
            x for x in tools if turn == "trial" or _base(x.get("turn")) == turn
        ]
        starts = [_num(x.get("start_s"), f"{trial_id}: tool start") for x in same_turn]
        origin = min(starts) if starts else 0.0
        waits, intervals, completed = [], [], set()
        ordered = sorted(
            calls,
            key=lambda x: (
                _num(x.get("start_s"), "wait start"),
                str(x.get("call_id") or ""),
            ),
        )
        for index, call in enumerate(ordered, 1):
            args = _mapping(call.get("args"))
            result = _mapping(call.get("result"))
            start, end = (
                _num(call.get(k), f"{trial_id}: {k}") for k in ("start_s", "end_s")
            )
            waited = _num(result.get("waited_s"), f"{trial_id}: waited_s")
            bs, be = call.get("blocking_start_s"), call.get("blocking_end_s")
            if waited > 0 and (bs is None or be is None):
                raise CorpusError(f"{trial_id}: positive wait lacks blocking interval")
            block_start = start if bs is None else _num(bs, "blocking_start_s")
            block_end = start if be is None else _num(be, "blocking_end_s")
            if end < start or block_end < block_start or waited < 0:
                raise CorpusError(f"{trial_id}: invalid wait interval")
            intervals.append((block_start - origin, block_end - origin))
            raw_job = args.get("job_id") or result.get("job_id")
            if not isinstance(raw_job, str) or not raw_job:
                raise CorpusError(f"{trial_id}: positive wait has no job id")
            job_hash, state = _hash(raw_job), result.get("state")
            observed = state == "exited"
            node_id = (
                call.get("node_id") if isinstance(call.get("node_id"), str) else None
            )
            required = node_id is not None
            if required and observed:
                completed.add(job_hash)
            job = jobs.get(raw_job)
            exit_s = job.get("end_s") if isinstance(job, dict) else None
            if exit_s is None and observed:
                exit_s = end
            exit_num = _num(exit_s, "job exit") if exit_s is not None else None
            waits.append({"wait_index": index, "node_id": node_id, "job_id_hash": job_hash, "requested_wait_s": _num(args.get("wait_seconds"), "requested wait"), "call_start_offset_s": _off(start, origin), "call_end_offset_s": _off(end, origin), "blocking_start_offset_s": _off(block_start, origin), "blocking_end_offset_s": _off(block_end, origin), "waited_s": waited, "state": state if isinstance(state, str) else "unknown", "job_exit_offset_s": _off(exit_num, origin), "required_completion": required, "observed_completion": observed})  # fmt: skip
        correct = slot.get("correctness_passed", frozen.get("correctness_passed"))
        same = slot.get("same_prompt_completion", frozen.get("same_prompt_completion"))
        rows.append({"source_id": source_id, "source_sha256": source_sha, "trial_id": trial_id, "scenario": scenario, "arm": arm, "base_turn": turn, "observed_blocking_wall_s": _union(intervals), "waits": waits, "observed_required_completions": len(completed), "terminal_state": trial.get("status") or frozen.get("trial_status") or trace.get("timing_status"), "correct": bool(correct) if correct is not None else None, "same_prompt": bool(same) if same is not None else None})  # fmt: skip
    return rows
def _extract_phase1(inventory_path: Path, inventory_sha: str, source: dict[str, Any]) -> dict[str, Any]:
    source_id = source["source_id"]
    report_path = _resolve(inventory_path, source.get("report_path"))
    expected_sha = source.get("sha256")
    actual_sha = _sha_file(report_path)
    if not isinstance(expected_sha, str) or actual_sha != expected_sha:
        raise CorpusError(f"{source_id}: report SHA-256 mismatch")
    slots, trials = _slots(_load(report_path)), source.get("trials")
    if not isinstance(trials, list) or source.get("trial_count") != len(trials):
        raise CorpusError(f"{source_id}: frozen trial inventory is inconsistent")
    rows: list[dict[str, Any]] = []
    for frozen in trials:
        if not isinstance(frozen, dict) or frozen.get("submitted") is not True:
            raise CorpusError(f"{source_id}: canonical inventory has unsubmitted slot")
        trial_id = frozen.get("trial_id")
        slot = slots.get(trial_id) if isinstance(trial_id, str) else None
        if slot is None:
            raise CorpusError(
                f"{source_id}: referenced canonical trial missing: {trial_id}"
            )
        if slot.get("submitted") is False:
            raise CorpusError(f"{source_id}: canonical report marks trial unsubmitted")
        if slot.get("arm") not in (None, frozen.get("arm")):
            raise CorpusError(f"{trial_id}: canonical report arm mismatch")
        evidence_dir = frozen.get("evidence_dir") or frozen.get("state_dir")
        root = (
            Path(evidence_dir).expanduser() if isinstance(evidence_dir, str) else Path()
        )
        if not (root / "trial.json").is_file() or not (root / "trace.json").is_file():
            raise CorpusError(
                f"{trial_id}: referenced canonical trial evidence is missing"
            )
        rows.extend(
            _canonical_rows(
                source_id,
                expected_sha,
                frozen,
                slot,
                _load(root / "trial.json"),
                _load(root / "trace.json"),
            )
        )
    rows.sort(key=_row_key)
    return {"schema_version": 1, "source_id": source_id, "kind": source.get("kind"), "status": "available", "inventory_sha256": inventory_sha, "source_sha256": expected_sha, "trial_count": len(trials), "row_count": len(rows), "rows": rows}  # fmt: skip
def _journal_entry(line: str) -> tuple[float, str, dict[str, str]] | None:
    parts = line.lstrip().split(maxsplit=1)
    if len(parts) != 2:
        return None
    try:
        ts = float(parts[0])
    except ValueError:
        return None
    at = parts[1].find("event=")
    if at < 0:
        return None
    payload = parts[1][at:]
    return ts, payload, plain_fields(payload)
def _read_journal(source: dict[str, Any]) -> str:
    service = source.get("service")
    if not isinstance(service, str):
        raise JournalWindowUnavailable("journal_service_missing")
    oldest, newest = (
        _num(source.get(k), k) for k in ("oldest_unix_s", "newest_unix_s")
    )
    proc = subprocess.run(["journalctl", "--user", "-u", service, "--since", f"@{oldest - 60:.6f}", "--until", f"@{newest + 60:.6f}", "-o", "short-unix", "--no-pager"], check=False, capture_output=True, text=True)  # fmt: skip
    if proc.returncode:
        raise JournalWindowUnavailable(f"journalctl_failed_rc_{proc.returncode}")
    return proc.stdout
def _extract_operational(inventory_sha: str, source: dict[str, Any], journal_text: str) -> dict[str, Any]:
    oldest, newest = (
        _num(source.get(k), k) for k in ("oldest_unix_s", "newest_unix_s")
    )
    expected = source.get("line_count")
    if not isinstance(expected, int):
        raise JournalWindowUnavailable("journal_line_count_missing")
    parsed = [x for line in journal_text.splitlines() if (x := _journal_entry(line))]
    timings = [
        x
        for x in parsed
        if oldest <= x[0] <= newest
        and x[2].get("event") == source.get("event_filter", "job_status_timing")
    ]
    if len(timings) != expected:
        raise JournalWindowUnavailable(
            f"frozen_window_line_count_mismatch_{expected}_{len(timings)}"
        )
    normalized = (
        "\n".join(f"{ts:.6f} {payload}" for ts, payload, _ in sorted(timings)) + "\n"
    )
    source_sha = _hash(normalized)
    starts: dict[str, tuple[float, dict[str, str]]] = {}
    ends: dict[str, tuple[float, dict[str, str]]] = {}
    exits: dict[str, float] = {}
    origins: dict[str, float] = {}
    for ts, _, fields in parsed:
        event, call = fields.get("event"), fields.get("call")
        if event == "tool_call" and call:
            starts[call] = (ts, fields)
            turn = _base(fields.get("turn"))
            if turn:
                origins[turn] = min(ts, origins.get(turn, ts))
        elif event == "tool_result" and call:
            ends[call] = (ts, fields)
        elif event == "job_exit" and fields.get("job_id"):
            exits[fields["job_id"]] = ts
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    terminal: dict[str, str] = {}
    for timing_ts, _, fields in timings:
        requested = _num(
            fields.get("wait_requested_s", 0), "operational requested wait"
        )
        if requested <= 0:
            continue
        call = fields.get("call")
        if not call or call not in starts or call not in ends:
            raise JournalWindowUnavailable("positive_wait_missing_tool_call_pair")
        start, call_fields = starts[call]
        end, result_fields = ends[call]
        turn = (
            _base(fields.get("turn"))
            or _base(call_fields.get("turn"))
            or f"call:{call}"
        )
        origin = origins.get(turn, start)
        waited = _num(fields.get("waited_s"), "operational waited_s")
        if waited < 0:
            raise JournalWindowUnavailable("negative_operational_wait")
        block_end = min(end, start + waited)
        job_id = fields.get("job_id")
        if not job_id:
            raise JournalWindowUnavailable("positive_wait_missing_job_id")
        state = fields.get("state") or result_fields.get("state") or "unknown"
        exit_s = exits.get(job_id, end if state == "exited" else None)
        groups[turn].append({"wait_index": 0, "node_id": None, "job_id_hash": _hash(job_id), "requested_wait_s": requested, "call_start_offset_s": _off(start, origin), "call_end_offset_s": _off(end, origin), "blocking_start_offset_s": _off(start, origin), "blocking_end_offset_s": _off(block_end, origin), "waited_s": waited, "state": state, "job_exit_offset_s": _off(exit_s, origin), "required_completion": False, "observed_completion": state == "exited", "_timing_ts": timing_ts})  # fmt: skip
        terminal[turn] = state
    rows = []
    for turn, waits in groups.items():
        waits.sort(key=lambda x: (x["call_start_offset_s"], x["_timing_ts"]))
        intervals = []
        for index, wait in enumerate(waits, 1):
            wait.pop("_timing_ts")
            wait["wait_index"] = index
            intervals.append(
                (
                    float(wait["blocking_start_offset_s"]),
                    float(wait["blocking_end_offset_s"]),
                )
            )
        turn_hash = _hash(turn)
        rows.append({"source_id": source["source_id"], "source_sha256": source_sha, "trial_id": f"operational-{turn_hash[:16]}", "scenario": "operational", "arm": "historical", "base_turn": f"turn-{turn_hash[:16]}", "observed_blocking_wall_s": _union(intervals), "waits": waits, "observed_required_completions": 0, "terminal_state": terminal[turn], "correct": None, "same_prompt": None})  # fmt: skip
    rows.sort(key=_row_key)
    return {"schema_version": 1, "source_id": source["source_id"], "kind": source.get("kind"), "status": "available", "inventory_sha256": inventory_sha, "source_sha256": source_sha, "source_window": {"oldest_unix_s": source.get("oldest_unix_s"), "newest_unix_s": source.get("newest_unix_s"), "line_count": expected}, "trial_count": len(rows), "row_count": len(rows), "rows": rows}  # fmt: skip
def extract_source(inventory_path: Path, source_id: str, *, journal_text: str | None = None) -> dict[str, Any]:
    inventory = _load(inventory_path)
    _contract(inventory)
    inventory_sha = _sha_file(inventory_path)
    sources = inventory.get("sources")
    matches = (
        [x for x in sources if isinstance(x, dict) and x.get("source_id") == source_id]
        if isinstance(sources, list)
        else []
    )
    if len(matches) != 1:
        raise CorpusError(
            f"source_id must match exactly one frozen source: {source_id}"
        )
    source = matches[0]
    if source.get("kind") == "phase1-macro-report":
        return _extract_phase1(inventory_path, inventory_sha, source)
    if source.get("kind") != "operational-journal":
        raise CorpusError(f"{source_id}: unsupported source kind")
    if source.get("status") != "available":
        reason = "inventory_window_unavailable"
    else:
        try:
            return _extract_operational(
                inventory_sha,
                source,
                journal_text if journal_text is not None else _read_journal(source),
            )
        except JournalWindowUnavailable as exc:
            reason = str(exc)
    return {"schema_version": 1, "source_id": source_id, "kind": source.get("kind"), "status": "unavailable", "reason": reason, "inventory_sha256": inventory_sha, "source_sha256": None, "trial_count": 0, "row_count": 0, "rows": []}  # fmt: skip
def _validate_row(row: dict[str, Any], source_id: str) -> None:
    if set(row) != set(TURN_FIELDS) or row.get("source_id") != source_id:
        raise CorpusError(f"{source_id}: row differs from frozen schema")
    waits = row.get("waits")
    if not isinstance(waits, list) or any(
        not isinstance(wait, dict) or set(wait) != set(WAIT_FIELDS) for wait in waits
    ):
        raise CorpusError(f"{source_id}: wait differs from frozen schema")
def merge_shards(inventory_path: Path, shards_dir: Path, output_path: Path, report_path: Path) -> dict[str, Any]:
    inventory = _load(inventory_path)
    _contract(inventory)
    inventory_sha = _sha_file(inventory_path)
    sources = inventory.get("sources")
    if not isinstance(sources, list):
        raise CorpusError("inventory sources list is missing")
    rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    valid_sources = sorted(
        (x for x in sources if isinstance(x, dict)),
        key=lambda x: str(x.get("source_id") or ""),
    )
    for source in valid_sources:
        source_id = source.get("source_id")
        if not isinstance(source_id, str):
            raise CorpusError("inventory source has no source_id")
        path = shards_dir / f"{source_id}.json"
        if not path.is_file():
            raise CorpusError(f"missing shard for frozen source: {source_id}")
        shard = _load(path)
        if (
            shard.get("source_id") != source_id
            or shard.get("inventory_sha256") != inventory_sha
        ):
            raise CorpusError(f"{source_id}: shard identity mismatch")
        if shard.get("status") == "unavailable":
            if source.get("kind") != "operational-journal":
                raise CorpusError(
                    f"{source_id}: mandatory canonical shard is unavailable"
                )
            summaries.append(shard)
            continue
        if shard.get("status") != "available":
            raise CorpusError(f"{source_id}: invalid shard status")
        if source.get("kind") == "phase1-macro-report" and shard.get(
            "source_sha256"
        ) != source.get("sha256"):
            raise CorpusError(f"{source_id}: shard source SHA-256 mismatch")
        shard_rows = shard.get("rows")
        if not isinstance(shard_rows, list):
            raise CorpusError(f"{source_id}: shard rows is not a list")
        for row in shard_rows:
            if not isinstance(row, dict):
                raise CorpusError(f"{source_id}: shard row is not an object")
            _validate_row(row, source_id)
            if row["source_sha256"] != shard.get("source_sha256"):
                raise CorpusError(f"{source_id}: row source SHA-256 mismatch")
            rows.append(row)
        summaries.append(shard)
    rows.sort(key=_row_key)
    corpus = {"schema_version": 1, "fields": TURN_FIELDS, "wait_fields": WAIT_FIELDS, "rows": rows}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_dump(corpus), encoding="utf-8")
    corpus_sha = _sha_file(output_path)
    waits_total = sum(len(row["waits"]) for row in rows)
    canonical_trials = len({(row["source_id"], row["trial_id"]) for row in rows if row["scenario"] != "operational"})
    lines = ["# Phase-3 replay corpus", "", "- Schema version: 1.", f"- Corpus SHA-256: `{corpus_sha}`.", f"- Source inventory SHA-256: `{inventory_sha}`.", f"- Replay rows: {len(rows)}.", f"- Canonical trials represented: {canonical_trials}.", f"- Positive wait records: {waits_total}.", "", "## Sources", "", "| Source | Status | Rows | Waits | Source SHA-256 | Window |", "| --- | --- | ---: | ---: | --- | --- |"]  # fmt: skip
    excluded = []
    for shard in summaries:
        raw_rows = shard.get("rows")
        report_rows: list[dict[str, Any]] = [x for x in raw_rows if isinstance(x, dict)] if isinstance(raw_rows, list) else []
        count = 0
        for report_row in report_rows:
            raw_waits = report_row.get("waits")
            if isinstance(raw_waits, list):
                count += len(raw_waits)
        window = shard.get("source_window")
        window_text = (
            f"{window.get('oldest_unix_s')}..{window.get('newest_unix_s')} ({window.get('line_count')} timing lines)"
            if isinstance(window, dict)
            else "-"
        )
        lines.append(
            f"| {shard.get('source_id')} | {shard.get('status')} | {len(report_rows)} | {count} | "
            f"`{shard.get('source_sha256') or '-'}` | {window_text} |"
        )
        if shard.get("status") == "unavailable":
            excluded.append(
                f"- `{shard.get('source_id')}`: {shard.get('reason', 'unavailable')}."
            )
    lines += ["", "## Exclusions", "", *(excluded or ["- None."]), "", "## Privacy", ""]
    lines += ["- Conversation prose and irrelevant tool arguments are excluded.", "- Job identifiers are stored only as SHA-256 hex digests.", "- Operational turn identifiers are normalized to truncated SHA-256 labels.", ""]  # fmt: skip
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return corpus
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chat-scheduling-replay-corpus")
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract")
    extract.add_argument("--inventory", type=Path, required=True)
    extract.add_argument("--source-id", required=True)
    extract.add_argument("--output", type=Path, required=True)
    merge = commands.add_parser("merge")
    merge.add_argument("--inventory", type=Path, required=True)
    merge.add_argument("--shards-dir", type=Path, required=True)
    merge.add_argument("--output", type=Path, required=True)
    merge.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "extract":
        shard = extract_source(args.inventory, args.source_id)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(_dump(shard), encoding="utf-8")
        print(
            json.dumps(
                {
                    "source_id": shard["source_id"],
                    "status": shard["status"],
                    "rows": shard["row_count"],
                },
                sort_keys=True,
            )
        )
        return 0
    corpus = merge_shards(args.inventory, args.shards_dir, args.output, args.report)
    print(json.dumps({"rows": len(corpus["rows"])}, sort_keys=True))
    return 0
# fmt: on
if __name__ == "__main__":
    raise SystemExit(main())
