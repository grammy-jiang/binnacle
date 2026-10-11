"""Bounded observation over an injected, already authenticated A3 channel.

The v1 observation envelope echoes a fresh challenge, operation and complete
generation, and explicitly asserts positive enrollment. Strings and stored
records alone do not enroll anything. This client never creates enrollment,
rebinds a generation, or authorizes signals. Transport authentication belongs
to AuthenticatedChannel; a nonce echo alone is not peer authentication.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from dataclasses import asdict
from threading import RLock
from uuid import uuid4

from binnacle.platform.contracts.capability_contracts import (
    Capability,
    CapabilityState,
    GenerationMismatch,
    NativeCapabilityError,
)
from binnacle.platform.contracts.darwin_contracts import (
    AuthorityObservation,
    OwnerGeneration,
)
from binnacle.platform.contracts.native_service_contracts import AuthenticatedChannel
from binnacle.platform.darwin.process_authority import (
    _process_token,
    _unknown_observation,
)

_PROTOCOL = "binnacle-darwin-witness-v1"


class DarwinWitness:
    def __init__(
        self, channel: AuthenticatedChannel, generation: OwnerGeneration
    ) -> None:
        self._channel = channel
        self._generation = generation
        self._owner_pid = os.getpid()
        self._owner_token = _process_token()
        self._lock = RLock()
        self._closed = False
        if not all(
            (generation.manager_epoch, generation.witness_epoch, generation.job_id)
        ):
            raise self._mismatch()

    @staticmethod
    def _mismatch() -> GenerationMismatch:
        return GenerationMismatch(
            "darwin_generation_mismatch",
            Capability(
                CapabilityState.UNKNOWN, "darwin_generation_mismatch", "history only"
            ),
        )

    def _observe(self, operation: str) -> AuthorityObservation:
        if os.getpid() != self._owner_pid or self._owner_token is not _process_token():
            return _unknown_observation("darwin_witness_owner_lost")
        with self._lock:
            if self._closed:
                return _unknown_observation("darwin_witness_closed")
            challenge = uuid4().hex
            expected = {
                "protocol": _PROTOCOL,
                "operation": operation,
                "challenge": challenge,
                "generation": asdict(self._generation),
            }
            deadline = time.monotonic() + 1.0
            try:
                reply = self._channel.request(expected, timeout_s=1.0)
            except (OSError, NativeCapabilityError, ValueError):
                return _unknown_observation("darwin_witness_disconnected")
            if time.monotonic() >= deadline:
                return _unknown_observation("darwin_witness_expired")
            if not isinstance(reply, Mapping) or any(
                reply.get(key) != value for key, value in expected.items()
            ):
                return _unknown_observation("darwin_witness_generation_unverified")
            if reply.get("enrolled") is not True:
                return _unknown_observation("darwin_witness_not_enrolled")
            return AuthorityObservation(
                Capability(
                    CapabilityState.LIMITED,
                    "darwin_witness_observed",
                    "live enrollment observation only",
                ),
                self._generation,
                membership_closed=False,
                can_signal=False,
            )

    def observe(self, job_id: str) -> AuthorityObservation:
        if job_id != self._generation.job_id:
            raise self._mismatch()
        return self._observe("observe")

    def reconnect(self, generation: OwnerGeneration) -> AuthorityObservation:
        # Reconciliation of the same enrollment only, never manager adoption.
        if generation != self._generation:
            raise self._mismatch()
        return self._observe("reconnect")

    def close(self) -> None:
        if os.getpid() != self._owner_pid or self._owner_token is not _process_token():
            return
        with self._lock:
            if not self._closed:
                self._closed = True
                self._channel.close()
