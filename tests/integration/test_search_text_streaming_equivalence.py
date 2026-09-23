"""Streaming exact search preserves the materialized public result semantics."""

from __future__ import annotations

from pathlib import Path

import pytest

from binnacle.tools import search_text as st


def run_mode(monkeypatch, mode: str, pattern: str, path: Path, **kwargs):
    monkeypatch.setattr(st, "EXACT_EXECUTION", mode)
    return st.search_text_impl(
        pattern,
        str(path),
        kwargs.get("glob"),
        kwargs.get("fixed_strings", False),
        kwargs.get("context_lines"),
        kwargs.get("names_only", False),
        kwargs.get("max_results", 100),
        kwargs.get("line_numbers", False),
    ).structured_content


def by_file(payload: dict) -> dict:
    """The payload with its entries grouped by file, in path order.

    rg runs with its default parallel walker and no `--sort`, so which file
    it reports first depends on which worker thread finishes first. Neither
    pipeline sorts (order is not part of the contract, see the truncation
    test below), and two independent rg runs can therefore disagree on file
    order: measured 2026-09-24 on the Pi, 49 of 400 back-to-back pairs under
    CPU load differed in nothing but that. The sort is stable, so the line
    order inside a file -- which rg does fix -- is still compared.
    """
    return {**payload, "entries": sorted(payload["entries"], key=lambda e: e["file"])}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fixed_strings": True, "context_lines": 0},
        {"glob": "*.py", "context_lines": 1, "line_numbers": True},
        {"names_only": True, "glob": "*.py", "context_lines": 0},
    ],
)
def test_normal_exact_results_match_between_pipelines(tmp_path, monkeypatch, kwargs):
    (tmp_path / "a.py").write_text("before\nhit alpha\nafter\nhit beta\n")
    (tmp_path / "b.txt").write_text("hit text\n")

    materialized = run_mode(monkeypatch, "materialized", "hit", tmp_path, **kwargs)
    streaming = run_mode(monkeypatch, "streaming", "hit", tmp_path, **kwargs)

    assert by_file(streaming) == by_file(materialized)


def test_truncated_independent_rg_runs_preserve_contract_not_order(
    tmp_path, monkeypatch
):
    (tmp_path / "a.py").write_text("hit alpha\nhit beta\n")
    (tmp_path / "b.txt").write_text("hit text\n")

    materialized = run_mode(
        monkeypatch, "materialized", "hit", tmp_path, context_lines=0, max_results=2
    )
    streaming = run_mode(
        monkeypatch, "streaming", "hit", tmp_path, context_lines=0, max_results=2
    )

    # Separate rg invocations may traverse files in a different order; same-raw
    # reducer/property tests cover entry-order equivalence. Public truncation
    # semantics must remain identical here without imposing a new sort order.
    for payload in (materialized, streaming):
        assert payload["count"] == 3
        assert payload["truncated"] is True
        assert len(payload["entries"]) == 2
        assert payload["note"] == (
            "Showing first 2 of 3 matches; narrow the pattern, add a glob, "
            "or raise max_results."
        )


def test_auto_context_second_rg_matches(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text(
        "\n".join(
            [f"line {i}" for i in range(1, 15)]
            + ["unique needle"]
            + [f"tail {i}" for i in range(1, 15)]
        )
        + "\n"
    )
    materialized = run_mode(monkeypatch, "materialized", "unique needle", tmp_path)
    streaming = run_mode(monkeypatch, "streaming", "unique needle", tmp_path)
    assert streaming == materialized


def test_adaptive_result_matches_with_preaccepted_events(tmp_path, monkeypatch):
    for index in range(8):
        (tmp_path / f"file-{index:02d}.py").write_text(
            "\n".join(f"hit branch{index % 3} " + "x" * 160 for _ in range(20)) + "\n"
        )
        (tmp_path / f"skip-{index:02d}.txt").write_text("hit skip\n" * 20)
    monkeypatch.setattr(st, "SEARCH_RESULT_MAX_BYTES", 4_096)
    monkeypatch.setattr(st.SEARCH_SETTINGS, "adaptive_discovery_enabled", True)

    materialized = run_mode(
        monkeypatch,
        "materialized",
        "hit|branch0|branch1|branch2",
        tmp_path,
        glob="*.py",
        context_lines=1,
        max_results=100,
    )
    streaming = run_mode(
        monkeypatch,
        "streaming",
        "hit|branch0|branch1|branch2",
        tmp_path,
        glob="*.py",
        context_lines=1,
        max_results=100,
    )

    assert streaming == materialized
    assert streaming["truncated"] is True
    assert "adaptive" in streaming.get("note", "").lower()


def test_streaming_invalid_regex_keeps_error_code(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "EXACT_EXECUTION", "streaming")
    with pytest.raises(st.CodedToolError, match="ripgrep rejected") as exc:
        run_mode(monkeypatch, "streaming", "(", tmp_path, context_lines=0)
    assert exc.value.telemetry_code == "rg_rejected"


def test_streaming_invalid_glob_keeps_error_code_and_reaps_rg(
    tmp_path, monkeypatch, caplog
):
    (tmp_path / "a.py").write_text("hit\n")
    monkeypatch.setattr(st, "EXACT_EXECUTION", "streaming")

    def invalid(*args, **kwargs):
        raise ValueError("synthetic bad glob")

    monkeypatch.setattr("binnacle.search_text_collect.full_match", invalid)
    # search_text's compatibility matcher captures its own full_match reference;
    # patch that seam too so the streaming reducer exercises consumer cleanup.
    monkeypatch.setattr(st, "full_match", invalid)
    from binnacle.callctx import current_call

    token = current_call.set("stream-invalid-glob")
    try:
        with (
            caplog.at_level("INFO", logger="binnacle.search_text"),
            pytest.raises(st.CodedToolError, match="Invalid glob") as exc,
        ):
            run_mode(
                monkeypatch,
                "streaming",
                "hit",
                tmp_path,
                glob="*.py",
                context_lines=0,
            )
    finally:
        current_call.reset(token)
    assert exc.value.telemetry_code == "invalid_glob"
    summary = next(
        record.getMessage()
        for record in caplog.records
        if "event=search_exact call=stream-invalid-glob" in record.getMessage()
    )
    assert "outcome=error error_code=invalid_glob" in summary
    assert "pipeline=streaming" in summary
    assert "collect_event_candidates=1" in summary


def test_streaming_timeout_keeps_error_code(tmp_path, monkeypatch):
    fake = tmp_path / "fake-rg"
    fake.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n")
    fake.chmod(0o755)
    monkeypatch.setattr(st, "EXACT_EXECUTION", "streaming")
    monkeypatch.setattr(st, "RG_BIN", str(fake))
    monkeypatch.setattr(st, "SEARCH_TIMEOUT_S", 0.1)
    started = __import__("time").monotonic()
    with pytest.raises(st.CodedToolError, match="timed out") as exc:
        run_mode(monkeypatch, "streaming", "hit", tmp_path, context_lines=0)
    assert __import__("time").monotonic() - started < 2
    assert exc.value.telemetry_code == "rg_timeout"
