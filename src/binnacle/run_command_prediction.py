from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import urllib.error
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from binnacle.config import (
    JudgeBudget,
    read_cerebras_api_key,
)
from binnacle.config import (
    run_command_cerebras_reset_seconds as _reset_seconds,
)
from binnacle.config import (
    run_command_cerebras_transport as _urlopen_transport,
)
from binnacle.run_command_telemetry import (
    CommandFeatures,
    JudgeResult,
    MemoryLookup,
    Prediction,
    log_shadow_config,
    log_shadow_judge,
    log_shadow_memory_error,
    log_shadow_prediction,
)
from binnacle.run_command_telemetry import (
    prediction_optional_int as _optional_int,
)
from binnacle.run_command_telemetry import (
    prediction_runtime_bucket as runtime_bucket,
)

_BUCKETS = {"short", "medium", "long"}
_SLEEP = re.compile(
    r'(?ix)(?:^|(?:&&|\|\||[;|&({"\'])\s*|\b(?:do|then)\s+)sleep\s+'
    r'(\d+(?:\.\d+)?)([sm]?)(?=$|[\s;|&)}"\'])'
)
_FAST_SKIP = re.compile(
    r"(?ix)^(?:(?P<fast_shell>cd|ls|cat|echo|printf)(?:\s|$)|(?P<fast_git_read>git(?:\s+(?:-C\s+\S+|--no-pager))*\s+(?:status|log|diff|show)\b)|(?P<fast_file_read>sed\s+-n\s+\S+\s+\S+|(?:head|tail|wc)\b.*\s+\S+|grep\b(?:\s+-\S+)*\s+\S+\s+\S+))"
)
_CREDENTIAL = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)[A-Z0-9_]*)"
    r"\s*=\s*(?:'[^']*'|\"[^\"]*\"|[^\s]+)"
)
_LONG_ASSIGNMENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)=([^\s'\"]{21,})")
_SECRET_FLAG = re.compile(
    r"(?i)(--?(?:api[-_]?key|token|password|passwd|secret|credential)(?:=|\s+))"
    r"(?:'[^']*'|\"[^\"]*\"|[^\s]+)"
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_BLOB = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Fa-f0-9]{21,}|[A-Za-z0-9+/=_-]{32,})(?![A-Za-z0-9])"
)
_LONG_QUOTED = re.compile(r"(['\"])(?:(?!\1).){80,}\1", re.DOTALL)
Transport = Callable[..., tuple[int, bytes, Mapping[str, str]]]
_JUDGE_SYSTEM = "Estimate runtime; prefer local history. Return requested JSON only."
_JUDGE_FORMAT = json.loads(
    """{"type":"json_schema","json_schema":{"name":"run_command_runtime_prediction","strict":true,"schema":{"type":"object","properties":{"bucket":{"type":"string","enum":["short","medium","long"]},"p90_s":{"type":"number","minimum":0}},"required":["bucket","p90_s"],"additionalProperties":false}}}"""
)


def _hash(value: object, length: int = 12) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:length]


def sanitize_command(command: str, *, max_chars: int = 1200) -> str:
    text = command.replace(str(Path.home()), "~")
    text = re.sub(r"/home/[^/\s]+", "~", text)
    text = re.sub(
        r"(?i)\bAuthorization\s*[:=]\s*(?:(?:Bearer|Basic)\s+)?[^\s'\"]+",
        "Authorization=<redacted>",
        text,
    )
    text = re.sub(r"(?i)\bBearer\s+[^\s]+", "Bearer <redacted>", text)
    text = _CREDENTIAL.sub(lambda m: f"{m.group(1)}=<redacted>", text)
    text = _SECRET_FLAG.sub(lambda m: f"{m.group(1)}<redacted>", text)
    text = _LONG_ASSIGNMENT.sub(lambda m: f"{m.group(1)}=<redacted>", text)
    text = _EMAIL.sub("<email>", text)
    text = _BLOB.sub("<blob>", text)
    text = _LONG_QUOTED.sub(lambda m: f"{m.group(1)}<long-literal>{m.group(1)}", text)
    return " ".join(text.split())[:max_chars]


def _pctl(values: list[float], q: float) -> float:
    return float(sorted(values)[max(0, math.ceil(q * len(values)) - 1)])


class MemoryStore:
    def __init__(
        self, root: Path, *, max_keys: int, samples_per_key: int, cache_ttl_s: int
    ) -> None:
        self.root = root
        self.path = root / "memory.json"
        self.max_keys = max_keys
        self.samples_per_key = samples_per_key
        self.cache_ttl_s = cache_ttl_s
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("version") == 1:
                tables = {
                    group: {
                        str(key): [float(value) for value in values]
                        for key, values in raw.get(group, {}).items()
                    }
                    for group in ("exact", "shape")
                }
                return {**tables, "cache": dict(raw.get("cache", {}))}
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return {"exact": {}, "shape": {}, "cache": {}}

    def _write(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        tmp = self.path.with_suffix(".tmp")
        payload = json.dumps({"version": 1, **self._data}, separators=(",", ":"))
        tmp.write_text(payload, encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def lookup(self, features: CommandFeatures, min_samples: int) -> MemoryLookup:
        with self._lock:
            exact = list(self._data["exact"].get(features.command_hash, ()))
            shape = list(self._data["shape"].get(features.shape_key, ()))
        counts = (len(exact), len(shape))
        for values, source in ((exact, "exact"), (shape, "shape")):
            if len(values) >= min_samples:
                p90 = _pctl(values, 0.90)
                prediction = Prediction(runtime_bucket(p90), p90)
                return MemoryLookup(prediction, len(values), source, *counts)
        return MemoryLookup(None, max(counts), "none", *counts)

    def local_stats(self, features: CommandFeatures) -> dict[str, Any]:
        with self._lock:
            exact = list(self._data["exact"].get(features.command_hash, ()))
            shape = list(self._data["shape"].get(features.shape_key, ()))
        stats: dict[str, Any] = {}
        for name, values in (("exact", exact), ("shape", shape)):
            stats[f"{name}_n"] = len(values)
            stats[f"{name}_p50_s"] = _pctl(values, 0.5) if values else None
            stats[f"{name}_p90_s"] = _pctl(values, 0.9) if values else None
        return stats

    def record(self, features: CommandFeatures, runtime_s: float) -> None:
        if runtime_s < 0:
            return
        with self._lock:
            for group, key in (
                ("exact", features.command_hash),
                ("shape", features.shape_key),
            ):
                table = self._data[group]
                values = list(table.pop(key, []))
                table[key] = (values + [float(runtime_s)])[-self.samples_per_key :]
                while len(table) > self.max_keys:
                    table.pop(next(iter(table)))
            self._write()

    def cache_get(self, command_hash: str) -> JudgeResult | None:
        with self._lock:
            row = self._data["cache"].get(command_hash)
            if not row or float(row.get("expires", 0)) <= time.time():
                self._data["cache"].pop(command_hash, None)
                return None
            return JudgeResult(
                str(row["bucket"]),
                float(row["p90_s"]),
                0.0,
                _optional_int(row.get("prompt_tokens")),
                _optional_int(row.get("completion_tokens")),
            )

    def cache_set(self, command_hash: str, result: JudgeResult) -> None:
        if result.bucket not in _BUCKETS or result.p90_s is None:
            return
        with self._lock:
            cache = self._data["cache"]
            cache.pop(command_hash, None)
            cache[command_hash] = {
                "expires": time.time() + self.cache_ttl_s,
                "bucket": result.bucket,
                "p90_s": result.p90_s,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
            }
            while len(cache) > self.max_keys:
                cache.pop(next(iter(cache)))
            self._write()

    @property
    def key_count(self) -> int:
        with self._lock:
            return len(self._data["exact"]) + len(self._data["shape"])


def hand_rule_prediction(command: str) -> tuple[Prediction | None, tuple[str, ...]]:
    delays = [
        float(value) * (60 if unit.lower() == "m" else 1)
        for value, unit in _SLEEP.findall(command)
    ]
    delays.extend(
        map(
            float,
            re.findall(r"(?i)\btime\.sleep\s*\(\s*(\d+(?:\.\d+)?)\s*\)", command),
        )
    )
    if not (delays := [value for value in delays if value >= 10]):
        return None, ()
    p90 = max(delays)
    return Prediction(runtime_bucket(p90), p90), ("sleep_ge_10",)


def judge_skip_reason(
    features: CommandFeatures,
    memory: MemoryLookup,
    *,
    chain_threshold: int,
    length_threshold: int,
    budget_available: bool,
    command: str | None = None,
) -> str | None:
    if memory.prediction is not None:
        return "history"
    complex_shape = features.heredoc or features.chain_n > chain_threshold
    complex_shape |= features.len_chars > length_threshold
    if not complex_shape and command is not None:
        match = _FAST_SKIP.match(command.lstrip())
        if match is not None:
            return match.lastgroup
    return None if budget_available else "budget"


class CerebrasJudgeClient:
    def __init__(self, settings: Any, transport: Transport | None = None) -> None:
        self.settings = settings
        self.transport = transport or _urlopen_transport

    def _api_key(self) -> str:
        return read_cerebras_api_key(self.settings)

    def predict(
        self,
        *,
        sanitized_command: str,
        features: CommandFeatures,
        local_stats: Mapping[str, Any],
    ) -> JudgeResult:
        started = time.perf_counter()
        try:
            prompt = {
                "host": "Raspberry Pi 5, 4 cores",
                "command": sanitized_command,
                "shape_hash": features.shape_hash,
                "first_token_class": features.first_token_class,
                "runner_flags": list(features.runner_flags),
                "max_delay_s": features.max_delay_s,
                "heredoc": features.heredoc,
                "chain_n": features.chain_n,
                "len_chars": features.len_chars,
                "local_history": dict(local_stats),
                "output": {"bucket": "short|medium|long", "p90_s": "number"},
            }
            body = json.dumps(
                {
                    "model": self.settings.judge_model,
                    "reasoning_effort": "low",
                    "messages": [
                        {"role": "system", "content": _JUDGE_SYSTEM},
                        {
                            "role": "user",
                            "content": json.dumps(prompt, separators=(",", ":")),
                        },
                    ],
                    "response_format": _JUDGE_FORMAT,
                    "temperature": 0,
                },
                separators=(",", ":"),
            ).encode()
            status, payload, response_headers = self.transport(
                self.settings.judge_endpoint,
                {
                    "Authorization": f"Bearer {self._api_key()}",
                    "Content-Type": "application/json",
                    "User-Agent": "binnacle-shadow-judge/1",
                },
                body,
                self.settings.judge_timeout_ms / 1000,
            )
            if status >= 400:
                error = f"http_{status}"
                retry = _reset_seconds(response_headers) if status == 429 else None
                latency = (time.perf_counter() - started) * 1000
                return JudgeResult(None, None, latency, None, None, error, retry)
            decoded = json.loads(payload)
            answer = json.loads(decoded["choices"][0]["message"]["content"])
            bucket, p90 = str(answer["bucket"]), float(answer["p90_s"])
            if bucket not in _BUCKETS or p90 < 0:
                raise ValueError
            usage = decoded.get("usage") or {}
            return JudgeResult(
                bucket,
                p90,
                (time.perf_counter() - started) * 1000,
                _optional_int(usage.get("prompt_tokens")),
                _optional_int(usage.get("completion_tokens")),
            )
        except TimeoutError:
            error = "TimeoutError"
        except (OSError, urllib.error.URLError):
            error = "TransportError"
        except (ValueError, TypeError, KeyError):
            error = "ParseError"
        except RuntimeError as exc:
            error = str(exc).replace(" ", "_")[:48]
        latency = (time.perf_counter() - started) * 1000
        return JudgeResult(None, None, latency, error=error)


class ShadowPredictionEngine:
    def __init__(self, settings: Any, *, transport: Transport | None = None) -> None:
        self.settings = settings
        self.enabled = bool(settings.enabled)
        self.predictors = tuple(settings.predictors)
        self._budget = JudgeBudget(settings)
        self._inflight_lock = threading.Lock()
        self._inflight: dict[str, list[str]] = {}
        self.store: MemoryStore | None = None
        self.judge: CerebrasJudgeClient | None = None
        self.executor: ThreadPoolExecutor | None = None
        if self.enabled:
            self.store = MemoryStore(
                settings.memory_dir,
                max_keys=settings.memory_max_keys,
                samples_per_key=settings.memory_samples_per_key,
                cache_ttl_s=settings.judge_cache_ttl_s,
            )
            self.judge = CerebrasJudgeClient(settings, transport)
            self.executor = ThreadPoolExecutor(
                max_workers=settings.judge_workers,
                thread_name_prefix="binnacle-shadow-judge",
            )

    def log_config(self) -> None:
        s = self.settings
        filter_values = (
            s.memory_min_samples,
            s.judge_complex_chain_threshold,
            s.judge_complex_length_threshold,
            s.judge_minute_budget,
            s.judge_hour_budget,
            s.judge_day_budget,
            s.judge_cache_ttl_s,
        )
        log_shadow_config(
            enabled=self.enabled,
            predictors=self.predictors,
            judge_model=s.judge_model.replace(" ", "_") if s.judge_enabled else "-",
            filter_hash=_hash(filter_values),
            sanitizer_hash=_hash((1, s.sanitized_command_max_chars)),
        )

    def submit(
        self,
        *,
        call_id: str,
        command: str,
        features: CommandFeatures,
        auto_rule_hash: str | None,
    ) -> None:
        store = self.store
        if not self.enabled or store is None:
            return
        history = store.lookup(features, self.settings.memory_min_samples)
        memory = (
            history
            if "memory" in self.predictors
            else MemoryLookup(None, 0, "none", history.exact_n, history.shape_n)
        )
        rules, hits = (
            hand_rule_prediction(command) if "rules" in self.predictors else (None, ())
        )
        state = "disabled"
        skip: str | None = None
        cache_state, cached, queued = "-", None, False
        if "judge" in self.predictors and self.settings.judge_enabled:
            skip = judge_skip_reason(
                features,
                history,
                chain_threshold=self.settings.judge_complex_chain_threshold,
                length_threshold=self.settings.judge_complex_length_threshold,
                budget_available=True,
                command=command,
            )
            state = "skipped"
            if skip is None:
                with self._inflight_lock:
                    cached = store.cache_get(features.command_hash)
                    if cached is not None:
                        state, cache_state = "cached", "hit"
                    elif features.command_hash in self._inflight:
                        self._inflight[features.command_hash].append(call_id)
                        state, cache_state = "queued", "hit"
                    elif self._budget.take():
                        self._inflight[features.command_hash] = [call_id]
                        state, cache_state, queued = "queued", "miss", True
                    else:
                        skip, cache_state = "budget", "miss"
        log_shadow_prediction(
            call_id=call_id,
            features=features,
            auto_rule_hash=auto_rule_hash,
            memory=memory,
            memory_store_keys=store.key_count,
            rules=rules,
            hits=hits,
            judge=(state, skip, cache_state),
        )
        if cached is not None:
            self._log_judge(call_id, cached)
        elif queued:
            executor = self.executor
            if executor is None:
                self._log_judge(
                    call_id, JudgeResult(None, None, 0.0, error="ExecutorUnavailable")
                )
                return
            try:
                executor.submit(self._judge_task, command, features)
            except RuntimeError:
                with self._inflight_lock:
                    waiters = self._inflight.pop(features.command_hash, [call_id])
                failed = JudgeResult(None, None, 0.0, error="ExecutorUnavailable")
                for waiter in waiters:
                    self._log_judge(waiter, failed)

    def _judge_task(self, command: str, features: CommandFeatures) -> None:
        store, judge = self.store, self.judge
        if store is None or judge is None:
            return
        try:
            result = judge.predict(
                sanitized_command=sanitize_command(
                    command, max_chars=self.settings.sanitized_command_max_chars
                ),
                features=features,
                local_stats=store.local_stats(features),
            )
        except Exception as exc:  # noqa: BLE001 - shadow work must fail open
            result = JudgeResult(None, None, 0.0, error=type(exc).__name__)
        if result.error == "http_429":
            self._budget.pause_for(result.retry_after_s)
        if result.error is None:
            try:
                store.cache_set(features.command_hash, result)
            except OSError:
                log_shadow_memory_error("OSError")
        with self._inflight_lock:
            waiters = self._inflight.pop(features.command_hash, [])
        for call_id in waiters:
            self._log_judge(call_id, result)

    def _log_judge(self, call_id: str, result: JudgeResult) -> None:
        model = self.settings.judge_model.replace(" ", "_")[:80]
        log_shadow_judge(call_id, model, result)

    def record_runtime(self, features: CommandFeatures, runtime_s: float) -> None:
        if not self.enabled or self.store is None or self.executor is None:
            return
        try:
            self.executor.submit(self._record_runtime_task, features, runtime_s)
        except RuntimeError:
            log_shadow_memory_error("ExecutorUnavailable")

    def _record_runtime_task(self, features: CommandFeatures, runtime_s: float) -> None:
        store = self.store
        if store is None:
            return
        try:
            store.record(features, runtime_s)
        except OSError:
            log_shadow_memory_error("OSError")

    def close(self) -> None:
        if self.executor is not None:
            self.executor.shutdown(wait=True)
