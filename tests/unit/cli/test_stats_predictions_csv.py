from binnacle import cli, logstats

SAMPLE = """\
2026-09-26T10:00:00.000 INFO: event=run_command_prediction schema=1 call=a feature_hash=fa shape_hash=sa first_token_class=uv heredoc=0 chain_n=0 max_delay_s=0 len_chars=12 declared_wait_s=30 declared_background=none auto_rule=- memory_bucket=- memory_p90_s=- memory_n=0 memory_source=none memory_store_keys=0 rules_bucket=- rules_p90_s=- rules_hits=- judge=skipped judge_skip_reason=budget judge_cache=miss
2026-09-26T10:00:00.010 INFO: event=run_command_dispatch call=a client=x job_id=ja state=exited
2026-09-26T10:00:12.000 INFO: event=job_exit job_id=ja runtime_s=12 exit_code=0 signal=- log_bytes=1
"""


def test_stats_predictions_csv_exports_joined_privacy_safe_rows(
    tmp_path, monkeypatch, capsys
):
    output = tmp_path / "predictions.csv"
    monkeypatch.setattr(logstats, "fetch_journal", lambda units, since, until: SAMPLE)

    cli.stats(unit="dev", predictions_csv=output)

    rendered = capsys.readouterr().out
    exported = output.read_text()
    assert "predictions:" in rendered
    assert "feature_hash" in exported
    assert "fa" in exported
    assert "12.0" in exported
    assert "command" not in exported
    assert "prompt" not in exported
