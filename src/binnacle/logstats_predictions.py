"""Join shadow run-command predictions to terminal outcomes."""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from binnacle.logstats_models import PredictionStats, Record
from binnacle.logstats_run_command import build_run_command_index

Fields = dict[str, str]
Parser = Callable[[str], Fields]
PREDICTORS = ("memory", "rules")


def _num(fields: Fields, key: str) -> float | None:
    try:
        return float(fields[key])
    except (KeyError, TypeError, ValueError):
        return None


def _bucket(runtime: float) -> str:
    return "short" if runtime < 10 else "medium" if runtime <= 60 else "long"


def _runtime(call: str, index: Any) -> float | None:
    row = index.dispatches.get(call)
    if row is None:
        return None
    job_id = row[1].get("job_id")
    if job_id and job_id in index.job_exits:
        found = _num(index.job_exits[job_id][1], "runtime_s")
        if found is not None:
            return found
    if call in index.tool_results:
        result = index.tool_results[call][1]
        return _num(result, "runtime_s") or _num(result, "duration_s")
    return None


def _positive(bucket: str, threshold: int) -> bool:
    return bucket in {"medium", "long"} if threshold == 10 else bucket == "long"


def _score(
    out: PredictionStats, predictor: str, predicted: str, runtime: float
) -> None:
    actual_bucket = _bucket(runtime)
    out.calibration[predictor][f"{predicted}->{actual_bucket}"] += 1
    for threshold in (10, 60):
        p = _positive(predicted, threshold)
        a = runtime >= 10 if threshold == 10 else runtime > 60
        cell = "tp" if p and a else "fp" if p else "fn" if a else "tn"
        out.confusion[f"{predictor}:{threshold}"][cell] += 1


def analyze_predictions(records: list[Record], fields: Parser) -> PredictionStats:
    """Join prediction events to terminal run-command outcomes by call/job id."""
    out = PredictionStats()
    index = build_run_command_index(records, fields)
    dispatches: dict[str, Fields] = {}
    for record in records:
        f = fields(record.body)
        if record.event == "tool_config":
            if f.get("tool") == "run_command" and "shadow_prediction" in f:
                out.filter_hash = f.get("filter_hash")
        elif record.event == "run_command_prediction":
            call = f.get("call")
            if not call:
                continue
            dispatches[call] = f
            out.dispatches += 1
            if record.timestamp:
                out.window_start = out.window_start or record.timestamp
                out.window_end = record.timestamp
            try:
                out.memory_store_keys = max(
                    out.memory_store_keys, int(f.get("memory_store_keys", "0"))
                )
            except ValueError:
                pass
            try:
                out.memory_sample_counts[int(f.get("memory_n", "0"))] += 1
            except ValueError:
                pass

    for call, prediction in dispatches.items():
        actual = _runtime(call, index)
        if actual is not None:
            out.outcomes += 1
        row: dict[str, Any] = {
            "call": call,
            "feature_hash": prediction.get("feature_hash", "-"),
            "shape_hash": prediction.get("shape_hash", "-"),
            "first_token_class": prediction.get("first_token_class", "-"),
            "actual_runtime_s": actual,
            "actual_bucket": _bucket(actual) if actual is not None else None,
        }
        for name in PREDICTORS:
            bucket = prediction.get(f"{name}_bucket")
            row[f"{name}_bucket"] = (
                bucket if bucket in {"short", "medium", "long"} else None
            )
            row[f"{name}_p90_s"] = _num(prediction, f"{name}_p90_s")
            if bucket not in {"short", "medium", "long"}:
                continue
            out.coverage[name] += 1
            if actual is not None:
                _score(out, name, bucket, actual)
        out.rows.append(row)
    return out


def _metrics(counter: Any) -> dict[str, Any]:
    tp, fp, tn, fn = (int(counter.get(k, 0)) for k in ("tp", "fp", "tn", "fn"))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def prediction_report(stats: PredictionStats) -> dict[str, Any]:
    """Return the JSON-safe prediction section and privacy-safe joined rows."""
    predictors = {
        name: {
            "coverage_n": int(stats.coverage[name]),
            "coverage": (
                stats.coverage[name] / stats.dispatches if stats.dispatches else 0.0
            ),
            "thresholds": {
                str(t): _metrics(stats.confusion[f"{name}:{t}"]) for t in (10, 60)
            },
            "calibration": dict(stats.calibration[name]),
        }
        for name in PREDICTORS
    }
    return {
        "dispatches": stats.dispatches,
        "outcomes": stats.outcomes,
        "window": {"start": stats.window_start, "end": stats.window_end},
        "filter_hash": stats.filter_hash,
        "predictors": predictors,
        "memory_store_keys": stats.memory_store_keys,
        "memory_sample_counts": {
            str(key): value for key, value in sorted(stats.memory_sample_counts.items())
        },
        "rows": stats.rows,
    }


def export_prediction_rows(stats: PredictionStats, path: Path) -> None:
    """Export privacy-safe joined rows as JSONL or CSV based on the suffix."""
    allowed = (
        "call",
        "feature_hash",
        "shape_hash",
        "first_token_class",
        "actual_runtime_s",
        "actual_bucket",
        "memory_bucket",
        "memory_p90_s",
        "rules_bucket",
        "rules_p90_s",
    )
    rows = [{key: row.get(key) for key in allowed} for row in stats.rows]
    if path.suffix.lower() == ".csv":
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=allowed)
            writer.writeheader()
            writer.writerows(rows)
        return
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def render_predictions(stats: PredictionStats) -> list[str]:
    if not stats.dispatches:
        return []
    report = prediction_report(stats)
    out = [
        "\npredictions:",
        (
            f"  dispatches={stats.dispatches} outcomes={stats.outcomes} "
            f"filter_hash={stats.filter_hash or '-'} "
            f"memory_store_keys={stats.memory_store_keys}"
        ),
    ]
    if stats.memory_sample_counts:
        out.append(
            "  memory samples: "
            + ", ".join(
                f"{key}:{value}"
                for key, value in sorted(stats.memory_sample_counts.items())
            )
        )
    for name in PREDICTORS:
        item = report["predictors"][name]
        out.append(
            f"  {name}: coverage={item['coverage_n']}/{stats.dispatches} "
            f"({100 * item['coverage']:.2f}%)"
        )
        for threshold in ("10", "60"):
            m = item["thresholds"][threshold]
            out.append(
                f"    threshold={threshold}s tp={m['tp']} fp={m['fp']} "
                f"tn={m['tn']} fn={m['fn']} precision={m['precision']:.3f} "
                f"recall={m['recall']:.3f} f1={m['f1']:.3f}"
            )
        if item["calibration"]:
            out.append(
                "    calibration: "
                + ", ".join(
                    f"{key}:{value}"
                    for key, value in sorted(item["calibration"].items())
                )
            )
    return out
