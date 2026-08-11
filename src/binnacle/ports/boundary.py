"""Final consequential-boundary predicate verification."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PreparedStateCheck:
    operation_id: str
    prepared_operation_id: str
    protected_facts: Mapping[str, str]


class PreparedStateVerifier(Protocol):
    async def current_state_digest(self, request: PreparedStateCheck) -> str: ...


@dataclass(frozen=True, slots=True)
class OperationBoundaryCheck:
    operation_id: str
    expected_state_version: int
    predicates: Mapping[str, str | bool | int | None]


@dataclass(frozen=True, slots=True)
class BoundaryCheckResult:
    allowed: bool
    reason_code: str


class OperationBoundaryVerifier(Protocol):
    async def verify(self, request: OperationBoundaryCheck) -> BoundaryCheckResult: ...
