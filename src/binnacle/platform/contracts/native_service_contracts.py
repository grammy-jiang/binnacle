"""Generation-bound native service plans and authenticated channel contracts.

A label or copied marker alone grants no authority. Mutations validate the owned
UID, generation and root inode; manager mutations require the quiet-job gate.
Rollback restores only owned prior state and verifies service and socket absence.
Channels require peer identity and a live generation challenge in a private root.
The existing Linux UnitProvisioner and RPC framing remain separate and unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from binnacle.platform.contracts.capability_contracts import Capability


@dataclass(frozen=True)
class ServiceLease:
    uid: int
    label: str
    generation: str
    root_device: int
    root_inode: int


@dataclass(frozen=True)
class ServicePlan:
    lease: ServiceLease
    plist_bytes: bytes
    plist_path: Path
    expected_previous_sha256: str | None


@dataclass(frozen=True)
class ServiceReceipt:
    lease: ServiceLease
    action: str
    capability: Capability
    absent: bool


class NativeProvisioner(Protocol):
    def plan(
        self,
        lease: ServiceLease,
        *,
        argv: Sequence[str],
        environment: Mapping[str, str],
        workdir: Path,
    ) -> ServicePlan: ...
    def apply(self, plan: ServicePlan) -> ServiceReceipt: ...
    def rollback(self, plan: ServicePlan) -> ServiceReceipt: ...


class AuthenticatedChannel(Protocol):
    def request(
        self, payload: Mapping[str, object], *, timeout_s: float
    ) -> Mapping[str, object]: ...
    def close(self) -> None: ...
