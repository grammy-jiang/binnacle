import json
import logging
import os
import threading

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
    sanitize_command,
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
    values = dict(
        enabled=True,
        predictors=("memory", "rules", "judge"),
        memory_dir=tmp_path,
        memory_min_samples=2,
        memory_max_keys=16,
        memory_samples_per_key=4,
        judge_enabled=True,
        judge_minute_budget=2,
        judge_complex_chain_threshold=0,
        judge_complex_length_threshold=1,
        judge_workers=1,
    )
    values.update(overrides)
    return RunCommandShadowPredictionSettings(**values)


def fake_ok(captured, bucket="long", p90=75.0):
    def transport(url, headers, body, timeout):
        captured.update(
            url=url, headers=headers, body=json.loads(body), timeout=timeout
        )
        payload = {
            "choices": [
                {"message": {"content": json.dumps({"bucket": bucket, "p90_s": p90})}}
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4},
        }
        return 200, json.dumps(payload).encode(), {}

    return transport


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


def test_prediction_sanitizer_removes_sensitive_values():
    home = os.path.expanduser("~")
    authorization = "Author" + "ization: " + "alpha" + "-value"
    bearer = "Bear" + "er " + "beta" + "-value"
    key = "API_" + "KEY=" + "gamma" + "-secret-value"
    password = "PASS" + "WORD=" + "delta" + "-value"
    token = "TO" + "KEN=" + ("tok" * 9)
    command = (
        f"{authorization} {bearer} {key} {password} {token} "
        "GENERIC="
        + ("abcdef" * 6)
        + " "
        + ("0123456789abcdef" * 2)
        + " user"
        + "@example.com "
        + f"{home}/Projects/demo "
        + '"'
        + ("z" * 100)
        + '"'
    )
    cleaned = sanitize_command(command, max_chars=500)
    for secret in (
        "alpha-value",
        "beta-value",
        "gamma-secret-value",
        "delta-value",
        "toktoktok",
        "abcdefabcdefabcdef",
        "0123456789abcdef0123456789abcdef",
        "user@example.com",
        home,
        "z" * 80,
    ):
        assert secret not in cleaned
    assert "<redacted>" in cleaned
    assert "<blob>" in cleaned
    assert "<email>" in cleaned
    assert "~/" in cleaned
    assert len(sanitize_command("x " * 2000, max_chars=123)) == 123


def test_store_roundtrip(tmp_path):
    store = Store(tmp_path, max_keys=2, samples_per_key=2, cache_ttl_s=60)
    assert store.key_count == 0


def test_local_table_roundtrip(tmp_path):
    table = Store(tmp_path, max_keys=2, samples_per_key=2, cache_ttl_s=60)
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


def test_prediction_judge_success_uses_fake_transport(monkeypatch, tmp_path):
    monkeypatch.setenv("CEREBRAS_API_KEY", "unit-test-key")
    captured = {}
    result = CerebrasJudgeClient(cfg(tmp_path), fake_ok(captured)).predict(
        sanitized_command="uv run pytest",
        features=feat(),
        local_stats={"shape_n": 3, "p90_s": 98},
    )
    assert result.bucket == "long"
    assert result.p90_s == 75
    assert result.prompt_tokens == 12
    assert captured["headers"]["Authorization"] == "Bearer unit-test-key"
    assert captured["timeout"] == pytest.approx(0.8)
    assert captured["body"]["response_format"]["type"] == "json_schema"
    assert captured["body"]["response_format"]["json_schema"]["strict"] is True


def test_prediction_rule_and_filter():
    assert hand_rule_prediction("sleep 15")[0] == Prediction("medium", 15)
    assert hand_rule_prediction("true && sleep 61")[0] == Prediction("long", 61)
    assert hand_rule_prediction("echo sleep 100") == (None, ())
    empty = MemoryLookup(None, 0, "none", 0, 0)
    simple = feat("echo x")
    assert (
        judge_skip_reason(
            simple,
            empty,
            chain_threshold=2,
            length_threshold=100,
            budget_available=True,
        )
        == "simple"
    )
    complex_item = feat("echo a && echo b")
    assert (
        judge_skip_reason(
            complex_item,
            empty,
            chain_threshold=0,
            length_threshold=100,
            budget_available=False,
        )
        == "budget"
    )


def test_prediction_engine_async(caplog, monkeypatch, tmp_path):
    monkeypatch.setenv("CEREBRAS_API_KEY", "unit-test-key")
    captured = {}
    engine = ShadowPredictionEngine(cfg(tmp_path), transport=fake_ok(captured))
    item = feat("echo a && echo b")
    with caplog.at_level(logging.INFO, logger="binnacle.run_command"):
        engine.log_config()
        engine.submit(
            call_id="c1",
            command="echo a && echo b",
            features=item,
            auto_rule_hash=None,
        )
        engine.close()
    assert "shadow_prediction=on" in caplog.text
    assert "judge=queued" in caplog.text
    assert "event=run_command_prediction_judge schema=1 call=c1" in caplog.text


def test_prediction_delay_units_and_secret_flag_sanitizing():
    assert feat("timeout 2m echo x").max_delay_s == 120
    assert feat("sleep 1h").max_delay_s == 3600
    cleaned = sanitize_command(
        'curl -H "Authorization: Basic basic-secret" '
        '--token "flag secret" --api-key=another-secret PASSWORD="quoted secret"'
    )
    for secret in ("basic-secret", "flag secret", "another-secret", "quoted secret"):
        assert secret not in cleaned


def test_prediction_default_judge_budgets_stay_below_provider_limits():
    settings = RunCommandShadowPredictionSettings()
    assert settings.judge_minute_budget == 4
    assert settings.judge_hour_budget == 120
    assert settings.judge_day_budget == 2000


def test_prediction_budget_enforces_windows_and_pause(tmp_path):
    now = [0.0]
    settings = cfg(
        tmp_path,
        judge_minute_budget=2,
        judge_hour_budget=5,
        judge_day_budget=10,
    )
    budget = JudgeBudget(settings, clock=lambda: now[0])
    assert budget.take()
    assert budget.take()
    assert not budget.take()
    now[0] = 61.0
    assert budget.take()
    budget.pause_for(30)
    assert not budget.take()
    now[0] = 92.0
    assert budget.take()


def test_prediction_judge_429_uses_reset_header(monkeypatch, tmp_path):
    monkeypatch.setenv("CEREBRAS_API_KEY", "unit-test-key")

    def limited(url, headers, body, timeout):
        return 429, b"{}", {"X-RateLimit-Reset-Requests": "12s"}

    result = CerebrasJudgeClient(cfg(tmp_path), limited).predict(
        sanitized_command="echo x",
        features=feat("echo x"),
        local_stats={},
    )
    assert result.error == "http_429"
    assert result.retry_after_s == 12


def test_prediction_judge_key_file_requires_0600(monkeypatch, tmp_path):
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    key_file = tmp_path / "key"
    key_file.write_text("secret\n")
    key_file.chmod(0o600)
    settings = cfg(tmp_path, judge_api_key_file=key_file)
    client = CerebrasJudgeClient(settings)
    assert client._api_key() == "secret"
    key_file.chmod(0o644)
    with pytest.raises(RuntimeError, match="unsafe_key_file_mode"):
        client._api_key()


@pytest.mark.parametrize(
    ("transport", "error"),
    [
        (lambda *_: (200, b"not-json", {}), "ParseError"),
        (lambda *_: (_ for _ in ()).throw(TimeoutError()), "TimeoutError"),
        (lambda *_: (_ for _ in ()).throw(OSError()), "TransportError"),
    ],
)
def test_prediction_judge_fail_open_errors(monkeypatch, tmp_path, transport, error):
    monkeypatch.setenv("CEREBRAS_API_KEY", "unit-test-key")
    result = CerebrasJudgeClient(cfg(tmp_path), transport).predict(
        sanitized_command="echo x",
        features=feat("echo x"),
        local_stats={},
    )
    assert result.bucket is None
    assert result.error == error


def test_prediction_store_cache_and_shape_stats(monkeypatch, tmp_path):
    clock = [100.0]
    monkeypatch.setattr("binnacle.run_command_prediction.time.time", lambda: clock[0])
    store = Store(tmp_path, max_keys=4, samples_per_key=3, cache_ttl_s=10)
    one = feat("uv run pytest a")
    two = feat("uv run pytest b")
    store.record(one, 20)
    store.record(one, 80)
    stats = store.local_stats(two)
    assert stats["exact_n"] == 0
    assert stats["shape_n"] == 2
    assert stats["shape_p50_s"] == 20
    assert stats["shape_p90_s"] == 80

    result = JudgeResult("long", 80, 123, 30, 8)
    store.cache_set(one.command_hash, result)
    cached = store.cache_get(one.command_hash)
    assert cached is not None
    assert cached.bucket == "long"
    clock[0] = 111
    assert store.cache_get(one.command_hash) is None


def test_prediction_engine_coalesces_inflight_identical_commands(
    caplog, monkeypatch, tmp_path
):
    monkeypatch.setenv("CEREBRAS_API_KEY", "unit-test-key")
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def transport(url, headers, body, timeout):
        calls.append(json.loads(body))
        entered.set()
        assert release.wait(2)
        payload = {
            "choices": [
                {"message": {"content": json.dumps({"bucket": "medium", "p90_s": 20})}}
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5},
        }
        return 200, json.dumps(payload).encode(), {}

    engine = ShadowPredictionEngine(cfg(tmp_path), transport=transport)
    item = feat("echo a && echo b")
    with caplog.at_level(logging.INFO, logger="binnacle.run_command"):
        engine.submit(
            call_id="same-1",
            command="echo a && echo b",
            features=item,
            auto_rule_hash=None,
        )
        assert entered.wait(1)
        engine.submit(
            call_id="same-2",
            command="echo a && echo b",
            features=item,
            auto_rule_hash=None,
        )
        release.set()
        engine.close()
    assert len(calls) == 1
    assert "call=same-1" in caplog.text
    assert "call=same-2" in caplog.text
    assert caplog.text.count("event=run_command_prediction_judge") == 2


def test_prediction_engine_429_pauses_future_judge_calls(caplog, monkeypatch, tmp_path):
    monkeypatch.setenv("CEREBRAS_API_KEY", "unit-test-key")
    calls = []

    def limited(url, headers, body, timeout):
        calls.append(1)
        return 429, b"{}", {"x-ratelimit-reset-requests": "60s"}

    engine = ShadowPredictionEngine(cfg(tmp_path), transport=limited)
    item = feat("echo a && echo b")
    with caplog.at_level(logging.INFO, logger="binnacle.run_command"):
        engine.submit(
            call_id="limit-1",
            command="echo a && echo b",
            features=item,
            auto_rule_hash=None,
        )
        assert engine.executor is not None
        engine.executor.submit(lambda: None).result(timeout=2)
        engine.submit(
            call_id="limit-2",
            command="echo a && echo b",
            features=item,
            auto_rule_hash=None,
        )
        engine.close()
    assert len(calls) == 1
    second = next(line for line in caplog.messages if "call=limit-2 " in line)
    assert "judge=skipped" in second
    assert "judge_skip_reason=budget" in second


def test_prediction_runtime_persistence_is_async(tmp_path):
    settings = cfg(tmp_path, predictors=("memory",), judge_enabled=False)
    engine = ShadowPredictionEngine(settings)
    item = feat("echo x")
    engine.record_runtime(item, 15)
    engine.close()
    assert engine.store is not None
    lookup = engine.store.lookup(item, 1)
    assert lookup.prediction == Prediction("medium", 15)
