"""Shared tool-call/result/config telemetry aggregation."""

from typing import Any

from binnacle.logstats_models import Stats


def analyze_tool_call(st: Stats, fields: dict[str, str], args: dict[str, Any]) -> None:
    tool = fields.get("tool")
    if tool == "read_file":
        start_line = args.get("start_line", 1)
        mode = "whole" if start_line == 1 and args.get("end_line") is None else "range"
        st.read_file_requests[mode] += 1
    elif tool == "list_files":
        st.list_files_requests["glob" if args.get("glob") else "list"] += 1


def analyze_tool_config(st: Stats, fields: dict[str, str]) -> None:
    tool = fields.get("tool", "?")
    values = " ".join(
        f"{key}={value}"
        for key, value in sorted(fields.items())
        if key not in {"event", "tool"}
    )
    st.tool_config_variants[tool][values] += 1
    st.tool_config_latest[tool] = values


def analyze_tool_result(st: Stats, fields: dict[str, str]) -> None:
    tool = fields.get("tool", "?")
    if fields.get("est_tokens", "").isdigit():
        st.results[tool] += 1
        st.result_tokens[tool].append(int(fields["est_tokens"]))
    if fields.get("truncated") == "true":
        st.truncated[tool] += 1
    try:
        st.call_durations[tool].append(float(fields["duration_ms"]))
    except (KeyError, ValueError):
        pass
    if fields.get("is_error") == "True":
        st.tool_errors[f"{tool}: {fields.get('error_class', '?')}"] += 1
        if code := fields.get("error_code"):
            st.error_codes[f"{tool}: {code}"] += 1
    if tool == "read_file" and fields.get("is_error") != "True":
        _analyze_read_file_result(st, fields)
    if fields.get("background_job") == "true":
        st.background_jobs += 1


def _analyze_read_file_result(st: Stats, fields: dict[str, str]) -> None:
    if kind := fields.get("kind"):
        st.read_file_outcomes[f"kind:{kind}"] += 1
    for key in ("truncated", "fits_in_one_call", "lossy"):
        if fields.get(key) == "true":
            st.read_file_outcomes[key] += 1
    if "next_start_line" in fields:
        st.read_file_outcomes["continuation"] += 1
    try:
        clipped = int(fields.get("lines_clipped", "0"))
    except ValueError:
        clipped = 0
    if clipped:
        st.read_file_outcomes["lines_clipped_results"] += 1
        st.read_file_lines_clipped += clipped
