import json
import logging

import pytest

from binnacle.config import RunCommandShadowPredictionSettings
from binnacle.run_command_prediction import (
    CerebrasJudgeClient,
    JudgeBudget,
    JudgeResult,
    MemoryLookup,
    Prediction,
    ShadowPredictionEngine,
    hand_rule_prediction,
    judge_skip_reason,
    runtime_bucket,
)
from binnacle.run_command_prediction import (
    MemoryStore as Store,
)
from binnacle.run_command_telemetry import build_command_features


def feat(command="uv run pytest tests/unit"):
    return build_command_features(
        command, wait_seconds=30, declared_background="none", tail_lines=None
    )


def cfg(tmp_path, **overrides):
    values = {
        "enabled": True,
        "predictors": ("memory", "rules", "judge"),
        "memory_dir": tmp_path,
        "memory_min_samples": 2,
        "memory_max_keys": 16,
        "memory_samples_per_key": 4,
        "judge_enabled": True,
        "judge_minute_budget": 2,
        "judge_complex_chain_threshold": 0,
        "judge_complex_length_threshold": 1,
        "judge_workers": 1,
    }
    values.update(overrides)
    return RunCommandShadowPredictionSettings(**values)


def fake_ok(captured, bucket="long", p90=75.0, confidence=0.82, reason="test_suite"):
    def transport(url, headers, body, timeout):
        captured.update(
            url=url, headers=headers, body=json.loads(body), timeout=timeout
        )
        payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "bucket": bucket,
                                "p90_s": p90,
                                "confidence": confidence,
                                "reason": reason,
                            }
                        )
                    }
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4},
        }
        return 200, json.dumps(payload).encode(), {}

    return transport


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


@pytest.mark.parametrize(
    "command",
    [
        "python worker.py",
        "uv sync",
        "custom-executable --work",
        "./scripts/build.sh",
        "make all",
        "tox -e py",
        "pytest -q",
    ],
)
def test_prediction_judge_selects_short_long_capable_commands(command):
    empty = MemoryLookup(None, 0, "none", 0, 0)
    assert (
        judge_skip_reason(
            feat(command),
            empty,
            chain_threshold=5,
            length_threshold=500,
            budget_available=True,
            command=command,
        )
        is None
    )


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        ("cd /tmp", "fast_shell"),
        ("ls -la", "fast_shell"),
        ("cat README.md", "fast_shell"),
        ("echo ok", "fast_shell"),
        ("printf ok", "fast_shell"),
        ("git status", "fast_git_read"),
        ("git log -5", "fast_git_read"),
        ("git diff --stat", "fast_git_read"),
        ("git show HEAD", "fast_git_read"),
        ("sed -n '1,10p' README.md", "fast_file_read"),
        ("head -n 10 README.md", "fast_file_read"),
        ("tail -n 10 README.md", "fast_file_read"),
        ("wc -l README.md", "fast_file_read"),
        ("grep needle README.md", "fast_file_read"),
    ],
)
def test_prediction_judge_skips_only_clear_fast_shapes(command, reason):
    empty = MemoryLookup(None, 0, "none", 0, 0)
    assert (
        judge_skip_reason(
            feat(command),
            empty,
            chain_threshold=5,
            length_threshold=500,
            budget_available=True,
            command=command,
        )
        == reason
    )


def test_prediction_store_load_fallback_eviction_and_invalid_inputs(tmp_path):
    first = feat("python -c pass")
    second = feat("git push origin x")
    third = feat("sleep 12")
    store = Store(tmp_path, max_keys=2, samples_per_key=2, cache_ttl_s=60)
    store.record(first, -1)
    assert store.key_count == 0
    store.record(first, 1)
    store.record(second, 2)
    store.record(third, 3)
    assert store.key_count <= 4

    reloaded = Store(tmp_path, max_keys=2, samples_per_key=2, cache_ttl_s=60)
    assert reloaded.lookup(third, 1).prediction == Prediction("short", 3)
    assert reloaded.cache_get("missing") is None
    reloaded.cache_set("bad", JudgeResult(None, None, 0))
    assert reloaded.cache_get("bad") is None
    versioned = JudgeResult("medium", 20, 0, confidence=0.7, reason="local_history")
    reloaded.cache_set("versioned", versioned, prompt_hash="hash-a")
    assert reloaded.cache_get("versioned", prompt_hash="hash-a") == versioned
    assert reloaded.cache_get("versioned", prompt_hash="hash-b") is None

    reloaded.path.write_text("{bad json")
    corrupted = Store(tmp_path, max_keys=2, samples_per_key=2, cache_ttl_s=60)
    assert corrupted.key_count == 0
    corrupted.path.write_text(json.dumps({"version": 999}))
    wrong_version = Store(tmp_path, max_keys=2, samples_per_key=2, cache_ttl_s=60)
    assert wrong_version.key_count == 0


def test_prediction_reset_header_parsing(monkeypatch):
    import binnacle.run_command_prediction as prediction

    assert prediction._reset_seconds({}) == 60
    assert prediction._reset_seconds({"retry-after": "2.5"}) == 2.5
    assert prediction._reset_seconds({"retry-after": "1m30s"}) == 90
    assert prediction._reset_seconds({"retry-after": "nonsense"}) == 60
    monkeypatch.setattr("binnacle.config.time.time", lambda: 1_000_000_000.0)
    assert prediction._reset_seconds({"retry-after": "1000000010"}) == 10
    assert prediction._optional_int("bad") is None


def test_prediction_judge_key_file_missing_and_empty(monkeypatch, tmp_path):
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    missing = CerebrasJudgeClient(cfg(tmp_path, judge_api_key_file=None))
    with pytest.raises(RuntimeError, match="missing_api_key"):
        missing._api_key()

    key_file = tmp_path / "empty-key"
    key_file.write_text("")
    key_file.chmod(0o600)
    empty = CerebrasJudgeClient(cfg(tmp_path, judge_api_key_file=key_file))
    with pytest.raises(RuntimeError, match="missing_api_key"):
        empty._api_key()


def test_prediction_judge_http_and_invalid_output_fail_open(monkeypatch, tmp_path):
    monkeypatch.setenv("CEREBRAS_API_KEY", "unit-test-key")

    http_error = CerebrasJudgeClient(
        cfg(tmp_path), lambda *_: (500, b"{}", {})
    ).predict(
        sanitized_command="echo x",
        features=feat("echo x"),
        local_stats={},
    )
    assert http_error.error == "http_500"
    assert http_error.retry_after_s is None

    payload = {
        "choices": [
            {"message": {"content": json.dumps({"bucket": "wrong", "p90_s": -1})}}
        ]
    }
    invalid = CerebrasJudgeClient(
        cfg(tmp_path), lambda *_: (200, json.dumps(payload).encode(), {})
    ).predict(
        sanitized_command="echo x",
        features=feat("echo x"),
        local_stats={},
    )
    assert invalid.error == "ParseError"


def test_prediction_budget_hour_day_and_disabled_limits(tmp_path):
    now = [0.0]
    hourly = JudgeBudget(
        cfg(
            tmp_path,
            judge_minute_budget=5,
            judge_hour_budget=1,
            judge_day_budget=10,
        ),
        clock=lambda: now[0],
    )
    assert hourly.take()
    now[0] = 61
    assert not hourly.take()

    daily = JudgeBudget(
        cfg(
            tmp_path,
            judge_minute_budget=5,
            judge_hour_budget=5,
            judge_day_budget=1,
        ),
        clock=lambda: now[0],
    )
    assert daily.take()
    now[0] += 3601
    assert not daily.take()

    disabled = JudgeBudget(
        cfg(tmp_path, judge_minute_budget=0),
        clock=lambda: now[0],
    )
    assert not disabled.take()
    disabled.pause_for(None)
    assert not disabled.take()


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
    settings = cfg(
        tmp_path,
        predictors=(),
        judge_enabled=False,
    )
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
    assert "judge=disabled" in line


def test_prediction_engine_history_simple_and_cached_paths(
    caplog, monkeypatch, tmp_path
):
    monkeypatch.setenv("CEREBRAS_API_KEY", "unit-test-key")
    settings = cfg(
        tmp_path,
        judge_complex_chain_threshold=5,
        judge_complex_length_threshold=500,
    )
    engine = ShadowPredictionEngine(settings, transport=fake_ok({}))
    simple = feat("echo x")
    with caplog.at_level(logging.INFO, logger="binnacle.run_command"):
        engine.submit(
            call_id="simple",
            command="echo x",
            features=simple,
            auto_rule_hash=None,
        )
        assert engine.store is not None
        engine.store.record(simple, 1)
        engine.store.record(simple, 2)
        engine.submit(
            call_id="history",
            command="echo x",
            features=simple,
            auto_rule_hash=None,
        )

        complex_command = "cat <<'EOF'\nx\nEOF"
        complex_item = feat(complex_command)
        engine.store.cache_set(
            complex_item.command_hash,
            JudgeResult("medium", 20, 0, 1, 1, confidence=0.8, reason="test_suite"),
        )
        engine.submit(
            call_id="cached",
            command=complex_command,
            features=complex_item,
            auto_rule_hash=None,
        )
        engine.close()
    simple_line = next(line for line in caplog.messages if "call=simple " in line)
    history_line = next(line for line in caplog.messages if "call=history " in line)
    cached_line = next(line for line in caplog.messages if "call=cached " in line)
    assert "judge_skip_reason=fast_shell" in simple_line
    assert "judge_skip_reason=history" in history_line
    assert "judge=cached" in cached_line
    assert "judge_cache=hit" in cached_line


def test_prediction_engine_executor_and_worker_failures(caplog, monkeypatch, tmp_path):
    monkeypatch.setenv("CEREBRAS_API_KEY", "unit-test-key")
    settings = cfg(tmp_path)

    engine = ShadowPredictionEngine(settings, transport=fake_ok({}))
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

    class ExplodingJudge:
        def predict(self, **kwargs):
            raise LookupError("boom")

    caplog.clear()
    engine2 = ShadowPredictionEngine(settings, transport=fake_ok({}))
    engine2.judge = ExplodingJudge()
    item = feat("echo a && echo c")
    with caplog.at_level(logging.INFO, logger="binnacle.run_command"):
        engine2.submit(
            call_id="judge-exception",
            command="echo a && echo c",
            features=item,
            auto_rule_hash=None,
        )
        engine2.close()
    result_line = next(
        line
        for line in caplog.messages
        if "event=run_command_prediction_judge" in line
        and "call=judge-exception" in line
    )
    assert "error=LookupError" in result_line


def test_prediction_engine_store_failures_are_contained(caplog, monkeypatch, tmp_path):
    monkeypatch.setenv("CEREBRAS_API_KEY", "unit-test-key")
    engine = ShadowPredictionEngine(cfg(tmp_path), transport=fake_ok({}))
    assert engine.store is not None

    def fail_cache(*args, **kwargs):
        raise OSError

    monkeypatch.setattr(engine.store, "cache_set", fail_cache)
    item = feat("echo a && echo d")
    with caplog.at_level(logging.WARNING, logger="binnacle.run_command"):
        engine.submit(
            call_id="cache-write-error",
            command="echo a && echo d",
            features=item,
            auto_rule_hash=None,
        )
        engine.close()
    assert "run_command_prediction_memory_error" in caplog.text

    engine2 = ShadowPredictionEngine(
        cfg(tmp_path, predictors=("memory",), judge_enabled=False)
    )
    assert engine2.store is not None
    monkeypatch.setattr(
        engine2.store,
        "record",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError()),
    )
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="binnacle.run_command"):
        engine2._record_runtime_task(feat("echo y"), 1)
        engine2.close()
    assert "run_command_prediction_memory_error" in caplog.text
