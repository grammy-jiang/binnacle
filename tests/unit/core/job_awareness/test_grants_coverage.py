"""Denial, bound and tamper behavior of the synthetic grant authority.

Synthetic credentials only. Tests that reach into private authority state do so
to model a defect or a tampered ledger that the public API cannot produce; each
asserts that the authority fails closed.
"""

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from binnacle.features.commands.job_awareness import grants
from binnacle.features.commands.job_awareness.models import (
    AuthorityDecision,
    BoundaryError,
    ErrorCode,
    Failure,
    JobRef,
    PrincipalClaims,
    Scope,
    Success,
    VerifiedRunGrant,
)
from binnacle.features.commands.job_awareness.receipt_schema import (
    Limits,
    StoreFailure,
)

ISSUER = "1" * 32


class ForeignGrant(VerifiedRunGrant):
    @property
    def authority_handle(self) -> object:
        return self


class StubReader:
    """Minimal AuthorityReader stand-in for direct state-machine checks."""

    def __init__(self, now_ms, epoch):
        self.now_ms, self._epoch = now_ms, epoch

    def current_epoch(self, issuer_id):
        return self._epoch


class AuthorityFixture:
    limits: Limits | None = None

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ja-q1-grants-")
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "ledger.sqlite"
        self.wall, self.mono = 1000, 0
        self.clock = grants.TrustedClock(lambda: self.wall, lambda: self.mono)
        self.principal = PrincipalClaims(ISSUER, "2" * 32, "3" * 32, "4" * 32)
        self.job = JobRef("ja1_" + "5" * 32, "6" * 12, "g1_" + "7" * 32)
        self.authority = grants.SyntheticAuthority(
            self.path, ISSUER, self.clock, limits=self.limits
        )

    def ok(self, result):
        self.assertIsInstance(result, Success, result)
        return result.value

    def assert_denied(self, result):
        self.assertEqual(result, Failure(BoundaryError(ErrorCode.DENIED)))

    def started_grant(self, ttl_ms=900000):
        """Return (credential, capability, handle) for a verified READ grant."""
        self.ok(self.authority.start())
        credential = self.ok(self.authority.register_principal(self.principal))
        person = self.ok(self.authority.verify_principal(credential))
        capability = self.ok(
            self.authority.issue_grant(
                person, (self.job,), frozenset(Scope), ttl_ms=ttl_ms
            )
        )
        handle = self.ok(self.authority.verify(credential, capability, Scope.READ))
        return credential, capability, handle


class ClockLatchTests(AuthorityFixture, unittest.TestCase):
    def test_latched_clock_stays_unsafe_after_source_recovers(self):
        """A failed source disables the clock even when the source heals."""
        failing = patch.object(self.clock, "_wall", side_effect=OSError("down"))
        with (
            failing,
            self.assertRaises(StoreFailure) as first,
        ):
            self.clock.now()
        self.assertIs(first.exception.code, ErrorCode.CLOCK_UNSAFE)
        # The wall source is healthy again, but the latch is permanent.
        with self.assertRaises(StoreFailure) as second:
            self.clock.now()
        self.assertIs(second.exception.code, ErrorCode.CLOCK_UNSAFE)

    def test_wall_regress_latches_without_a_monotonic_regress(self):
        self.assertEqual(self.clock.now(), 1000)
        self.wall = 999
        with self.assertRaises(StoreFailure):
            self.clock.now()
        self.wall = 5000
        with self.assertRaises(StoreFailure):
            self.clock.now()


class HandleIdentityTests(AuthorityFixture, unittest.TestCase):
    def test_handles_are_their_own_authority_identity(self):
        _, _, grant_handle = self.started_grant()
        principal = self.ok(
            self.authority.verify_principal(
                self.ok(
                    self.authority.register_principal(
                        replace(self.principal, subject_id="9" * 32)
                    )
                )
            )
        )
        for handle in (grant_handle, principal):
            self.assertIs(handle.authority_handle, handle)
        self.assertIsNot(principal.authority_handle, grant_handle.authority_handle)


class StartTests(AuthorityFixture, unittest.TestCase):
    def test_start_is_one_shot(self):
        self.ok(self.authority.start())
        self.assert_denied(self.authority.start())

    def test_failed_start_leaves_authority_closed_and_not_retryable(self):
        self.path.write_bytes(b"this is not a sqlite ledger" * 64)
        result = self.authority.start()
        self.assertIsInstance(result, Failure)
        # The cold start is consumed and no epoch was committed.
        self.assert_denied(self.authority.start())
        self.assert_denied(self.authority.register_principal(self.principal))
        self.assert_denied(self.authority.verify_principal(b"c" * 32))
        self.assert_denied(self.authority.verify(b"c" * 32, b"d" * 32, Scope.READ))

    def test_epoch_commit_failure_publishes_no_readiness(self):
        with patch.object(grants.secrets, "token_hex", return_value="not-hex"):
            self.assertIsInstance(self.authority.start(), Failure)
        self.assertIsNone(self.authority._epoch)
        self.assert_denied(self.authority.register_principal(self.principal))
        self.assert_denied(self.authority.verify(b"c" * 32, b"d" * 32, Scope.READ))


class PrincipalRegistryTests(AuthorityFixture, unittest.TestCase):
    limits = Limits(grants=2)

    def test_duplicate_claims_are_denied_not_reenrolled(self):
        self.ok(self.authority.start())
        self.ok(self.authority.register_principal(self.principal))
        self.assert_denied(self.authority.register_principal(self.principal))

    def test_principal_population_is_bounded_by_the_grant_ceiling(self):
        self.ok(self.authority.start())
        for subject in ("a", "b"):
            self.ok(
                self.authority.register_principal(
                    replace(self.principal, subject_id=subject * 32)
                )
            )
        self.assertEqual(
            self.authority.register_principal(
                replace(self.principal, subject_id="c" * 32)
            ),
            Failure(BoundaryError(ErrorCode.QUOTA_EXCEEDED)),
        )
        # The refused enrollment did not displace an existing principal.
        self.assertEqual(len(self.authority._principals), 2)

    def test_credential_digest_collision_is_denied(self):
        """A broken randomness source must not alias two principals."""
        self.ok(self.authority.start())
        with patch.object(grants.secrets, "token_bytes", return_value=b"k" * 32):
            self.ok(self.authority.register_principal(self.principal))
            self.assert_denied(
                self.authority.register_principal(
                    replace(self.principal, subject_id="9" * 32)
                )
            )
        self.assertEqual(len(self.authority._principals), 1)

    def test_verify_principal_rejects_unknown_malformed_and_unstarted(self):
        self.assert_denied(self.authority.verify_principal(b"u" * 32))
        credential = self.started_grant()[0]
        self.assert_denied(self.authority.verify_principal(b"u" * 32))
        for bad in (b"", credential[:-1], credential + b"x", "s" * 32, None, 7):
            self.assert_denied(self.authority.verify_principal(bad))
        self.ok(self.authority.verify_principal(credential))
        # A started registry without an epoch admits nothing.
        self.authority._epoch = None
        self.assert_denied(self.authority.verify_principal(credential))


class IssueGrantTests(AuthorityFixture, unittest.TestCase):
    def test_capability_equal_to_credential_is_denied(self):
        """Credential and capability must stay independent secrets."""
        self.ok(self.authority.start())
        credential = self.ok(self.authority.register_principal(self.principal))
        person = self.ok(self.authority.verify_principal(credential))
        real = grants.secrets.token_bytes

        def fixed(nbytes):
            # token_hex(16) also draws from token_bytes; only pin the capability.
            return credential if nbytes == 32 else real(nbytes)

        with patch.object(grants.secrets, "token_bytes", fixed):
            self.assert_denied(
                self.authority.issue_grant(person, (self.job,), frozenset(Scope))
            )
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM grants").fetchone()[0], 0)

    def test_job_sets_outside_bounds_are_denied(self):
        self.ok(self.authority.start())
        credential = self.ok(self.authority.register_principal(self.principal))
        person = self.ok(self.authority.verify_principal(credential))
        too_many = tuple(
            replace(self.job, job_id=f"{index:012x}") for index in range(101)
        )
        for jobs in ([self.job], (), too_many, (self.job, "job"), self.job):
            self.assert_denied(
                self.authority.issue_grant(person, jobs, frozenset(Scope))
            )
        edge = too_many[:100]
        self.ok(self.authority.issue_grant(person, edge, frozenset(Scope)))


class VerifyBoundTests(AuthorityFixture, unittest.TestCase):
    def test_handle_registry_is_bounded_and_fails_closed(self):
        credential, cap1, first = self.started_grant()
        person = self.ok(self.authority.verify_principal(credential))
        second = self.ok(
            self.authority.issue_grant(person, (self.job,), frozenset(Scope))
        )
        # Model a registry that is already at its ceiling.
        self.authority._capacity = 1
        self.assertEqual(
            self.authority.verify(credential, second, Scope.READ),
            Failure(BoundaryError(ErrorCode.QUOTA_EXCEEDED)),
        )
        self.assertEqual(len(self.authority._grants), 1)
        # An already-registered grant is still served from the registry.
        self.assertIs(
            self.ok(self.authority.verify(credential, cap1, Scope.READ)), first
        )


class RegisteredHandleTests(AuthorityFixture, unittest.TestCase):
    def check(self, handle):
        return self.authority.check(handle, self.job, frozenset({Scope.READ}))

    def test_replaced_principal_binding_revokes_handle_authority(self):
        _, _, handle = self.started_grant()
        self.assertIs(self.check(handle), AuthorityDecision.AUTHORIZED)
        digest = next(iter(self.authority._principals))
        binding = self.authority._principals[digest]
        # An equal-looking but different binding object is a different identity.
        self.authority._principals[digest] = replace(binding)
        self.assertIs(self.check(handle), AuthorityDecision.DENIED)
        self.assert_denied(self.authority.revoke(handle))

    def test_tampered_ledger_capability_digest_denies(self):
        _, _, handle = self.started_grant()
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE grants SET capability_sha256=?", ("e" * 64,))
        self.assertIs(self.check(handle), AuthorityDecision.DENIED)

    def test_tampered_ledger_credential_digest_denies(self):
        _, _, handle = self.started_grant()
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE grants SET credential_sha256=?", ("e" * 64,))
        self.assertIs(self.check(handle), AuthorityDecision.DENIED)

    def test_tampered_ledger_claims_deny(self):
        _, _, handle = self.started_grant()
        with sqlite3.connect(self.path) as db:
            claims = db.execute("SELECT claims FROM grants").fetchone()[0]
            db.execute("UPDATE grants SET claims=?", (claims.replace("5", "8"),))
        self.assertIs(self.check(handle), AuthorityDecision.DENIED)

    def test_missing_ledger_record_denies(self):
        _, _, handle = self.started_grant()
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("DELETE FROM grants")
        self.assertIs(self.check(handle), AuthorityDecision.DENIED)

    def test_authority_without_epoch_denies_registered_handle(self):
        _, _, handle = self.started_grant()
        self.authority._epoch = None
        self.assertIs(self.check(handle), AuthorityDecision.DENIED)

    def test_grant_not_yet_valid_is_denied_not_expired(self):
        """A reader whose time precedes issue time cannot authorize the grant."""
        _, _, handle = self.started_grant()
        record = self.authority._grants[id(handle)].record
        issued = record.claims.issued_at_ms
        with patch.object(self.clock, "now", return_value=issued - 1):
            early = self.authority._state(
                StubReader(issued - 1, record.claims.issuer_epoch), record
            )
            self.assertIs(early, AuthorityDecision.DENIED)
        with patch.object(self.clock, "now", return_value=issued):
            on_time = self.authority._state(
                StubReader(issued, record.claims.issuer_epoch), record
            )
            self.assertIs(on_time, AuthorityDecision.AUTHORIZED)
        # A superseded epoch is reported as revoked before any time check.
        with patch.object(self.clock, "now", return_value=issued):
            stale = self.authority._state(StubReader(issued, "f" * 32), record)
            self.assertIs(stale, AuthorityDecision.REVOKED)


class RevokeTests(AuthorityFixture, unittest.TestCase):
    def test_unregistered_handle_cannot_revoke(self):
        _, _, handle = self.started_grant()
        for foreign in (object(), ForeignGrant(), grants._GrantHandle()):
            self.assert_denied(self.authority.revoke(foreign))
        # The real grant is untouched by the refused attempts.
        self.assertIs(
            self.authority.check(handle, self.job, frozenset({Scope.READ})),
            AuthorityDecision.AUTHORIZED,
        )
        self.ok(self.authority.revoke(handle))
        self.assertIs(
            self.authority.check(handle, self.job, frozenset({Scope.READ})),
            AuthorityDecision.REVOKED,
        )
