from __future__ import annotations
# ruff: noqa: I001

import hashlib
import json
import math
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from binnacle.run_command_telemetry import (
    CommandFeatures,
    MemoryLookup,
    Prediction,
    log_shadow_config,
    log_shadow_dropped_predictors,
    log_shadow_memory_error,
    log_shadow_prediction,
    prediction_runtime_bucket as runtime_bucket,
)

_SLEEP = re.compile(
    r'(?ix)(?:^|(?:&&|\|\||[;|&({"\'])\s*|\b(?:do|then)\s+)sleep\s+'
    r'(\d+(?:\.\d+)?)([sm]?)(?=$|[\s;|&)}"\'])'
)


def _hash(value: object, length: int = 12) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:length]


def _pctl(values: list[float], q: float) -> float:
    return float(sorted(values)[max(0, math.ceil(q * len(values)) - 1)])


class MemoryStore:
    def __init__(self, root: Path, *, max_keys: int, samples_per_key: int) -> None:
        self.root = root
        self.path = root / "memory.json"
        self.max_keys = max_keys
        self.samples_per_key = samples_per_key
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        # A file written before 2026-09-27 also holds a "cache" table of judge
        # answers; it is ignored here and dropped on the next write.
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("version") == 1:
                return {
                    group: {
                        str(key): [float(value) for value in values]
                        for key, values in raw.get(group, {}).items()
                    }
                    for group in ("exact", "shape")
                }
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return {"exact": {}, "shape": {}}

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


class ShadowPredictionEngine:
    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.enabled = bool(settings.enabled)
        self.predictors = tuple(settings.predictors)
        self.store: MemoryStore | None = None
        self.executor: ThreadPoolExecutor | None = None
        if self.enabled:
            self.store = MemoryStore(
                settings.memory_dir,
                max_keys=settings.memory_max_keys,
                samples_per_key=settings.memory_samples_per_key,
            )
            self.executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="binnacle-shadow-memory"
            )

    def log_config(self) -> None:
        log_shadow_config(
            enabled=self.enabled,
            predictors=self.predictors,
            filter_hash=_hash((self.settings.memory_min_samples,)),
        )
        dropped = tuple(getattr(self.settings, "dropped_predictors", ()))
        if dropped:
            log_shadow_dropped_predictors(dropped)

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
        log_shadow_prediction(
            call_id=call_id,
            features=features,
            auto_rule_hash=auto_rule_hash,
            memory=memory,
            memory_store_keys=store.key_count,
            rules=rules,
            hits=hits,
        )

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
