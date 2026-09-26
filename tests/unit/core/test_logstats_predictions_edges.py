from binnacle import logstats
from binnacle.logstats_predictions import export_prediction_rows

PREDICTION_SAMPLE = """\
2026-09-25T10:00:00.000 INFO: event=tool_config tool=run_command shadow_prediction=on predictors=memory,rules,judge judge_model=gpt-oss-120b filter_hash=f123 sanitizer_hash=s123
2026-09-25T10:00:00.100 INFO: event=run_command_prediction schema=1 call=a feature_hash=fa shape_hash=sa first_token_class=uv heredoc=0 chain_n=0 max_delay_s=0 len_chars=30 declared_wait_s=30 declared_background=none auto_rule=- memory_bucket=long memory_p90_s=90 memory_n=3 memory_source=shape memory_store_keys=12 rules_bucket=- rules_p90_s=- rules_hits=- judge=queued judge_skip_reason=- judge_cache=miss
2026-09-25T10:00:00.110 INFO: event=run_command_dispatch call=a client=x job_id=ja owner=manager owner_instance=o requested_wait_s=30 bounded_wait_s=30 effective_wait_s=30 background_arg=omitted auto_background=false handoff_reason=synchronous owner_roundtrip_ms=2 command_hash=h command_chars=30 state=exited
2026-09-25T10:00:12.000 INFO: event=job_exit job_id=ja owner=manager owner_instance=o runtime_s=12.0 exit_code=0 signal=- log_bytes=10
2026-09-25T10:00:12.010 INFO: event=run_command_prediction_judge schema=1 call=a prompt_version=2026-09-26.1 prompt_hash=abc123 model=gpt-oss-120b bucket=medium p90_s=20 confidence=0.82 reason=test_suite latency_ms=410 prompt_tokens=100 completion_tokens=20 error=-
2026-09-25T10:00:13.000 INFO: event=run_command_prediction schema=1 call=b feature_hash=fb shape_hash=sb first_token_class=other heredoc=0 chain_n=0 max_delay_s=0 len_chars=5 declared_wait_s=30 declared_background=none auto_rule=- memory_bucket=short memory_p90_s=2 memory_n=4 memory_source=exact memory_store_keys=14 rules_bucket=short rules_p90_s=1 rules_hits=sleep_ge_10 judge=skipped judge_skip_reason=history judge_cache=-
2026-09-25T10:00:13.010 INFO: event=run_command_dispatch call=b client=x job_id=jb owner=manager owner_instance=o requested_wait_s=30 bounded_wait_s=30 effective_wait_s=30 background_arg=omitted auto_background=false handoff_reason=synchronous owner_roundtrip_ms=2 command_hash=h2 command_chars=5 state=exited
2026-09-25T10:00:15.000 INFO: event=job_exit job_id=jb owner=manager owner_instance=o runtime_s=2.0 exit_code=0 signal=- log_bytes=5
2026-09-25T10:00:16.000 INFO: event=run_command_prediction schema=1 call=c feature_hash=fc shape_hash=sc first_token_class=other heredoc=1 chain_n=3 max_delay_s=0 len_chars=900 declared_wait_s=30 declared_background=none auto_rule=- memory_bucket=- memory_p90_s=- memory_n=0 memory_source=none memory_store_keys=14 rules_bucket=- rules_p90_s=- rules_hits=- judge=skipped judge_skip_reason=budget judge_cache=miss
"""


def test_stats_shadow_export_is_privacy_safe_jsonl_and_csv(tmp_path):
    records, starts = logstats.parse(PREDICTION_SAMPLE)
    stats = logstats.analyze(records, starts).predictions
    jsonl = tmp_path / "prediction.jsonl"
    csv_path = tmp_path / "prediction.csv"
    export_prediction_rows(stats, jsonl)
    export_prediction_rows(stats, csv_path)
    json_text = jsonl.read_text()
    csv_text = csv_path.read_text()
    assert '"feature_hash":"fa"' in json_text
    assert "feature_hash" in csv_text
    assert "command" not in json_text
    assert "prompt" not in json_text
    assert '"judge_confidence":0.82' in json_text
    assert '"judge_reason":"test_suite"' in json_text
    report = logstats.prediction_report(stats)
    assert report["judge"]["confidence_deciles"] == {"0.8-0.9": 1}
    assert report["judge"]["reason_counts"] == {"test_suite": 1}


def test_stats_shadow_malformed_sparse_and_error_records():
    sample = """\
2026-09-25T11:00:00.000 INFO: event=tool_config tool=other shadow_prediction=on filter_hash=ignored
2026-09-25T11:00:00.001 INFO: event=run_command_prediction schema=1 feature_hash=no-call
2026-09-25T11:00:00.002 INFO: event=run_command_prediction schema=1 call=x feature_hash=fx shape_hash=sx first_token_class=other memory_bucket=- memory_p90_s=- memory_n=bad memory_source=none memory_store_keys=bad rules_bucket=- rules_p90_s=- judge=queued judge_skip_reason=- judge_cache=miss
2026-09-25T11:00:00.003 INFO: event=run_command_dispatch call=x job_id=jx state=exited
2026-09-25T11:00:00.004 INFO: event=tool_result call=x tool=run_command state=exited duration_s=5.5
2026-09-25T11:00:00.005 INFO: event=run_command_prediction_judge schema=1 model=gpt-oss-120b bucket=-
2026-09-25T11:00:00.006 INFO: event=run_command_prediction_judge schema=1 call=x model=gpt-oss-120b bucket=- p90_s=- latency_ms=- error=TimeoutError
"""
    records, starts = logstats.parse(sample)
    shadow = logstats.analyze(records, starts).predictions
    assert shadow.dispatches == 1
    assert shadow.outcomes == 1
    assert shadow.rows[0]["actual_runtime_s"] == 5.5
    assert shadow.memory_store_keys == 0
    assert shadow.memory_sample_counts == {}
    assert shadow.judge_network_results == 1
    assert shadow.judge_errors == {"TimeoutError": 1}
    assert shadow.judge_latency_ms == []


def test_stats_shadow_runtime_and_metric_edge_helpers():
    from collections import Counter

    import binnacle.logstats_predictions as predictions

    assert predictions._quantile([], 0.5) is None
    empty = predictions._metrics(Counter())
    assert empty["precision"] == 0
    assert empty["recall"] == 0
    assert empty["f1"] == 0

    mixed = predictions._metrics(Counter(tp=1, fp=1, fn=1, tn=1))
    assert mixed["precision"] == 0.5
    assert mixed["recall"] == 0.5
    assert mixed["f1"] == 0.5


def test_stats_shadow_render_empty_and_error_sections():
    from binnacle.logstats_models import PredictionStats
    from binnacle.logstats_predictions import render_predictions

    assert render_predictions(PredictionStats()) == []

    stats = PredictionStats(dispatches=1, outcomes=0)
    stats.judge_results = 1
    stats.judge_network_results = 1
    stats.judge_errors["TimeoutError"] = 1
    stats.judge_skip_reasons["fast_shell"] = 1
    stats.rows.append({"judge_confidence": 1.0, "judge_reason": "network"})
    lines = render_predictions(stats)
    assert any("errors: TimeoutError:1" in line for line in lines)
    assert any("skip reasons: fast_shell:1" in line for line in lines)
    assert any("confidence deciles: 0.9-1.0:1" in line for line in lines)
    assert any("reason codes: network:1" in line for line in lines)


def test_stats_shadow_tool_result_runtime_s_fallback():
    sample = """\
2026-09-25T12:00:00.000 INFO: event=run_command_prediction schema=1 call=z feature_hash=fz shape_hash=sz first_token_class=other memory_bucket=short memory_p90_s=2 memory_n=1 memory_source=exact memory_store_keys=1 rules_bucket=- rules_p90_s=- judge=disabled judge_skip_reason=- judge_cache=-
2026-09-25T12:00:00.001 INFO: event=run_command_dispatch call=z job_id=jz state=exited
2026-09-25T12:00:00.002 INFO: event=tool_result call=z tool=run_command state=exited runtime_s=3.0 duration_s=4.0
"""
    records, starts = logstats.parse(sample)
    shadow = logstats.analyze(records, starts).predictions
    assert shadow.rows[0]["actual_runtime_s"] == 3.0
    assert shadow.calibration["memory"]["short->short"] == 1
