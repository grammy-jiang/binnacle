"""Execution-policy telemetry for ``run_command`` without changing its MCP schema."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("binnacle.run_command")

AUTO_BACKGROUND_SEMANTICS_VERSION = 1


def _short_hash(value: object) -> str:
    payload = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def auto_background_rule_hash(client_prefix: str, pattern: str) -> str:
    """Stable non-reversible identifier for one configured rule."""
    return _short_hash([client_prefix, pattern])


def auto_background_policy_hash(
    patterns: Mapping[str, Sequence[str]],
) -> str:
    """Fingerprint the ordered effective policy; order is currently semantic."""
    return _short_hash([[prefix, list(rules)] for prefix, rules in patterns.items()])


def auto_background_behavior_hash(
    patterns: Mapping[str, Sequence[str]],
    auto_warmup_s: float,
    semantics_version: int = AUTO_BACKGROUND_SEMANTICS_VERSION,
) -> str:
    """Fingerprint config plus behavior semantics that affect auto handoff."""

    return _short_hash(
        [
            "run_command_auto_background",
            semantics_version,
            auto_warmup_s,
            [[prefix, list(rules)] for prefix, rules in patterns.items()],
        ]
    )


_CHAIN = re.compile(r"&&|\|\||;|\n|\|")
_DELAY = re.compile(r"(?i)\b(?:sleep|timeout)\s+(?:--\s+)?(\d+(?:\.\d+)?)([smhd]?)")
_SIMPLE_RUNNERS_TEXT = (
    "pytest tox pip apt npm cargo make curl wget rsync tar find systemctl docker ssh"
)
_SIMPLE_RUNNERS = _SIMPLE_RUNNERS_TEXT.split()
_SPECIAL_RUNNERS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in (
        ("pre-commit", r"\bpre-commit\b"),
        ("uv-run", r"(?:^|[\s;&|])uv\s+run(?:\s|$)"),
        ("uv-sync", r"(?:^|[\s;&|])uv\s+sync(?:\s|$)"),
        ("uv-tool", r"(?:^|[\s;&|])uv\s+tool(?:\s|$)"),
        ("git-push", r"(?:^|[\s;&|])git\s+push(?:\s|$)"),
        ("git-fetch", r"(?:^|[\s;&|])git\s+fetch(?:\s|$)"),
        ("git-clone", r"(?:^|[\s;&|])git\s+clone(?:\s|$)"),
        ("git-pull", r"(?:^|[\s;&|])git\s+pull(?:\s|$)"),
        ("gh-run-watch", r"(?:^|[\s;&|])gh\s+run\s+watch(?:\s|$)"),
        ("journalctl-f", r"(?:^|[\s;&|])journalctl\b[^;&\n]*\s-f(?:\s|$)"),
        ("sleep", r"(?:^|[\s;&|])sleep\s+\d"),
        ("timeout", r"(?:^|[\s;&|])timeout\s+\d"),
    )
)


@dataclass(frozen=True)
class CommandFeatures:
    command_hash: str
    shape_key: str
    shape_hash: str
    feature_hash: str
    first_token_class: str
    runner_flags: tuple[str, ...]
    max_delay_s: float
    heredoc: bool
    len_chars: int
    chain_n: int
    declared_wait_s: int
    declared_background: str
    declared_tail_lines: int | None


def _effective_token(command: str) -> str:
    text = command.strip()
    for _ in range(4):
        changed = re.sub(r"^set\s+-[^;\n]+(?:;|&&)\s*", "", text, count=1)
        changed = re.sub(r"^cd\s+[^;&\n]+&&\s*", "", changed, count=1)
        if changed == text:
            break
        text = changed.strip()
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = re.findall(r"[^\s;&|]+", text)
    i = int(bool(tokens and tokens[0] == "env"))
    while i < len(tokens) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[i]):
        i += 1
    if i < len(tokens) and tokens[i] == "sudo":
        i += 1
        while i < len(tokens) and tokens[i].startswith("-"):
            i += 1
    if i < len(tokens) and tokens[i] == "timeout":
        i += 1
        while i < len(tokens) and tokens[i].startswith("-"):
            i += 1
        if i < len(tokens) and re.fullmatch(r"\d+(?:\.\d+)?[smhd]?", tokens[i]):
            i += 1
    return tokens[i] if i < len(tokens) else ""


def _first_token_class(token: str) -> str:
    base = Path(token).name.lower()
    if base == "python" or re.fullmatch(r"python3(?:\.\d+)?", base):
        return "python"
    if base in {"uv", "pytest", "git"}:
        return base
    if base in {
        "cd",
        "set",
        "export",
        "source",
        ".",
        "printf",
        "echo",
        "read",
        "test",
        "[",
    }:
        return "shell-builtin"
    return "script-path" if "/" in token or base.endswith((".py", ".sh")) else "other"


def build_command_features(
    command: str,
    *,
    wait_seconds: int,
    declared_background: str,
    tail_lines: int | None,
) -> CommandFeatures:
    token_class = _first_token_class(_effective_token(command))
    simple = tuple(
        name
        for name in _SIMPLE_RUNNERS
        if re.search(
            rf"(?:^|[\s;&|]){re.escape(name)}(?:-get)?(?:\s|$)", command, re.IGNORECASE
        )
    )
    special = tuple(
        name for name, pattern in _SPECIAL_RUNNERS if pattern.search(command)
    )
    runners = tuple(dict.fromkeys((*simple, *special)))
    unit_seconds = {"": 1.0, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}
    delays = [
        float(value) * unit_seconds[unit.lower()]
        for value, unit in _DELAY.findall(command)
    ]
    max_delay = max(delays, default=0.0)
    chain_n = len(_CHAIN.findall(command))
    heredoc = "<<" in command
    delay = (
        "0"
        if max_delay <= 0
        else "1-9"
        if max_delay < 10
        else "10-60"
        if max_delay <= 60
        else "60+"
    )
    length = (
        "<200" if len(command) < 200 else "200-799" if len(command) < 800 else "800+"
    )
    chain = "0" if chain_n == 0 else "1-2" if chain_n <= 2 else "3+"
    shape = "|".join(
        (
            f"first={token_class}",
            f"runners={','.join(runners) or '-'}",
            f"delay={delay}",
            f"heredoc={int(heredoc)}",
            f"len={length}",
            f"chain={chain}",
            f"wait={wait_seconds}",
            f"background={declared_background}",
            f"tail={tail_lines if tail_lines is not None else '-'}",
        )
    )
    material = {
        "shape": shape,
        "delay": round(max_delay, 3),
        "chars": len(command),
        "chain": chain_n,
    }
    return CommandFeatures(
        hashlib.sha256(command.encode()).hexdigest(),
        shape,
        _short_hash(shape),
        _short_hash(material),
        token_class,
        runners,
        max_delay,
        heredoc,
        len(command),
        chain_n,
        wait_seconds,
        declared_background,
        tail_lines,
    )


@dataclass(frozen=True)
class DispatchPlan:
    requested_wait_s: int
    bounded_wait_s: int
    effective_wait_s: float
    background_requested: bool
    background_arg: str
    auto_background: bool
    client: str | None
    owner: str
    command_hash: str
    command_chars: int
    auto_policy_hash: str
    auto_behavior_hash: str
    auto_semantics_version: int
    auto_warmup_s: float
    auto_rule_hash: str | None
    auto_match_start: int | None
    auto_match_end: int | None

    @classmethod
    def build(
        cls,
        *,
        command: str,
        wait_seconds: int,
        background: bool,
        argument_names: frozenset[str],
        client: str | None,
        settings: Any,
        warmup_s: float,
        wait_max_s: int,
        owner: str,
    ) -> DispatchPlan:
        bounded = max(1, min(wait_seconds, wait_max_s))
        match = None
        if not background and "background" not in argument_names:
            match = settings.match_auto_background(client, command)
        auto = match is not None
        effective = warmup_s if background or auto else float(bounded)
        background_arg = (
            str(background).lower() if "background" in argument_names else "omitted"
        )
        return cls(
            requested_wait_s=wait_seconds,
            bounded_wait_s=bounded,
            effective_wait_s=effective,
            background_requested=background,
            background_arg=background_arg,
            auto_background=auto,
            client=client,
            owner=owner,
            command_hash=hashlib.sha256(command.encode()).hexdigest()[:12],
            command_chars=len(command),
            auto_policy_hash=auto_background_policy_hash(
                settings.auto_background_patterns
            ),
            auto_behavior_hash=auto_background_behavior_hash(
                settings.auto_background_patterns, warmup_s
            ),
            auto_semantics_version=AUTO_BACKGROUND_SEMANTICS_VERSION,
            auto_warmup_s=warmup_s,
            auto_rule_hash=(
                auto_background_rule_hash(match.client_prefix, match.pattern)
                if match is not None
                else None
            ),
            auto_match_start=match.match_start if match is not None else None,
            auto_match_end=match.match_end if match is not None else None,
        )

    def log_auto_background(self, call_id: str) -> None:
        if self.auto_background:
            log.info(
                "event=run_command_auto_background call=%s client=%s command_hash=%s "
                "policy_hash=%s behavior_hash=%s semantics_version=%s "
                "auto_warmup_s=%s rule_hash=%s match_start=%s match_end=%s",
                call_id,
                self.client or "-",
                self.command_hash,
                self.auto_policy_hash,
                self.auto_behavior_hash,
                self.auto_semantics_version,
                self.auto_warmup_s,
                self.auto_rule_hash or "-",
                self.auto_match_start if self.auto_match_start is not None else "-",
                self.auto_match_end if self.auto_match_end is not None else "-",
            )

    def handoff_reason(self, state: str) -> str:
        if state == "exited":
            return "synchronous"
        if self.auto_background:
            return "auto_background"
        if self.background_requested:
            return "explicit_background"
        return "wait_expired"

    def log_success(
        self,
        call_id: str,
        job_id: str,
        state: str,
        owner_roundtrip_ms: float,
        owner_instance: str,
    ) -> None:
        log.info(
            "event=run_command_dispatch call=%s client=%s job_id=%s owner=%s "
            "owner_instance=%s requested_wait_s=%s bounded_wait_s=%s effective_wait_s=%s "
            "background_arg=%s auto_background=%s handoff_reason=%s "
            "owner_roundtrip_ms=%.2f command_hash=%s command_chars=%d state=%s",
            call_id,
            self.client or "-",
            job_id,
            self.owner,
            owner_instance,
            self.requested_wait_s,
            self.bounded_wait_s,
            self.effective_wait_s,
            self.background_arg,
            str(self.auto_background).lower(),
            self.handoff_reason(state),
            owner_roundtrip_ms,
            self.command_hash,
            self.command_chars,
            state,
        )

    def log_error(
        self, call_id: str, owner_roundtrip_ms: float, exc: Exception
    ) -> None:
        log.warning(
            "event=run_command_dispatch_error call=%s client=%s owner=%s "
            "requested_wait_s=%s bounded_wait_s=%s effective_wait_s=%s "
            "background_arg=%s auto_background=%s owner_roundtrip_ms=%.2f "
            "command_hash=%s command_chars=%d error_class=%s",
            call_id,
            self.client or "-",
            self.owner,
            self.requested_wait_s,
            self.bounded_wait_s,
            self.effective_wait_s,
            self.background_arg,
            str(self.auto_background).lower(),
            owner_roundtrip_ms,
            self.command_hash,
            self.command_chars,
            type(exc).__name__,
        )


@dataclass(frozen=True)
class Prediction:
    bucket: str
    p90_s: float


@dataclass(frozen=True)
class MemoryLookup:
    prediction: Prediction | None
    sample_count: int
    source: str
    exact_n: int
    shape_n: int


def _prediction_number(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}".rstrip("0").rstrip(".")


def log_shadow_config(
    enabled: bool,
    predictors: tuple[str, ...],
    filter_hash: str,
) -> None:
    log.info(
        "event=tool_config tool=run_command shadow_prediction=%s predictors=%s "
        "filter_hash=%s",
        "on" if enabled else "off",
        ",".join(predictors) or "-",
        filter_hash,
    )


def log_shadow_dropped_predictors(dropped: tuple[str, ...]) -> None:
    log.warning(
        "event=run_command_prediction_config_warning schema=1 "
        "dropped_predictors=%s reason=removed_predictor",
        ",".join(dropped),
    )


def log_shadow_prediction(
    call_id: str,
    features: CommandFeatures,
    auto_rule_hash: str | None,
    memory: MemoryLookup,
    memory_store_keys: int,
    rules: Prediction | None,
    hits: tuple[str, ...],
) -> None:
    mp = memory.prediction
    values = (
        call_id,
        features.feature_hash,
        features.shape_hash,
        features.first_token_class,
        int(features.heredoc),
        features.chain_n,
        _prediction_number(features.max_delay_s),
        features.len_chars,
        features.declared_wait_s,
        features.declared_background,
        auto_rule_hash or "-",
        mp.bucket if mp else "-",
        _prediction_number(mp.p90_s if mp else None),
        memory.sample_count,
        memory.source,
        memory_store_keys,
        rules.bucket if rules else "-",
        _prediction_number(rules.p90_s if rules else None),
        ",".join(hits) or "-",
    )
    log.info(
        "event=run_command_prediction schema=1 call=%s feature_hash=%s shape_hash=%s "
        "first_token_class=%s heredoc=%d chain_n=%d max_delay_s=%s len_chars=%d "
        "declared_wait_s=%d declared_background=%s auto_rule=%s memory_bucket=%s "
        "memory_p90_s=%s memory_n=%d memory_source=%s memory_store_keys=%d "
        "rules_bucket=%s rules_p90_s=%s rules_hits=%s",
        *values,
    )


def log_shadow_memory_error(error: str) -> None:
    log.warning("event=run_command_prediction_memory_error schema=1 error=%s", error)


def prediction_runtime_bucket(seconds: float) -> str:
    return "short" if seconds < 10 else "medium" if seconds <= 60 else "long"
