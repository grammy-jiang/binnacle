"""E2 S2: allocation protocol, owner-scoped selectors and serving rule (§2.3-2.5)."""

import asyncio
import hashlib
import re
import sqlite3
from dataclasses import replace

import pytest

from binnacle.features.commands.job_awareness import session_serving as serving
from binnacle.features.commands.job_awareness.models import (
    AuthorityDecision,
    Scope,
)
from binnacle.features.commands.job_awareness.session_binding import LabFailure
from binnacle.features.commands.job_awareness.session_lab import (
    CONSENT_VERSION,
    LabConfig,
    LabError,
    SessionLab,
)
from binnacle.features.commands.job_awareness.session_route import (
    SESSION_META,
    SUBJECT_META,
    RouteOutcome,
    RouteStatus,
    SessionKeyer,
    route,
)
from binnacle.features.commands.job_awareness.session_snapshot import FrozenTemplate
from tests.unit.core.job_awareness.session_support import (
    TEMPLATES,
    Lab,
    ManualClock,
    make_lab,
    pair,
    scan_phase,
    template,
)

VALUES_1 = ["synthetic-r3-01-00", "synthetic-r3-01-01", "synthetic-r3-01-02"]


def grant_record(lab, capability):
    digest = hashlib.sha256(capability).hexdigest()
    return lab.lab.authority.store.read_transaction(
        lambda tx: tx.grant_for_capability(digest)
    ).value


def handle_of(value: object) -> str:
    assert isinstance(value, str) and re.fullmatch("j_[0-9a-f]{12}", value), value
    return value


def test_allocation_is_live_granted_and_bound(tmp_path):
    lab = make_lab(tmp_path / "phase")
    outcome = lab.outcome("A")
    assert outcome.status is RouteStatus.UNBOUND
    handle = handle_of(lab.start("A", "R3-SYN-JOB-01"))
    assert lab.lab.bind(outcome).status is RouteStatus.BOUND
    assert lab.lab.bind(lab.outcome("B")).status is RouteStatus.UNBOUND
    rows = lab.rows("SELECT jobref,kd,slot,state,grant_id FROM alloc")
    assert len(rows) == 1 and rows[0][3] == "LIVE"
    assert rows[0][1] == lab.key("A").kd and rows[0][2] == "R3-SYN-JOB-01"
    assert lab.rows("SELECT state FROM emit") == [("PENDING",)]
    binding = lab.lab.table.get(lab.key("A").kd)
    assert binding is not None and binding.grant is not None
    (entry,) = binding.jobs.values()
    assert entry.handle == handle
    assert (
        lab.lab.authority.check(
            binding.grant, entry.job, frozenset({Scope.OBSERVE, Scope.READ})
        )
        is AuthorityDecision.AUTHORIZED
    )
    record = grant_record(lab, binding.capability)
    assert record.claims.consent_version == CONSENT_VERSION
    assert record.claims.expires_at_ms - record.claims.issued_at_ms == 1800000
    assert record.claims.grant_id == rows[0][4]
    assert lab.faults[-1] == "alloc:5:live"
    assert scan_phase(lab.phase, lab.events) == []


def test_explicit_tc_ttl(tmp_path):
    lab = make_lab(tmp_path / "phase", config=LabConfig(ttl_ms=3600000))
    lab.start("A", "R3-SYN-JOB-01")
    binding = lab.lab.table.get(lab.key("A").kd)
    record = grant_record(lab, binding.capability)
    assert record.claims.expires_at_ms - record.claims.issued_at_ms == 3600000
    for bad in (0, 3600001):
        with pytest.raises(ValueError):
            LabConfig(ttl_ms=bad)
    with pytest.raises(ValueError):
        LabConfig(max_live_per_key=9)


def test_stable_namespace_two_starts_and_repeated_slot(tmp_path):
    lab = make_lab(tmp_path / "phase")
    first = handle_of(lab.start("A", "R3-SYN-JOB-01"))
    second = handle_of(lab.start("A", "R3-SYN-JOB-02"))
    third = handle_of(lab.start("A", "R3-SYN-JOB-01"))
    other = handle_of(lab.start("B", "R3-SYN-JOB-01"))
    namespaces = {
        row[0].split(":")[0]
        for row in lab.rows("SELECT jobref FROM alloc WHERE kd=?", (lab.key("A").kd,))
    }
    assert len(namespaces) == 1
    assert (
        lab.rows("SELECT ns FROM keys WHERE kd=?", (lab.key("A").kd,))[0][0]
        in namespaces
    )
    other_ns = lab.rows("SELECT ns FROM keys WHERE kd=?", (lab.key("B").kd,))[0][0]
    assert other_ns not in namespaces
    outcome = lab.outcome("A")
    # The replacement grant covers every live allocation of the key.
    for handle in (first, second, third):
        assert isinstance(serving.read_page(lab.lab, outcome, handle, 1), dict)
    assert (
        serving.read_page(lab.lab, outcome, "R3-SYN-JOB-01", 0)
        is LabError.AMBIGUOUS_SLOT
    )
    page = serving.read_page(lab.lab, outcome, "R3-SYN-JOB-02", 0)
    assert isinstance(page, dict) and page["slot"] == "R3-SYN-JOB-02"
    # B's own allocation of the same slot has its own canaries.
    mine = serving.read_page(lab.lab, lab.outcome("B"), "R3-SYN-JOB-01", 0)
    theirs = serving.read_page(lab.lab, outcome, first, 0)
    assert isinstance(mine, dict) and isinstance(theirs, dict)
    assert (
        mine["canary"] != theirs["canary"] and mine["alloc_tag"] != theirs["alloc_tag"]
    )
    assert mine["value"] == theirs["value"]  # public template bytes
    assert serving.read_page(lab.lab, lab.outcome("B"), first, 0) is LabError.DENIED
    assert other != first


def test_key_full_and_quotas(tmp_path):
    lab = make_lab(
        tmp_path / "phase", config=LabConfig(max_per_key=10, max_per_phase=12)
    )
    for index in range(8):
        handle_of(lab.start("A", f"R3-SYN-JOB-{index + 1:02d}"))
    assert lab.start("A", "R3-SYN-JOB-09") is LabError.KEY_FULL
    first = next(iter(lab.lab.table.get(lab.key("A").kd).jobs.values()))
    assert asyncio.run(serving.retire(lab.lab, lab.key("A"), first.handle))
    handle_of(lab.start("A", "R3-SYN-JOB-09"))
    assert asyncio.run(serving.close(lab.lab, lab.key("A"))) == 8
    handle_of(lab.start("A", "R3-SYN-JOB-10"))
    assert lab.start("A", "R3-SYN-JOB-11") is LabError.QUOTA_EXCEEDED  # 10 per key
    handle_of(lab.start("B", "R3-SYN-JOB-01"))
    handle_of(lab.start("C", "R3-SYN-JOB-01"))
    assert lab.start("D", "R3-SYN-JOB-01") is LabError.QUOTA_EXCEEDED  # 12 per phase
    assert [e["error"] for e in lab.events if e["event"] == "ja_refused"] == [
        "KEY_FULL",
        "QUOTA_EXCEEDED",
        "QUOTA_EXCEEDED",
    ]


def test_uniform_denial_for_foreign_missing_malformed_retired(tmp_path):
    lab = make_lab(tmp_path / "phase")
    mine = handle_of(lab.start("A", "R3-SYN-JOB-01"))
    gone = handle_of(lab.start("A", "R3-SYN-JOB-02"))
    foreign = handle_of(lab.start("B", "R3-SYN-JOB-03"))
    assert asyncio.run(serving.retire(lab.lab, lab.key("A"), gone))
    outcome = lab.outcome("A")
    selectors = [
        foreign,
        "j_000000000000",
        "j_" + "f" * 12,
        gone,
        "R3-SYN-JOB-03",
        "R3-SYN-JOB-02",
        "R3-SYN-JOB-13",
        mine.upper(),
        mine + "\n",
        "",
        None,
        7,
        ["j_000000000000"],
    ]
    for selector in selectors:
        assert serving.read_page(lab.lab, outcome, selector, 0) is LabError.DENIED
        assert serving.echo(lab.lab, outcome, selector, VALUES_1) is LabError.DENIED
    for broken in (
        RouteOutcome(RouteStatus.NO_SESSION),
        RouteOutcome(RouteStatus.MISMATCH),
        RouteOutcome(RouteStatus.MALFORMED, format_change=True),
        "not an outcome",
    ):
        assert serving.read_page(lab.lab, broken, mine, 0) is LabError.DENIED
        assert (
            asyncio.run(lab.lab.start_fixture(broken, "R3-SYN-JOB-01"))
            is LabError.DENIED
        )
    for page in (3, -1, "0", True):
        assert serving.read_page(lab.lab, outcome, mine, page) is LabError.DENIED
    assert serving.echo(lab.lab, outcome, mine, VALUES_1) == {"ok": True}
    assert serving.echo(lab.lab, outcome, mine, ["x", "y", "z"]) == {"ok": False}
    assert serving.echo(lab.lab, outcome, "R3-SYN-JOB-01", VALUES_1) == {"ok": True}


def test_owner_scope_gate_reads_nothing_global(tmp_path, monkeypatch):
    lab = make_lab(tmp_path / "phase")
    handle_of(lab.start("A", "R3-SYN-JOB-01"))
    foreign = handle_of(lab.start("B", "R3-SYN-JOB-02"))
    reads = {"ledger": 0, "catalog": 0, "check": 0, "lease": 0}
    ledger, catalog = lab.lab.ledger, lab.lab.snapshots.catalog
    authority, snapshots = lab.lab.authority, lab.lab.snapshots
    for name, owner, attr in (
        ("ledger", ledger, "read"),
        ("catalog", catalog, "lookup"),
        ("check", authority, "check"),
        ("lease", snapshots, "open_verified"),
    ):
        original = getattr(owner, attr)

        def counted(*args, _name=name, _original=original, **kwargs):
            reads[_name] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(owner, attr, counted)
    outcome = lab.outcome("A")
    foreign_result = serving.read_page(lab.lab, outcome, foreign, 0)
    missing_result = serving.read_page(lab.lab, outcome, "j_" + "0" * 12, 0)
    slot_result = serving.read_page(lab.lab, outcome, "R3-SYN-JOB-02", 0)
    assert foreign_result is missing_result is slot_result is LabError.DENIED
    assert reads == {"ledger": 0, "catalog": 0, "check": 0, "lease": 0}
    assert isinstance(serving.read_page(lab.lab, outcome, "R3-SYN-JOB-01", 0), dict)
    assert reads["ledger"] == 1 and reads["lease"] == 1


def test_three_way_serving_rule(tmp_path):
    lab = make_lab(tmp_path / "phase")
    handle = handle_of(lab.start("A", "R3-SYN-JOB-01"))
    outcome, kd = lab.outcome("A"), lab.key("A").kd
    binding = lab.lab.table.get(kd)
    (entry,) = binding.jobs.values()
    # Lab disagreement: the row is no longer LIVE.
    db_job = entry.job.canonical_key
    db = sqlite3.connect(lab.lab.ledger.path)
    db.execute("UPDATE alloc SET state='DENY_FOREVER' WHERE jobref=?", (db_job,))
    db.commit()
    assert serving.read_page(lab.lab, outcome, handle, 0) is LabError.DENIED
    db.execute("UPDATE alloc SET state='LIVE' WHERE jobref=?", (db_job,))
    db.commit()
    db.close()
    assert isinstance(serving.read_page(lab.lab, outcome, handle, 0), dict)
    # Grant disagreement: revoked outside the lab.
    grant = binding.grant
    assert lab.lab.authority.revoke(grant).value is None
    assert serving.read_page(lab.lab, outcome, handle, 0) is LabError.DENIED
    # Memory disagreement: entry replaced.
    lab2 = make_lab(tmp_path / "phase2")
    handle2 = handle_of(lab2.start("A", "R3-SYN-JOB-01"))
    binding2 = lab2.lab.table.get(lab2.key("A").kd)
    (job2,) = binding2.jobs
    binding2.jobs[job2] = replace(binding2.jobs[job2])
    entry2 = binding2.jobs[job2]
    assert (
        serving.serving_grant(
            lab2.lab, lab2.key("A"), binding2, entry2, frozenset({Scope.READ})
        )
        is not None
    )
    stale = replace(entry2)
    assert (
        serving.serving_grant(
            lab2.lab, lab2.key("A"), binding2, stale, frozenset({Scope.READ})
        )
        is None
    )
    assert isinstance(serving.read_page(lab2.lab, lab2.outcome("A"), handle2, 0), dict)


def test_retire_keeps_other_allocations_served_and_suspend_denies(tmp_path):
    lab = make_lab(tmp_path / "phase")
    first = handle_of(lab.start("A", "R3-SYN-JOB-01"))
    second = handle_of(lab.start("A", "R3-SYN-JOB-02"))
    key, outcome = lab.key("A"), lab.outcome("A")
    assert asyncio.run(serving.retire(lab.lab, key, first))
    assert not asyncio.run(serving.retire(lab.lab, key, first))
    assert serving.read_page(lab.lab, outcome, first, 0) is LabError.DENIED
    assert isinstance(serving.read_page(lab.lab, outcome, second, 0), dict)
    states = dict(lab.rows("SELECT slot,state FROM alloc"))
    assert states == {"R3-SYN-JOB-01": "RETIRED", "R3-SYN-JOB-02": "LIVE"}
    grant_ids = {
        row[0] for row in lab.rows("SELECT grant_id FROM alloc WHERE state='LIVE'")
    }
    binding = lab.lab.table.get(key.kd)
    assert len(grant_ids) == 1
    assert asyncio.run(serving.suspend(lab.lab, key))
    assert lab.lab.bind(outcome).status is RouteStatus.SUSPENDED
    assert serving.read_page(lab.lab, outcome, second, 0) is LabError.DENIED
    assert lab.start("A", "R3-SYN-JOB-03") is LabError.DENIED
    assert lab.rows("SELECT state FROM keys WHERE kd=?", (key.kd,)) == [("SUSPENDED",)]
    assert binding.suspended
    assert asyncio.run(serving.close(lab.lab, lab.key("Z"))) == 0
    assert not asyncio.run(serving.retire(lab.lab, lab.key("Z"), first))


def test_close_retires_everything_with_one_revoke(tmp_path):
    lab = make_lab(tmp_path / "phase")
    for index in range(3):
        handle_of(lab.start("A", f"R3-SYN-JOB-{index + 1:02d}"))
    grants_before = lab.lab.authority.store.read_transaction(
        lambda tx: tx._db.execute("SELECT count(*) FROM grants").fetchone()[0]
    ).value
    assert asyncio.run(serving.close(lab.lab, lab.key("A"))) == 3
    grants_after = lab.lab.authority.store.read_transaction(
        lambda tx: tx._db.execute("SELECT count(*),sum(revoked) FROM grants").fetchone()
    ).value
    assert grants_after == (grants_before, grants_before)
    assert {row[0] for row in lab.rows("SELECT state FROM alloc")} == {"RETIRED"}
    binding = lab.lab.table.get(lab.key("A").kd)
    assert binding.grant is None and binding.jobs == {}
    handle_of(lab.start("A", "R3-SYN-JOB-04"))  # a closed key can allocate again


def test_bad_template_unknown_slot_and_old_epoch(tmp_path):
    templates = dict(TEMPLATES)
    templates["R3-SYN-JOB-01"] = replace(template(1), nonce_sha256="0" * 64)
    clock = ManualClock()
    session_lab = SessionLab(tmp_path / "phase", templates, clock.trusted())
    assert session_lab.start()
    lab = Lab(session_lab, clock, tmp_path / "phase", [], [])
    assert lab.start("A", "R3-SYN-JOB-01") is LabError.DENIED
    assert lab.rows("SELECT count(*) FROM alloc") == [(0,)]
    assert lab.start("A", "R3-SYN-JOB-13") is LabError.DENIED
    other = SessionKeyer("e" * 32)
    session, subject = pair("A")
    stale = route(
        other, [session], [subject], {SESSION_META: session, SUBJECT_META: subject}
    )
    assert session_lab.keyed(stale) is None
    assert (
        asyncio.run(session_lab.start_fixture(stale, "R3-SYN-JOB-02"))
        is LabError.DENIED
    )
    with pytest.raises(ValueError):
        SessionLab(tmp_path / "x", {"R3-SYN-JOB-02": template(1)}, clock.trusted())
    assert not session_lab.start()  # cold start happens once per controller
    unstarted = SessionLab(tmp_path / "y", TEMPLATES, clock.trusted())
    assert unstarted.keyed(lab.outcome("A")) is None
    for name in ("ledger", "snapshots", "keyer", "authority"):
        with pytest.raises(LabFailure):
            getattr(unstarted, name)
    assert isinstance(templates["R3-SYN-JOB-02"], FrozenTemplate)


def test_fence_timeout_denies_allocation(tmp_path):
    lab = make_lab(tmp_path / "phase", config=LabConfig(fence_timeout_s=0.05))

    async def scenario():
        lock = lab.lab.fences.lock(lab.key("A").kd)
        await lock.acquire()
        try:
            return await lab.lab.start_fixture(lab.outcome("A"), "R3-SYN-JOB-01")
        finally:
            lock.release()

    assert asyncio.run(scenario()) is LabError.DENIED
    assert lab.rows("SELECT count(*) FROM alloc") == [(0,)]


def test_restart_rotates_epoch_and_denies_old_rows(tmp_path):
    first = make_lab(tmp_path / "phase")
    old = handle_of(first.start("A", "R3-SYN-JOB-01"))
    old_kd = first.key("A").kd
    second = make_lab(tmp_path / "phase", clock=first.clock)
    assert second.key("A").kd != old_kd
    assert second.rows("SELECT state FROM alloc") == [("DENY_FOREVER",)]
    assert serving.read_page(second.lab, second.outcome("A"), old, 0) is LabError.DENIED
    new = handle_of(second.start("A", "R3-SYN-JOB-01"))
    assert (
        serving.read_page(second.lab, second.outcome("A"), "R3-SYN-JOB-01", 0)["slot"]
        == "R3-SYN-JOB-01"
    )
    assert new != old
    assert scan_phase(second.phase, first.events + second.events) == []


def test_suspend_retire_and_replacement_failures_fail_closed(tmp_path):
    armed = {"point": None}

    def fault(seen):
        if seen == armed["point"]:
            raise LabFailure()

    lab = make_lab(tmp_path / "phase", fault=fault)
    first = handle_of(lab.start("A", "R3-SYN-JOB-01"))
    second = handle_of(lab.start("A", "R3-SYN-JOB-02"))
    armed["point"] = "lab:regrant"
    assert asyncio.run(serving.retire(lab.lab, lab.key("A"), first))
    assert lab.lab.table.get(lab.key("A").kd).suspended
    assert serving.read_page(lab.lab, lab.outcome("A"), second, 0) is LabError.DENIED
    handle_of(lab.start("B", "R3-SYN-JOB-01"))
    armed["point"] = "lab:retire"
    b_handle = next(iter(lab.lab.table.get(lab.key("B").kd).jobs.values())).handle
    assert not asyncio.run(serving.retire(lab.lab, lab.key("B"), b_handle))
    assert lab.lab.table.get(lab.key("B").kd).suspended
    armed["point"] = "lab:suspend"
    handle_of(lab.start("C", "R3-SYN-JOB-01"))
    assert asyncio.run(serving.suspend(lab.lab, lab.key("C")))
    assert any(e["event"] == "ja_suspend_unwritten" for e in lab.events)
    armed["point"] = None
    assert asyncio.run(serving.suspend(lab.lab, lab.key("nobody")))
    assert lab.rows(
        "SELECT count(*) FROM keys WHERE kd=?", (lab.key("nobody").kd,)
    ) == [(0,)]


def test_lease_and_revoke_failures(tmp_path, monkeypatch):
    from binnacle.features.commands.job_awareness.models import (
        BoundaryError,
        ErrorCode,
        Failure,
    )

    lab = make_lab(tmp_path / "phase")
    handle = handle_of(lab.start("A", "R3-SYN-JOB-01"))
    denied = Failure(BoundaryError(ErrorCode.QUOTA_EXCEEDED))
    with monkeypatch.context() as patch:
        patch.setattr(
            lab.lab.snapshots, "open_verified", lambda grant, snapshot: denied
        )
        assert (
            serving.read_page(lab.lab, lab.outcome("A"), handle, 0) is LabError.DENIED
        )
        assert lab.start("A", "R3-SYN-JOB-02") is LabError.DENIED  # step 4 lease
    assert lab.lab.table.get(lab.key("A").kd).suspended
    lab2 = make_lab(tmp_path / "phase2")
    handle_of(lab2.start("A", "R3-SYN-JOB-01"))
    monkeypatch.setattr(
        lab2.lab.authority,
        "revoke",
        lambda grant: Failure(BoundaryError(ErrorCode.BUSY)),
    )
    assert lab2.start("A", "R3-SYN-JOB-02") is LabError.DENIED
    assert lab2.lab.table.get(lab2.key("A").kd).suspended


def test_lease_digest_mismatch_denies(tmp_path, monkeypatch):
    from binnacle.features.commands.job_awareness.models import Success

    lab = make_lab(tmp_path / "phase")

    class Lease:
        verified_bytes = b"not the sealed bytes"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(
        lab.lab.snapshots, "open_verified", lambda grant, snapshot: Success(Lease())
    )
    assert lab.start("A", "R3-SYN-JOB-01") is LabError.DENIED
    assert lab.rows("SELECT state FROM alloc") == [("DENY_FOREVER",)]


def test_start_refuses_corrupt_receipt_store(tmp_path):
    phase = tmp_path / "phase"
    (phase / "receipt").mkdir(parents=True, mode=0o700)
    phase.chmod(0o700)
    (phase / "receipt" / "receipt.sqlite").write_bytes(b"not a database" * 100)
    lab = make_lab(phase, start=False)
    assert lab.lab.start() is False and not lab.lab.ready


def test_grant_remaining_ms_for_logs(tmp_path):
    lab = make_lab(tmp_path / "phase", config=LabConfig(ttl_ms=3600000))
    assert lab.lab.grant_remaining_ms(lab.key("A")) is None
    handle_of(lab.start("A", "R3-SYN-JOB-01"))
    assert lab.lab.grant_remaining_ms(lab.key("A")) == 3600000
    lab.clock.advance(60000)
    assert lab.lab.grant_remaining_ms(lab.key("A")) == 3540000
    lab.clock.advance(3600000)
    assert lab.lab.grant_remaining_ms(lab.key("A")) == 0
    lab.clock.wall_ms -= 10**7  # clock regression latches the trusted clock
    lab.clock.mono_ns -= 10**13
    assert lab.lab.grant_remaining_ms(lab.key("A")) is None
