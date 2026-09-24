"""Execution-policy telemetry for ``run_command`` without changing its MCP schema."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("binnacle.run_command")


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
    auto_rule_hash: str | None

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
            auto_rule_hash=(
                auto_background_rule_hash(match.client_prefix, match.pattern)
                if match is not None
                else None
            ),
        )

    def log_auto_background(self, call_id: str) -> None:
        if self.auto_background:
            log.info(
                "event=run_command_auto_background call=%s client=%s command_hash=%s "
                "policy_hash=%s rule_hash=%s",
                call_id,
                self.client or "-",
                self.command_hash,
                self.auto_policy_hash,
                self.auto_rule_hash or "-",
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
