"""Ripgrep execution and JSON parsing for exact search."""

import subprocess
import time
from pathlib import Path

import orjson

from binnacle.errors import CodedToolError
from binnacle.features.search.rg_env import (
    NO_CONFIG,
    accept_denied,
    rejection_message,
    rg_env,
)
from binnacle.features.search.search_text_telemetry import ExactSearchMetrics


def run_rg(
    root: Path,
    pattern: str,
    fixed_strings: bool,
    context: int,
    *,
    rg_bin: str,
    timeout_s: int,
    metrics: ExactSearchMetrics | None = None,
) -> tuple[list[dict], bool]:
    cmd = [rg_bin, NO_CONFIG, "--json", "--smart-case"]
    if fixed_strings:
        cmd.append("--fixed-strings")
    if context > 0:
        cmd += ["--context", str(context)]
    cmd += ["--regexp", pattern, str(root)]
    if metrics is not None:
        metrics.rg_calls += 1
    started_ns = time.perf_counter_ns()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            env=rg_env(),
        )
    except FileNotFoundError as exc:
        raise CodedToolError(
            "rg_missing",
            "ripgrep (rg) is not available; use run_command (grep -rn) instead.",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise CodedToolError(
            "rg_timeout",
            f"Search timed out after {timeout_s} s. Narrow the scope "
            "with a more specific path or a glob filter.",
        ) from exc
    finally:
        if metrics is not None:
            metrics.rg_subprocess_ms += ExactSearchMetrics.elapsed_ms(started_ns)

    if (
        proc.returncode == 2 or (proc.returncode not in (0, 1) and proc.stderr)
    ) and not accept_denied(proc.stderr, root):
        raise CodedToolError(
            "rg_rejected",
            rejection_message(proc.stderr),
        )

    if metrics is not None:
        metrics.rg_stdout_chars += len(proc.stdout)
    parse_started_ns = time.perf_counter_ns()
    events: list[dict] = []
    for line in proc.stdout.splitlines():
        try:
            event = orjson.loads(line)
        except orjson.JSONDecodeError:
            if metrics is not None:
                metrics.rg_bad_json += 1
            continue
        events.append(event)
        if metrics is not None:
            metrics.rg_events += 1
            kind = event.get("type")
            if kind == "match":
                metrics.rg_match_events += 1
            elif kind == "context":
                metrics.rg_context_events += 1
            elif kind == "begin":
                metrics.rg_begin_events += 1
    if metrics is not None:
        metrics.rg_parse_ms += ExactSearchMetrics.elapsed_ms(parse_started_ns)
    return events, proc.returncode == 1


def run_rg_compat(
    root: Path,
    pattern: str,
    fixed_strings: bool,
    context: int,
    metrics: ExactSearchMetrics | None = None,
    *,
    rg_bin: str,
    timeout_s: int,
) -> tuple[list[dict], bool]:
    return run_rg(
        root,
        pattern,
        fixed_strings,
        context,
        rg_bin=rg_bin,
        timeout_s=timeout_s,
        metrics=metrics,
    )
