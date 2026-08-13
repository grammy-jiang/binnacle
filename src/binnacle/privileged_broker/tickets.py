"""Fail-closed receiver-side validation of privileged authority tickets."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from binnacle.domain.privileged import PrivilegedAction, PrivilegedTicket

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class PrivilegedTicketRejected(RuntimeError):
    """A ticket is stale, unpromoted, or differs from protected broker policy."""


@dataclass(frozen=True, slots=True)
class PrivilegedTicketValidationProfile:
    broker_profile_id: str
    broker_profile_version: str
    broker_profile_sha256: str
    action_contract_versions: Mapping[PrivilegedAction, tuple[str, str]]
    target_profiles: Mapping[PrivilegedAction, tuple[str, str]]
    application_build_sha256: str
    application_config_sha256: str
    application_policy_sha256: str
    integrity_algorithm: str
    maximum_ticket_lifetime_seconds: int = 300

    def __post_init__(self) -> None:
        if not self.action_contract_versions or set(self.action_contract_versions) != set(
            self.target_profiles
        ):
            raise PrivilegedTicketRejected("privileged action profile is incomplete")
        if any(
            not action.consequential or action is PrivilegedAction.HOST_REBOOT
            for action in self.action_contract_versions
        ):
            raise PrivilegedTicketRejected(
                "privileged action profile includes unpromoted authority"
            )
        if self.integrity_algorithm not in {"ed25519", "hmac-sha256"}:
            raise PrivilegedTicketRejected("privileged integrity algorithm is unsupported")
        if not 1 <= self.maximum_ticket_lifetime_seconds <= 300:
            raise PrivilegedTicketRejected("privileged ticket lifetime ceiling is invalid")
        digests = (
            self.broker_profile_sha256,
            self.application_build_sha256,
            self.application_config_sha256,
            self.application_policy_sha256,
        )
        if any(_SHA256.fullmatch(value) is None for value in digests):
            raise PrivilegedTicketRejected("privileged validation profile digest is invalid")
        if not self.broker_profile_id or not self.broker_profile_version:
            raise PrivilegedTicketRejected("privileged broker profile identity is invalid")
        for action, (contract, version) in self.action_contract_versions.items():
            target_id, target_sha256 = self.target_profiles[action]
            if (
                not contract
                or not version
                or not target_id
                or _SHA256.fullmatch(target_sha256) is None
            ):
                raise PrivilegedTicketRejected("privileged action binding is invalid")


class PrivilegedTicketValidator:
    """Validate exact ticket fields and its detached integrity proof."""

    def __init__(
        self,
        profile: PrivilegedTicketValidationProfile,
        *,
        verify_integrity: Callable[[str, str, str], bool],
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._profile = profile
        self._verify_integrity = verify_integrity
        self._wall_clock = wall_clock or (lambda: datetime.now(UTC))

    def validate(self, ticket: PrivilegedTicket) -> None:
        now = self._wall_clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise PrivilegedTicketRejected("broker wall clock is not timezone-aware")
        if not ticket.issued_at <= now < ticket.expires_at:
            raise PrivilegedTicketRejected("privileged ticket is not current")
        if (
            ticket.expires_at - ticket.issued_at
        ).total_seconds() > self._profile.maximum_ticket_lifetime_seconds:
            raise PrivilegedTicketRejected("privileged ticket lifetime exceeds the profile")
        expected_contract = self._profile.action_contract_versions.get(ticket.action)
        expected_target = self._profile.target_profiles.get(ticket.action)
        if expected_contract is None or expected_target is None:
            raise PrivilegedTicketRejected("privileged ticket action is not promoted")
        exact = (
            (ticket.broker_profile_id, self._profile.broker_profile_id),
            (ticket.broker_profile_version, self._profile.broker_profile_version),
            (ticket.broker_profile_sha256, self._profile.broker_profile_sha256),
            (
                (ticket.operation_contract, ticket.operation_contract_version),
                expected_contract,
            ),
            ((ticket.target_profile_id, ticket.target_profile_sha256), expected_target),
            (ticket.application_build_sha256, self._profile.application_build_sha256),
            (ticket.application_config_sha256, self._profile.application_config_sha256),
            (ticket.application_policy_sha256, self._profile.application_policy_sha256),
            (ticket.integrity_algorithm, self._profile.integrity_algorithm),
        )
        if any(observed != expected for observed, expected in exact):
            raise PrivilegedTicketRejected("privileged ticket authority differs from profile")
        if not self._verify_integrity(
            ticket.unsigned_payload_sha256,
            ticket.integrity_algorithm,
            ticket.integrity_proof,
        ):
            raise PrivilegedTicketRejected("privileged ticket integrity proof is invalid")


__all__ = [
    "PrivilegedTicketRejected",
    "PrivilegedTicketValidationProfile",
    "PrivilegedTicketValidator",
]
