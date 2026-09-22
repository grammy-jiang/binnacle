"""Exact-search Phase B journal aggregation and mixed-version coverage."""

from binnacle import logstats

SAMPLE = """
2026-09-22T18:00:00.000 INFO: event=search_dispatch call=old mode=exact path_hash=a pattern_chars=3
2026-09-22T18:00:01.000 INFO: event=search_dispatch call=n1 mode=exact path_hash=b pattern_chars=4
2026-09-22T18:00:01.010 INFO: event=search_exact call=n1 outcome=ok error_code=- strategy=normal budget_outcome=none scope=dir rg_calls=1 auto_context=false context_requested=0 effective_context=0 rg_subprocess_ms=4 rg_parse_ms=1 collect_ms=2 context_attach_ms=0 adaptive_ms=0 budget_ms=0.1 impl_ms=8 rg_stdout_chars=1000 rg_events=20 rg_match_events=10 rg_context_events=0 rg_begin_events=2 rg_bad_json=0 collect_event_candidates=10 collect_glob_checks=10 collect_glob_rejected=5 accepted_matches=5 accepted_files=1 retained_matches=5 match_cap_hit=false adaptive_attempted=false adaptive_selected=false adaptive_budget_trimmed=false adaptive_match_events=0 adaptive_glob_checks=0 adaptive_glob_rejected=0 pre_budget_bytes=500 returned_entries=5 result_bytes=500 final_truncated=false
2026-09-22T18:00:02.000 INFO: event=search_dispatch call=n2 mode=exact path_hash=c pattern_chars=5
2026-09-22T18:00:02.010 INFO: event=search_exact call=n2 outcome=ok error_code=- strategy=adaptive budget_outcome=none scope=dir rg_calls=2 auto_context=true context_requested=omitted effective_context=15 rg_subprocess_ms=10 rg_parse_ms=3 collect_ms=4 context_attach_ms=1 adaptive_ms=5 budget_ms=0 impl_ms=24 rg_stdout_chars=4000 rg_events=80 rg_match_events=20 rg_context_events=40 rg_begin_events=4 rg_bad_json=0 collect_event_candidates=60 collect_glob_checks=0 collect_glob_rejected=0 accepted_matches=10 accepted_files=2 retained_matches=10 match_cap_hit=false adaptive_attempted=true adaptive_selected=true adaptive_budget_trimmed=false adaptive_match_events=20 adaptive_glob_checks=0 adaptive_glob_rejected=0 pre_budget_bytes=80000 returned_entries=4 result_bytes=1000 final_truncated=true
2026-09-22T18:00:03.000 INFO: event=search_dispatch call=e mode=exact path_hash=d pattern_chars=1
2026-09-22T18:00:03.010 INFO: event=search_exact call=e outcome=error error_code=rg_rejected strategy=normal budget_outcome=none scope=dir rg_calls=1 auto_context=false context_requested=0 effective_context=0 rg_subprocess_ms=2 rg_parse_ms=0 collect_ms=0 context_attach_ms=0 adaptive_ms=0 budget_ms=0 impl_ms=2 rg_stdout_chars=0 rg_events=0 rg_match_events=0 rg_context_events=0 rg_begin_events=0 rg_bad_json=0 collect_event_candidates=0 collect_glob_checks=0 collect_glob_rejected=0 accepted_matches=0 accepted_files=0 retained_matches=0 match_cap_hit=false adaptive_attempted=false adaptive_selected=false adaptive_budget_trimmed=false adaptive_match_events=0 adaptive_glob_checks=0 adaptive_glob_rejected=0 pre_budget_bytes=0 returned_entries=0 result_bytes=0 final_truncated=false
2026-09-22T18:00:04.000 INFO: event=search_dispatch call=idx mode=indexed path_hash=e pattern_chars=10
"""


def test_exact_search_stats_report_coverage_phases_work_and_amplification():
    records, startups = logstats.parse(SAMPLE)
    st = logstats.analyze(records, startups)
    exact = st.exact_search
    assert exact.dispatches == 4
    assert exact.summaries == 3 and exact.errors == 1
    assert exact.strategies == {"normal": 2, "adaptive": 1}
    assert exact.budget_outcomes == {"none": 3}
    assert exact.error_codes == {"rg_rejected": 1}
    assert exact.rg_calls_total == 4 and exact.auto_context == 1
    assert exact.impl_ms == [8.0, 24.0, 2.0]
    assert exact.rg_events == [20, 80, 0]
    assert exact.events_per_accepted_match == [4.0, 8.0]
    assert exact.chars_per_returned_entry == [200.0, 1000.0]

    text = logstats.render(st)
    assert "exact search telemetry:" in text
    assert "dispatches=4 summaries=3 coverage=75.0% errors=1" in text
    assert "normal=2" in text and "adaptive=1" in text
    assert "auto_context_second_rg=1" in text
    assert "rg JSON parse" in text and "collect/filter" in text
    assert "rg events / accepted" in text and "rg chars / returned" in text


STREAMING_SAMPLE = """
2026-09-22T20:00:00.000 INFO: event=search_dispatch call=s mode=exact path_hash=x pattern_chars=3
2026-09-22T20:00:00.010 INFO: event=search_exact call=s outcome=ok error_code=- strategy=normal budget_outcome=none scope=dir pipeline=streaming rg_calls=1 auto_context=false context_requested=1 effective_context=1 rg_subprocess_ms=0 rg_parse_ms=0 collect_ms=0 context_attach_ms=0.2 adaptive_ms=0 budget_ms=0.1 impl_ms=9 rg_stdout_chars=0 rg_stdout_bytes=2400 rg_wall_ms=7 stream_cpu_ms=3 glob_cache_hits=20 glob_cache_misses=4 glob_rejected_files=2 glob_rejected_events=10 adaptive_retained_match_events=6 rg_events=30 rg_match_events=8 rg_context_events=15 rg_begin_events=3 rg_bad_json=0 collect_event_candidates=23 collect_glob_checks=4 collect_glob_rejected=10 accepted_matches=6 accepted_files=2 retained_matches=6 match_cap_hit=false adaptive_attempted=false adaptive_selected=false adaptive_budget_trimmed=false adaptive_match_events=0 adaptive_glob_checks=0 adaptive_glob_rejected=0 pre_budget_bytes=900 returned_entries=6 result_bytes=900 final_truncated=false
"""


def test_exact_search_stats_keep_streaming_and_materialized_metrics_separate():
    records, startups = logstats.parse(SAMPLE + STREAMING_SAMPLE)
    st = logstats.analyze(records, startups)
    exact = st.exact_search
    assert exact.pipelines == {"materialized": 3, "streaming": 1}
    assert exact.rg_subprocess_ms == [4.0, 10.0, 2.0]
    assert exact.rg_parse_ms == [1.0, 3.0, 0.0]
    assert exact.collect_ms == [2.0, 4.0, 0.0]
    assert exact.rg_wall_ms == [7.0]
    assert exact.stream_cpu_ms == [3.0]
    assert exact.rg_stdout_chars == [1000, 4000, 0]
    assert exact.rg_stdout_bytes == [2400]
    assert exact.glob_cache_hits == [20]
    assert exact.glob_cache_misses == [4]
    assert exact.glob_rejected_files == [2]
    assert exact.glob_rejected_events == [10]
    assert exact.adaptive_retained_match_events == [6]
    assert exact.bytes_per_returned_entry == [400.0]

    text = logstats.render(st)
    assert "pipeline: materialized=3, streaming=1" in text
    assert "rg stream wall" in text and "stream CPU" in text
    assert "rg stdout bytes" in text and "glob cache misses" in text
    assert "rg bytes / returned" in text
