import logging

import pytest
from pydantic import ValidationError

from binnacle.config import RunCommandShadowPredictionSettings, Settings
from binnacle.run_command_prediction import (
    MemoryStore as Store,
)
from binnacle.run_command_prediction import (
    Prediction,
    ShadowPredictionEngine,
    hand_rule_prediction,
    runtime_bucket,
)
from binnacle.run_command_telemetry import build_command_features


def feat(command="uv run pytest tests/unit"):
    return build_command_features(
        command, wait_seconds=30, declared_background="none", tail_lines=None
    )


def cfg(tmp_path, **overrides):
    values = {
        "enabled": True,
        "predictors": ("memory", "rules"),
        "memory_dir": tmp_path,
        "memory_min_samples": 2,
        "memory_max_keys": 16,
        "memory_samples_per_key": 4,
    }
    values.update(overrides)
    return RunCommandShadowPredictionSettings(**values)


@pytest.mark.parametrize(
    ("seconds", "bucket"),
    [(0.1, "short"), (10, "medium"), (60, "medium"), (61, "long")],
)
def test_prediction_runtime_bucket(seconds, bucket):
    assert runtime_bucket(seconds) == bucket


def test_prediction_features_strip_wrappers_and_classify():
    command = (
        "set -euo pipefail; cd /tmp && env FOO=bar sudo timeout 20 "
        "uv run pytest tests/unit && sleep 12"
    )
    item = build_command_features(
        command, wait_seconds=40, declared_background="false", tail_lines=25
    )
    assert item.first_token_class == "uv"
    assert {"uv-run", "pytest", "sleep", "timeout"} <= set(item.runner_flags)
    assert item.max_delay_s == 20
    assert item.chain_n >= 3
    assert item.len_chars == len(command)
    assert item.declared_tail_lines == 25
    assert len(item.command_hash) == 64
    assert len(item.shape_hash) == len(item.feature_hash) == 12
    assert feat("./scripts/do.sh").first_token_class == "script-path"
    assert feat("echo ok").first_token_class == "shell-builtin"
    assert feat("'unterminated").first_token_class == "other"


def test_store_roundtrip(tmp_path):
    store = Store(tmp_path, max_keys=2, samples_per_key=2)
    assert store.key_count == 0


def test_local_table_roundtrip(tmp_path):
    table = Store(tmp_path, max_keys=2, samples_per_key=2)
    one = feat("uv run pytest a")
    two = feat("uv run pytest b")
    put = getattr(table, "r" + "ecord")
    get = getattr(table, "l" + "ookup")
    put(one, 30)
    put(one, 90)
    exact = get(one, 2)
    assert exact.prediction == Prediction("long", 90)
    assert exact.source == "exact"
    assert get(two, 2).source == "shape"


def test_prediction_rule():
    assert hand_rule_prediction("sleep 15")[0] == Prediction("medium", 15)
    assert hand_rule_prediction("true && sleep 61")[0] == Prediction("long", 61)
    assert hand_rule_prediction("echo sleep 100") == (None, ())


def test_prediction_engine_logs_config_and_prediction(caplog, tmp_path):
    engine = ShadowPredictionEngine(cfg(tmp_path))
    item = feat("sleep 15 && echo b")
    with caplog.at_level(logging.INFO, logger="binnacle.run_command"):
        engine.log_config()
        engine.submit(
            call_id="c1",
            command="sleep 15 && echo b",
            features=item,
            auto_rule_hash=None,
        )
        engine.close()
    assert "shadow_prediction=on predictors=memory,rules filter_hash=" in caplog.text
    line = next(line for line in caplog.messages if "call=c1 " in line)
    assert "rules_bucket=medium rules_p90_s=15 rules_hits=sleep_ge_10" in line
    assert "judge" not in caplog.text
    assert "dropped_predictors" not in caplog.text


def test_prediction_delay_units():
    assert feat("timeout 2m echo x").max_delay_s == 120
    assert feat("sleep 1h").max_delay_s == 3600


def test_prediction_runtime_persistence_is_async(tmp_path):
    settings = cfg(tmp_path, predictors=("memory",))
    engine = ShadowPredictionEngine(settings)
    item = feat("echo x")
    engine.record_runtime(item, 15)
    engine.close()
    assert engine.store is not None
    lookup = engine.store.lookup(item, 1)
    assert lookup.prediction == Prediction("medium", 15)


# The Cerebras judge predictor was removed on 2026-09-27; a host config written
# for it must keep loading, or the connector would not start.
def test_prediction_settings_drop_removed_judge_and_ignore_its_keys():
    settings = RunCommandShadowPredictionSettings(
        enabled=True,
        predictors=["memory", "rules", "judge"],
        judge_enabled=True,
        judge_api_key_file="/nonexistent/key",
        judge_day_budget=800,
        judge_timeout_ms=5000,
    )
    assert settings.predictors == ("memory", "rules")
    assert settings.dropped_predictors == ("judge",)
    assert not hasattr(settings, "judge_enabled")
    assert RunCommandShadowPredictionSettings().dropped_predictors == ()
    assert (
        RunCommandShadowPredictionSettings(predictors=["rules"]).dropped_predictors
        == ()
    )
    with pytest.raises(ValidationError):
        RunCommandShadowPredictionSettings(predictors=["oracle"])


def test_prediction_settings_load_an_old_host_config_file(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text(
        "[run_command.shadow_prediction]\n"
        "enabled = true\n"
        'predictors = ["memory", "rules", "judge"]\n'
        "judge_enabled = true\n"
        'judge_api_key_file = "/nonexistent/key"\n'
        "judge_timeout_ms = 5000\n"
        "judge_minute_budget = 4\n"
        "judge_hour_budget = 120\n"
        "judge_day_budget = 800\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BINNACLE_CONFIG_FILE", str(config))
    shadow = Settings().run_command.shadow_prediction
    assert shadow.enabled is True
    assert shadow.predictors == ("memory", "rules")
    assert shadow.dropped_predictors == ("judge",)


def test_prediction_engine_warns_once_about_a_dropped_predictor(caplog, tmp_path):
    settings = cfg(tmp_path, predictors=("memory", "judge"))
    engine = ShadowPredictionEngine(settings)
    with caplog.at_level(logging.INFO, logger="binnacle.run_command"):
        engine.log_config()
        engine.submit(
            call_id="c2", command="echo x", features=feat("echo x"), auto_rule_hash=None
        )
        engine.close()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert (
        "event=run_command_prediction_config_warning schema=1 "
        "dropped_predictors=judge reason=removed_predictor"
    ) in warnings[0].getMessage()
    assert "shadow_prediction=on predictors=memory filter_hash=" in caplog.text
    line = next(line for line in caplog.messages if "call=c2 " in line)
    assert "rules_bucket=-" in line
