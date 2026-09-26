import json
import logging

import pytest

from binnacle.config import RunCommandShadowPredictionSettings
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
    ("command", "seconds"),
    [
        ("sleep 35; pytest -q", 35),
        ('bash -lc "sleep 12; ls"', 12),
        ("(sleep 13)", 13),
        ("{ sleep 14; }", 14),
        ("printf x | sleep 15", 15),
        ("printf x & sleep 16", 16),
        ("for x in 1; do sleep 17; done", 17),
        ("if true; then sleep 18; fi", 18),
        ("python -c 'import time; time.sleep(25)'", 25),
        ("sleep 20s", 20),
        ("sleep 2m", 120),
    ],
)
def test_prediction_rule_sleep_forms(command, seconds):
    prediction, hits = hand_rule_prediction(command)
    assert prediction == Prediction(runtime_bucket(seconds), seconds)
    assert hits == ("sleep_ge_10",)


@pytest.mark.parametrize(
    "command",
    [
        "timeout 40 pytest -q",
        "pytest --timeout 40",
        "echo sleep 100",
    ],
)
def test_prediction_rule_does_not_treat_timeout_as_sleep(command):
    assert hand_rule_prediction(command) == (None, ())


def test_prediction_store_load_fallback_eviction_and_invalid_inputs(tmp_path):
    first = feat("python -c pass")
    second = feat("git push origin x")
    third = feat("sleep 12")
    store = Store(tmp_path, max_keys=2, samples_per_key=2)
    store.record(first, -1)
    assert store.key_count == 0
    store.record(first, 1)
    store.record(second, 2)
    store.record(third, 3)
    assert store.key_count <= 4

    reloaded = Store(tmp_path, max_keys=2, samples_per_key=2)
    assert reloaded.lookup(third, 1).prediction == Prediction("short", 3)

    reloaded.path.write_text("{bad json")
    corrupted = Store(tmp_path, max_keys=2, samples_per_key=2)
    assert corrupted.key_count == 0
    corrupted.path.write_text(json.dumps({"version": 999}))
    wrong_version = Store(tmp_path, max_keys=2, samples_per_key=2)
    assert wrong_version.key_count == 0


def test_prediction_engine_disabled_and_predictor_selection(caplog, tmp_path):
    disabled = ShadowPredictionEngine(RunCommandShadowPredictionSettings())
    with caplog.at_level(logging.INFO, logger="binnacle.run_command"):
        disabled.log_config()
        disabled.submit(
            call_id="disabled",
            command="echo x",
            features=feat("echo x"),
            auto_rule_hash=None,
        )
        disabled.record_runtime(feat("echo x"), 1)
        disabled.close()
    assert "shadow_prediction=off" in caplog.text

    caplog.clear()
    settings = cfg(tmp_path, predictors=())
    engine = ShadowPredictionEngine(settings)
    with caplog.at_level(logging.INFO, logger="binnacle.run_command"):
        engine.submit(
            call_id="no-predictors",
            command="echo x",
            features=feat("echo x"),
            auto_rule_hash=None,
        )
        engine.close()
    line = next(line for line in caplog.messages if "call=no-predictors " in line)
    assert "memory_bucket=-" in line
    assert "rules_bucket=-" in line
    assert "judge" not in line


def test_prediction_engine_memory_history_path(caplog, tmp_path):
    engine = ShadowPredictionEngine(cfg(tmp_path))
    simple = feat("echo x")
    with caplog.at_level(logging.INFO, logger="binnacle.run_command"):
        engine.submit(
            call_id="cold", command="echo x", features=simple, auto_rule_hash=None
        )
        assert engine.store is not None
        engine.store.record(simple, 1)
        engine.store.record(simple, 2)
        engine.submit(
            call_id="warm", command="echo x", features=simple, auto_rule_hash="r1"
        )
        engine.close()
    cold = next(line for line in caplog.messages if "call=cold " in line)
    warm = next(line for line in caplog.messages if "call=warm " in line)
    assert "memory_bucket=- memory_p90_s=- memory_n=0 memory_source=none" in cold
    assert "auto_rule=r1 memory_bucket=short memory_p90_s=2 memory_n=2" in warm
    assert "memory_source=exact" in warm


def test_prediction_engine_executor_failures(caplog, tmp_path):
    engine = ShadowPredictionEngine(cfg(tmp_path))
    assert engine.executor is not None
    engine.executor.shutdown(wait=True)
    with caplog.at_level(logging.WARNING, logger="binnacle.run_command"):
        engine.submit(
            call_id="shutdown-submit",
            command="echo a && echo b",
            features=feat("echo a && echo b"),
            auto_rule_hash=None,
        )
        engine.record_runtime(feat("echo x"), 1)
    assert "ExecutorUnavailable" in caplog.text


def test_prediction_engine_store_failures_are_contained(caplog, monkeypatch, tmp_path):
    engine = ShadowPredictionEngine(cfg(tmp_path, predictors=("memory",)))
    assert engine.store is not None
    monkeypatch.setattr(
        engine.store,
        "record",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError()),
    )
    with caplog.at_level(logging.WARNING, logger="binnacle.run_command"):
        engine._record_runtime_task(feat("echo y"), 1)
        engine.close()
    assert "run_command_prediction_memory_error" in caplog.text


def test_prediction_store_drops_the_old_judge_cache_on_write(tmp_path):
    item = feat("uv run pytest a")
    (tmp_path / "memory.json").write_text(
        json.dumps(
            {
                "version": 1,
                "exact": {item.command_hash: [5.0, 7.0]},
                "shape": {},
                "cache": {"key:prompt": {"bucket": "long", "p90_s": 90}},
            }
        )
    )
    store = Store(tmp_path, max_keys=4, samples_per_key=4)
    assert store.lookup(item, 2).prediction == Prediction("short", 7.0)
    store.record(item, 9)
    written = json.loads((tmp_path / "memory.json").read_text())
    assert "cache" not in written
    assert written["exact"][item.command_hash] == [5.0, 7.0, 9.0]
