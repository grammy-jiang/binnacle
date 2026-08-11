"""Append-only audit and obligation boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from binnacle.domain.audit import AuditAppendResult, AuditEventDraft, AuditTail


@dataclass(frozen=True, slots=True)
class AuditObligation:
    schema_version: str
    obligation_id: str
    operation_id: str
    running_state_version: int


@dataclass(frozen=True, slots=True)
class AuditObligationRecovery:
    obligation_id: str
    operation_id: str
    running_state_version: int
    generation: int
    effect_outcome: str
    evidence_sha256: str
    event_hash: str


class AuditJournal(Protocol):
    @property
    def tail(self) -> AuditTail: ...

    async def append(self, draft: AuditEventDraft) -> AuditAppendResult: ...

    async def append_emergency(
        self,
        *,
        reason_code: str,
        operation_id: str | None,
        source_event_id: str,
    ) -> None: ...

    async def find_obligation_evidence(
        self,
        *,
        obligation_id: str,
        operation_id: str,
        running_state_version: int,
    ) -> str | None: ...

    async def find_generation_recovery(self, generation: int) -> str | None: ...

    async def list_obligation_recoveries(
        self, generation: int
    ) -> tuple[AuditObligationRecovery, ...]: ...

    async def find_generation_verification(self, generation: int) -> str | None: ...


class AuditObligationStore(Protocol):
    async def publish(self, obligation: AuditObligation) -> None: ...

    async def remove(self, obligation_id: str) -> None: ...

    async def scan(self) -> tuple[AuditObligation, ...]: ...
