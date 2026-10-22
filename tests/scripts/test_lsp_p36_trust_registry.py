"""Operator registry loading, key lifecycle and replay ledger (synthetic keys)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.lsp_p36_secure_io import PathPolicy
from scripts.lsp_p36_trust_registry import (
    REGISTRY_ENV,
    FileReplayLedger,
    MemoryReplayLedger,
    RegistryRefused,
    TrustRegistry,
    load_trust_registry,
    replay_key,
)
from tests.fixtures.lsp.trust_chain import (
    REGISTRY_ID,
    World,
    key_entry,
    process_owner_policy,
    registry_doc,
    write_private,
    write_registry,
)

POLICY = process_owner_policy()
UTC = timezone.utc


def _load(path, **kw):
    return load_trust_registry(
        path, policy=POLICY, expected_registry_id=REGISTRY_ID, **kw
    )


def test_unconfigured_registry_fails_closed(monkeypatch):
    monkeypatch.delenv(REGISTRY_ENV, raising=False)
    with pytest.raises(RegistryRefused, match="trust_registry_not_configured"):
        _load(None)


def test_valid_registry_loads_and_reports_process_ownership(tmp_path):
    world = World(tmp_path)
    registry = _load(world.publish_registry())
    assert registry.doc.serial == 3
    assert registry.owner_is_current_user  # Truthfully reported, not hidden.


def test_registry_cannot_be_constructed_from_arbitrary_data(tmp_path):
    world = World(tmp_path)
    registry = _load(world.publish_registry())
    with pytest.raises(RegistryRefused, match="not_loaded_from_operator_path"):
        TrustRegistry(object(), registry.doc, registry.sha256, 0)


@pytest.mark.parametrize("mode", [0o660, 0o606, 0o4600])
def test_improper_registry_mode_refused(tmp_path, mode):
    world = World(tmp_path)
    world.publish_registry().chmod(mode)
    with pytest.raises(RegistryRefused, match="registry_path_file_mode_unsafe"):
        _load(world.registry_path)


def test_improper_registry_owner_refused(tmp_path):
    world = World(tmp_path)
    world.publish_registry()
    root_only = PathPolicy(
        owner_uids=frozenset({os.geteuid() + 1}), allow_sticky_ancestors=True
    )
    with pytest.raises(RegistryRefused, match="registry_path_path_ancestor_owner"):
        load_trust_registry(
            world.registry_path, policy=root_only, expected_registry_id=REGISTRY_ID
        )


def test_registry_symlink_and_hardlink_refused(tmp_path):
    world = World(tmp_path)
    real = world.publish_registry()
    (tmp_path / "operator" / "link.json").symlink_to(real)
    with pytest.raises(RegistryRefused, match="symlink"):
        _load(tmp_path / "operator" / "link.json")
    (tmp_path / "alias").symlink_to(tmp_path / "operator")
    with pytest.raises(RegistryRefused, match="symlink"):
        _load(tmp_path / "alias" / "registry.json")
    os.link(real, tmp_path / "operator" / "second.json")
    with pytest.raises(RegistryRefused, match="hardlink"):
        _load(real)


def test_registry_inside_forbidden_evidence_root_refused(tmp_path):
    world = World(tmp_path)
    path = world.publish_registry()
    policy = PathPolicy(
        owner_uids=POLICY.owner_uids,
        allow_sticky_ancestors=True,
        forbidden_roots=(str(path.parent),),
    )
    with pytest.raises(RegistryRefused, match="untrusted_root"):
        load_trust_registry(path, policy=policy, expected_registry_id=REGISTRY_ID)


def test_duplicate_unknown_and_nonfinite_json_refused(tmp_path):
    world = World(tmp_path)
    doc = registry_doc(key_entry(world.reviewer, "independent-reviewer"))
    text = json.dumps(doc)
    cases = {
        "dup": '{"serial":1,' + text[1:],
        "unknown": json.dumps({**doc, "trusted_by_report": True}),
        "nan": text.replace('"serial": 3', '"serial": NaN'),
        "garbage": "not json",
    }
    for raw in cases.values():
        write_private(world.registry_path, raw.encode())
        with pytest.raises(RegistryRefused):
            _load(world.registry_path)


def test_registry_identity_and_rollback_pins(tmp_path):
    world = World(tmp_path)
    path = world.publish_registry()
    with pytest.raises(RegistryRefused, match="registry_id_mismatch"):
        load_trust_registry(path, policy=POLICY, expected_registry_id="other")
    with pytest.raises(RegistryRefused, match="registry_rollback_refused"):
        _load(path, min_serial=4)
    for bad in (0, -1, True):
        with pytest.raises(RegistryRefused, match="serial_policy_invalid"):
            _load(path, min_serial=bad)


def test_key_id_must_be_digest_of_embedded_public_key(tmp_path):
    world = World(tmp_path)
    entry = key_entry(world.reviewer, "independent-reviewer", key_id="0" * 64)
    with pytest.raises(RegistryRefused, match="key_id_mismatch"):
        _load(write_registry(world.registry_path, registry_doc(entry)))


def test_registry_structural_invariants(tmp_path):
    world = World(tmp_path)
    one = key_entry(world.reviewer, "independent-reviewer")
    other = Ed25519PrivateKey.generate()
    two = key_entry(other, "second-reviewer")
    bad_docs = {
        "duplicate_key": registry_doc(one, one),
        "reviewer_is_producer": registry_doc(key_entry(other, "synthetic-ci-producer")),
        "window": registry_doc({**one, "not_after_utc": "2025-01-01T00:00:00Z"}),
        "active_with_change": registry_doc(
            {**one, "state_changed_at_utc": "2026-10-02T00:00:00Z"}
        ),
        "retired_without_change": registry_doc({**one, "state": "retired"}),
        "unknown_predecessor": registry_doc(one, {**two, "supersedes": "1" * 64}),
        "active_predecessor": registry_doc(one, {**two, "supersedes": one["key_id"]}),
        "self_supersede": registry_doc({**one, "supersedes": one["key_id"]}),
    }
    for name, doc in bad_docs.items():
        write_registry(world.registry_path, doc)
        with pytest.raises(RegistryRefused):
            _load(world.registry_path)
        assert name


def test_rotation_and_revocation_resolution(tmp_path):
    world = World(tmp_path)
    new = Ed25519PrivateKey.generate()
    old_entry = key_entry(
        world.reviewer,
        "independent-reviewer",
        state="retired",
        state_changed_at_utc="2026-10-23T06:00:00Z",
    )
    new_entry = key_entry(new, "independent-reviewer", supersedes=old_entry["key_id"])
    revoked = key_entry(
        Ed25519PrivateKey.generate(),
        "revoked-reviewer",
        state="revoked",
        state_changed_at_utc="2026-10-10T00:00:00Z",
    )
    registry = _load(
        write_registry(world.registry_path, registry_doc(old_entry, new_entry, revoked))
    )
    now = datetime(2026, 10, 23, 7, 0, tzinfo=UTC)
    before = datetime(2026, 10, 23, 5, 0, tzinfo=UTC)
    after = datetime(2026, 10, 23, 6, 30, tzinfo=UTC)
    for issued in (before, after):
        # A stolen retired key may backdate issued_at_utc; no fresh linking.
        with pytest.raises(RegistryRefused, match="signer_key_retired"):
            registry.resolve(old_entry["key_id"], "P3.3", issued, now)
    assert registry.resolve(new_entry["key_id"], "P3.5", after, now)
    for issued in (before, after):  # Revocation is retroactive and absolute.
        with pytest.raises(RegistryRefused, match="signer_key_revoked"):
            registry.resolve(revoked["key_id"], "P3.3", issued, now)
    with pytest.raises(RegistryRefused, match="signer_key_unknown"):
        registry.resolve("f" * 64, "P3.3", after, now)
    far = datetime(2027, 6, 1, tzinfo=UTC)
    with pytest.raises(RegistryRefused, match="signer_key_outside_validity"):
        registry.resolve(new_entry["key_id"], "P3.3", after, far)


def test_stage_role_is_restricted_by_registry(tmp_path):
    world = World(tmp_path)
    entry = key_entry(world.reviewer, "independent-reviewer", stages=["P3.3"])
    registry = _load(write_registry(world.registry_path, registry_doc(entry)))
    when = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)
    assert registry.resolve(entry["key_id"], "P3.3", when, when)
    with pytest.raises(RegistryRefused, match="signer_role_unauthorized"):
        registry.resolve(entry["key_id"], "P3.4", when, when)


def test_memory_ledger_detects_replay():
    ledger = MemoryReplayLedger()
    key = replay_key("r", "run", "P3.3")
    assert not ledger.seen(key) and not ledger.persistent
    ledger.record([key])
    assert ledger.seen(key)
    with pytest.raises(RegistryRefused, match="review_replay_detected"):
        ledger.record([key])
    assert replay_key("r", "run", "P3.4") != key != replay_key("r", "run2", "P3.3")


def test_file_ledger_persists_across_instances_and_is_all_or_nothing(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    path = state / "replay.ledger"
    path.touch(mode=0o600)  # pre-provisioned by the operator, never by verifier
    first = FileReplayLedger(path, POLICY)
    keys = [replay_key("r", "run", stage) for stage in ("P3.3", "P3.4")]
    first.record(keys)
    second = FileReplayLedger(path, POLICY)
    assert second.persistent and all(second.seen(key) for key in keys)
    fresh = replay_key("r", "run", "P3.5")
    with pytest.raises(RegistryRefused, match="review_replay_detected"):
        second.record([fresh, keys[0]])
    assert not second.seen(fresh)
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_file_ledger_refuses_unsafe_locations_and_content(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    state.chmod(0o755)
    with pytest.raises(RegistryRefused, match="ledger_directory_not_private"):
        FileReplayLedger(state / "ledger", POLICY).seen("0" * 64)
    state.chmod(0o700)
    ledger = state / "ledger"
    ledger.write_text("not-a-digest\n")
    ledger.chmod(0o600)
    with pytest.raises(RegistryRefused, match="ledger_file_corrupt"):
        FileReplayLedger(ledger, POLICY).seen("0" * 64)
    ledger.chmod(0o640)
    with pytest.raises(RegistryRefused, match="ledger_file_unsafe"):
        FileReplayLedger(ledger, POLICY).seen("0" * 64)
    ledger.unlink()
    target = tmp_path / "elsewhere"
    target.write_text("")
    ledger.symlink_to(target)
    with pytest.raises(RegistryRefused, match="ledger_unreadable"):
        FileReplayLedger(ledger, POLICY).seen("0" * 64)
    with pytest.raises(RegistryRefused, match="ledger_path_invalid"):
        FileReplayLedger("relative", POLICY)
