"""scripts/weekly_usage.py: journal latency without test traffic, which
tools are judged, the usage baseline and the checks. No journal is read."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from scripts.weekly_scope import Limits, Runner
from scripts.weekly_usage import (
    DOCUMENTED,
    journal_latency,
    latency_checks,
    latest_usage_baseline,
    usage_check,
    usage_checks,
)
from tests.scripts.weekly_fakes import T0, FakeHost, inner

LINES = [
    'a INFO: event=tool_call call=c1 tool=read_file client=openai-mcp args_chars=9 args={"path":"/x"}',
    "a INFO: event=tool_result call=c1 tool=read_file client=openai-mcp duration_ms=4.0 is_error=False",
    'a INFO: event=tool_call call=c2 tool=read_file client=mcp args={"path":"/tmp/e2e-smoke-1/a"}',
    "a INFO: event=tool_result call=c2 tool=read_file client=mcp duration_ms=900.0 is_error=False",
    'a INFO: event=tool_call call=c3 tool=read_file client=openai-mcp args={"path":"/y"}',
    "a INFO: event=tool_result call=c3 tool=read_file client=openai-mcp duration_ms=6.0 is_error=False",
    "a INFO: event=tool_result call=c4 tool=job_status client=openai-mcp duration_ms=50000.0 x=1",
]


def test_journal_latency_leaves_out_nonce_marked_calls() -> None:
    table, tests = journal_latency(LINES)
    assert tests == 1
    assert table == {
        "job_status": {"n": 1, "p50_ms": 50000.0, "p95_ms": 50000.0},
        "read_file": {"n": 2, "p50_ms": 4.0, "p95_ms": 6.0},
    }


def row(n: int, p95: float) -> dict[str, float]:
    return {"n": n, "p50_ms": p95 / 2, "p95_ms": p95}


def test_only_server_bound_tools_with_enough_calls_are_judged() -> None:
    base = {
        "read_file": row(100, 20.0),
        "list_files": row(100, 20.0),
        "write_file": row(10, 20.0),
    }
    now = {
        "read_file": row(100, 80.0),
        "list_files": row(100, 5000.0),
        "write_file": row(100, 900.0),
        "async_probe_wait": row(44, 12003.0),
    }
    checks = {c.name: c for c in latency_checks(now, base)}
    assert "journal async_probe_wait" not in checks  # not one of the tools
    assert checks["journal read_file"].level == "warn"  # limit 20 * 1.25 + 50 = 75
    assert checks["journal list_files"].level == "ok"  # the tree decides its time
    assert checks["journal write_file"].level == "ok"  # too few baseline calls


def test_usage_needs_enough_traffic_to_judge() -> None:
    check = usage_check({"steps": {"steps": 100}, "job_polling": {}}, DOCUMENTED)
    assert check.level == "ok" and "too little ChatGPT traffic" in check.detail


def test_usage_warns_on_more_solo_polls_or_excess() -> None:
    steps = {
        "steps": 3000,
        "calls_per_step": 1.25,
        "steps_per_turn_median": 18,
        "steps_per_turn_p90": 90,
    }
    fine = {"solo_share_of_steps": 0.17, "excess_over_minimum": 90}
    assert usage_check({"steps": steps, "job_polling": fine}, DOCUMENTED).level == "ok"
    share = {"solo_share_of_steps": 0.30, "excess_over_minimum": 90}
    assert (
        usage_check({"steps": steps, "job_polling": share}, DOCUMENTED).level == "warn"
    )
    excess = {"solo_share_of_steps": 0.17, "excess_over_minimum": 273}
    check = usage_check({"steps": steps, "job_polling": excess}, DOCUMENTED)
    assert (
        check.level == "warn" and "excess 91.0/1k steps (baseline 29.5)" in check.detail
    )


def test_the_usage_baseline_is_the_newest_file_with_step_metrics(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "docs" / "usage-baselines"
    folder.mkdir(parents=True)
    (folder / "2026-09-27.json").write_text(json.dumps({"tools": {}}), encoding="utf-8")
    assert latest_usage_baseline(tmp_path) == DOCUMENTED
    with_steps = {
        "steps": {"steps": 2000},
        "job_polling": {
            "solo_share_of_steps": 0.2,
            "solo_at_max_share": 0.9,
            "excess_over_minimum": 40,
        },
    }
    (folder / "2026-10-04.json").write_text(json.dumps(with_steps), encoding="utf-8")
    base = latest_usage_baseline(tmp_path)
    assert base["source"] == "docs/usage-baselines/2026-10-04.json"
    assert base["excess_per_1k_steps"] == 20.0


def fake_usage(data: dict):
    def effect(argv: Sequence[str]) -> None:
        args = inner(argv)
        Path(args[args.index("--out") + 1]).write_text(
            json.dumps(data), encoding="utf-8"
        )

    return effect


def test_usage_checks_record_the_journal_baseline_on_the_first_run(
    tmp_path: Path,
) -> None:
    data = {
        "window": ["a", "b"],
        "journal": {"read_file": row(50, 10.0)},
        "test_calls_excluded": 12,
        "usage": {"steps": {"steps": 10}, "job_polling": {}},
    }
    host = FakeHost(plans=[(20.0, 0, fake_usage(data))] * 2)
    (tmp_path / "run").mkdir()
    run = Runner(
        host.as_host(), Limits(), "r", tmp_path / "run", {}, deadline=T0 + 10_800
    )
    first = usage_checks(
        run, tmp_path, tmp_path, "2026-09-21 00:10:00", "2026-09-28 00:10:00"
    )
    assert any(
        c.detail.startswith("journal baseline recorded; 12 e2e- test calls")
        for c in first
    )
    args = inner(host.spawned[0])
    assert args[args.index("--since") + 1] == "2026-09-21 00:10:00"
    second = usage_checks(run, tmp_path, tmp_path, "x", "y")
    assert any(
        c.detail.startswith("journal compared with the recorded baseline")
        for c in second
    )
