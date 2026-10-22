"""End-to-end synthetic registry/attestation linking: external signer, refusals.

Every key is ephemeral and test-only; the operator, evidence and state roots are
separate temporary directories. No network, shell or production registry is used.
"""

from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import lsp_p36_link as link
from scripts.lsp_p36_link import LinkRefused, StageInput, link_stage_evidence
from scripts.lsp_p36_signed_review import ReviewRefused
from scripts.lsp_p36_trust_registry import (
    REGISTRY_ENV,
    FileReplayLedger,
    MemoryReplayLedger,
    RegistryRefused,
)
from tests.fixtures.lsp.trust_chain import (
    COMMIT,
    NOW,
    PRODUCER,
    REGISTRY_ID,
    RUN_ID,
    STAGES,
    TARGET,
    World,
    key_entry,
    process_owner_policy,
    sign_receipt,
    write_private,
)

POLICY = process_owner_policy()
REFUSALS = (LinkRefused, RegistryRefused, ReviewRefused)


def run(world: World, stages=None, ledger=None, **override):
    args: dict[str, Any] = {
        "registry_path": world.registry_path,
        "registry_policy": POLICY,
        "evidence_policy_": POLICY,
        "ledger": ledger if ledger is not None else MemoryReplayLedger(),
        "registry_id": REGISTRY_ID,
        "min_registry_serial": 1,
        "run_id": RUN_ID,
        "producer": PRODUCER,
        "binnacle_commit": COMMIT,
        "target_sha256": TARGET,
        "stages": stages if stages is not None else world.stage_inputs(),
        "now": NOW,
    }
    args.update(override)
    return link_stage_evidence(**args)


@pytest.fixture
def world(tmp_path):
    item = World(tmp_path)
    item.publish_registry()
    return item


def test_valid_external_signer_links_all_stages_without_authority(world):
    report = run(world)
    assert set(report["stages"]) == set(STAGES)
    for stage in report["stages"].values():
        assert stage["outcome"] == "verified_approval"
        assert stage["reviewer"] == "independent-reviewer"
    # Authenticated, signed approval is still not GO, READ or accepted confinement.
    assert report["selection"] == report["resource"] == "REWORK"
    assert report["read"] == report["public_release"] == "NO-GO"
    assert report["attestations_verified"] is False
    assert report["authority_granted"] is False
    assert report["os_confinement_accepted"] is False
    assert report["replay_protection"] == "ephemeral"
    assert report["registry"]["owner_is_current_user"] is True
    assert (
        "operator_registry_provenance_not_provable_from_agent_sandbox"
        in report["blockers"]
    )
    assert '"GO"' not in json.dumps(report)


def test_unconfigured_registry_fails_closed(world, monkeypatch):
    monkeypatch.delenv(REGISTRY_ENV, raising=False)
    with pytest.raises(RegistryRefused, match="trust_registry_not_configured"):
        run(world, registry_path=None)


def test_environment_registry_is_used_only_through_same_checks(world, monkeypatch):
    monkeypatch.setenv(REGISTRY_ENV, str(world.registry_path))
    assert run(world, registry_path=None)["selection"] == "REWORK"
    world.registry_path.chmod(0o666)
    with pytest.raises(RegistryRefused, match="file_mode_unsafe"):
        run(world, registry_path=None)


def test_wrong_key_signature_refused(world):
    stages = world.stage_inputs()
    rogue = Ed25519PrivateKey.generate()
    forged = sign_receipt(
        rogue,
        "P3.4",
        world.artifacts["P3.4"],
        world.evidence_sha("P3.4"),
        key_id=key_entry(world.reviewer, "x")["key_id"],  # Claims the real key id.
    )
    write_private(Path(stages["P3.4"].receipt), forged)
    with pytest.raises(ReviewRefused, match="review_signature_invalid"):
        run(world, stages=stages)


def test_injected_key_unknown_to_registry_refused(world):
    rogue = Ed25519PrivateKey.generate()
    stages = world.stage_inputs()
    forged = sign_receipt(
        rogue, "P3.3", world.artifacts["P3.3"], world.evidence_sha("P3.3")
    )
    write_private(Path(stages["P3.3"].receipt), forged)
    with pytest.raises(ReviewRefused, match="signer_key_unknown"):
        run(world, stages=stages)


def test_subject_report_cannot_inject_key_or_role(world):
    stages = world.stage_inputs()
    data = json.loads(Path(stages["P3.3"].receipt).read_bytes())
    for field in ({"public_key_b64": "A" * 44}, {"roles": ["reviewer"]}):
        write_private(
            Path(stages["P3.3"].receipt), json.dumps({**data, **field}).encode()
        )
        with pytest.raises(ReviewRefused, match="invalid_review_schema"):
            run(world, stages=stages)


def test_spoofed_self_reviewer_refused(world):
    producer_key = Ed25519PrivateKey.generate()
    # Producer key is not in the registry; naming the real reviewer does not help.
    stages = world.stage_inputs()
    spoof = sign_receipt(
        producer_key, "P3.3", world.artifacts["P3.3"], world.evidence_sha("P3.3")
    )
    write_private(Path(stages["P3.3"].receipt), spoof)
    with pytest.raises(ReviewRefused, match="signer_key_unknown"):
        run(world, stages=stages)
    # A genuine registry key whose receipt names the producer as reviewer.
    stages = world.stage_inputs(**{"P3.3": {"reviewer": PRODUCER}})
    with pytest.raises(ReviewRefused, match="signer_identity_mismatch"):
        run(world, stages=stages)
    # A producer-controlled registry entry is rejected when the registry loads.
    world.publish_registry(key_entry(world.reviewer, PRODUCER))
    with pytest.raises(RegistryRefused, match="registry_reviewer_is_producer"):
        run(world)


def test_expected_producer_equal_to_reviewer_refused(world):
    with pytest.raises(ReviewRefused, match="self_review_refused"):
        run(
            world,
            stages=world.stage_inputs(**{"P3.3": {"producer": "independent-reviewer"}}),
            producer="independent-reviewer",
        )


def test_revoked_key_refused_even_for_old_receipts(world):
    entry = key_entry(
        world.reviewer,
        "independent-reviewer",
        state="revoked",
        state_changed_at_utc="2026-10-23T06:59:30Z",
    )
    world.publish_registry(entry)
    with pytest.raises(ReviewRefused, match="signer_key_revoked"):
        run(world)


def test_deleted_key_refused(world):
    world.publish_registry(key_entry(Ed25519PrivateKey.generate(), "someone-else"))
    with pytest.raises(ReviewRefused, match="signer_key_unknown"):
        run(world)


def test_rotation_old_key_after_retirement_refused_new_key_accepted(world):
    old = key_entry(
        world.reviewer,
        "independent-reviewer",
        state="retired",
        state_changed_at_utc="2026-10-23T06:30:00Z",
    )
    successor = Ed25519PrivateKey.generate()
    new = key_entry(successor, "independent-reviewer", supersedes=old["key_id"])
    world.publish_registry(old, new)
    with pytest.raises(ReviewRefused, match="signer_key_retired"):
        run(world)  # Issued 06:59, after the old key retired at 06:30.
    world.reviewer = successor
    assert run(world, ledger=MemoryReplayLedger())["selection"] == "REWORK"


def test_role_limited_key_cannot_review_other_stage(world):
    world.publish_registry(
        key_entry(world.reviewer, "independent-reviewer", stages=["P3.3"])
    )
    with pytest.raises(ReviewRefused, match="signer_role_unauthorized"):
        run(world)


@pytest.mark.parametrize(
    "delta,reason",
    [
        (timedelta(days=2), "review_expired_or_future"),
        (timedelta(minutes=-10), "review_expired_or_future"),
    ],
)
def test_stale_and_future_receipts_refused(world, delta, reason):
    with pytest.raises(ReviewRefused, match=reason):
        run(world, now=NOW + delta)


def test_duplicate_json_receipt_refused(world):
    stages = world.stage_inputs()
    path = Path(stages["P3.5"].receipt)
    write_private(path, b'{"stage":"P3.5",' + path.read_bytes()[1:])
    with pytest.raises(ReviewRefused, match="invalid_review_schema"):
        run(world, stages=stages)


@pytest.mark.parametrize("mode", [0o660, 0o606])
def test_registry_with_improper_mode_refused(world, mode):
    world.registry_path.chmod(mode)
    with pytest.raises(RegistryRefused, match="file_mode_unsafe"):
        run(world)


def test_registry_with_improper_owner_refused(world):
    from scripts.lsp_p36_secure_io import PathPolicy

    other = PathPolicy(
        owner_uids=frozenset({os.geteuid() + 1}), allow_sticky_ancestors=True
    )
    with pytest.raises(RegistryRefused, match="owner_untrusted"):
        run(world, registry_policy=other)


def test_default_cli_policy_refuses_process_owned_registry(world, capsys):
    if os.geteuid() == 0:
        pytest.skip("process owner is root")
    stages = world.stage_inputs()
    argv = [
        "--registry",
        str(world.registry_path),
        "--registry-id",
        REGISTRY_ID,
        "--ledger",
        str(world.ledger_path),
        "--run-id",
        RUN_ID,
        "--producer",
        PRODUCER,
        "--binnacle-commit",
        COMMIT,
        "--target-sha256",
        TARGET,
    ]
    for stage in STAGES:
        entry = stages[stage]
        argv += [
            f"--{stage.lower().replace('.', '')}",
            entry.artifact,
            entry.evidence_sha256,
            entry.receipt,
        ]
    assert link.main(argv) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["selection"] == "NO-GO" and out["read"] == "NO-GO"
    assert out["reason"].startswith("registry_path_")
    assert out["attestations_verified"] is False


def test_registry_symlink_path_refused(world, tmp_path):
    (tmp_path / "alias").symlink_to(world.registry_path.parent)
    with pytest.raises(RegistryRefused, match="symlink"):
        run(world, registry_path=tmp_path / "alias" / "registry.json")


def test_evidence_symlink_and_hardlink_refused(world, tmp_path):
    stages = world.stage_inputs()
    artifact = Path(stages["P3.3"].artifact)
    moved = artifact.with_name("real.json")
    artifact.rename(moved)
    artifact.symlink_to(moved)
    with pytest.raises(LinkRefused, match="evidence_path_symlink"):
        run(world, stages=stages)
    artifact.unlink()
    os.link(moved, artifact)
    with pytest.raises(LinkRefused, match="hardlink"):
        run(world, stages=stages)


def test_registry_located_among_evidence_refused(world, tmp_path):
    evidence_dir = tmp_path / "evidence"
    inside = write_private(
        evidence_dir / "registry.json", world.registry_path.read_bytes()
    )
    with pytest.raises(RegistryRefused, match="untrusted_root"):
        run(world, registry_path=inside)


def test_evidence_located_inside_registry_directory_refused(world):
    stages = world.stage_inputs()
    art = Path(stages["P3.3"].artifact)
    nested = world.registry_path.parent / "nested" / "a.json"
    inside = write_private(nested, art.read_bytes())
    stages["P3.3"] = StageInput(
        str(inside), stages["P3.3"].evidence_sha256, stages["P3.3"].receipt
    )
    with pytest.raises(LinkRefused, match="untrusted_root"):
        run(world, stages=stages)


def test_registry_inside_repository_checkout_refused(world, monkeypatch):
    monkeypatch.setattr(link, "REPO", world.registry_path.parent)
    with pytest.raises(RegistryRefused, match="untrusted_root"):
        run(world)


def test_replay_refused_across_ledger_instances(world):
    ledger_path = world.ledger_path
    ledger_path.parent.mkdir(mode=0o700)
    first = run(world, ledger=FileReplayLedger(ledger_path, POLICY))
    assert first["replay_protection"] == "persistent_ledger"
    with pytest.raises(ReviewRefused, match="review_replay_detected"):
        run(world, ledger=FileReplayLedger(ledger_path, POLICY))


def test_failed_link_does_not_burn_ledger_entries(world):
    ledger = MemoryReplayLedger()
    stages = world.stage_inputs(**{"P3.5": {"verdict": "REWORK", "run_id": "other"}})
    with pytest.raises(ReviewRefused, match="scope_or_identity_mismatch"):
        run(world, stages=stages, ledger=ledger)
    assert run(world, ledger=ledger)["selection"] == "REWORK"


@pytest.mark.parametrize(
    "override",
    [
        {"run_id": "another-run"},
        {"binnacle_commit": "b" * 40},
        {"target_sha256": "c" * 64},
        {"producer": "different-producer"},
        {"registry_id": "other-registry"},
    ],
)
def test_expected_identity_mismatch_refused(world, override):
    with pytest.raises(REFUSALS):
        run(world, **override)


@pytest.mark.parametrize(
    "field,value",
    [
        ("target_sha256", "d" * 64),
        ("binnacle_commit", "e" * 40),
        ("run_id", "someone-elses-run"),
        ("registry_id", "other-registry"),
        ("evidence_sha256", "f" * 64),
    ],
)
def test_receipt_bound_to_other_scope_refused(world, field, value):
    stages = world.stage_inputs(**{"P3.4": {field: value}})
    with pytest.raises(ReviewRefused, match="scope_or_identity_mismatch"):
        run(world, stages=stages, ledger=MemoryReplayLedger())


def test_altered_raw_artifact_refused(world):
    stages = world.stage_inputs()
    path = Path(stages["P3.5"].artifact)
    write_private(path, path.read_bytes().replace(b"synthetic", b"tampered_"))
    with pytest.raises(ReviewRefused, match="scope_or_identity_mismatch"):
        run(world, stages=stages)


def test_cross_stage_substitution_refused(world):
    stages = world.stage_inputs()
    swapped = {
        **stages,
        "P3.5": StageInput(
            stages["P3.4"].artifact,
            stages["P3.5"].evidence_sha256,
            stages["P3.4"].receipt,
        ),
    }
    with pytest.raises(ReviewRefused, match="scope_or_identity_mismatch"):
        run(world, stages=swapped)


def test_same_artifact_reused_across_stages_refused(world):
    shared = b'{"one":"artifact"}'
    stages = world.stage_inputs()
    for stage in STAGES:
        write_private(Path(stages[stage].artifact), shared)
        write_private(
            Path(stages[stage].receipt),
            sign_receipt(world.reviewer, stage, shared, world.evidence_sha(stage)),
        )
    with pytest.raises(LinkRefused, match="cross_stage_artifact_reuse"):
        run(world, stages=stages)


def test_missing_stage_or_missing_file_refused(world):
    stages = world.stage_inputs()
    partial = {k: v for k, v in stages.items() if k != "P3.4"}
    with pytest.raises(LinkRefused, match="stage_evidence_missing_or_unknown"):
        run(world, stages=partial)
    with pytest.raises(LinkRefused, match="stage_evidence_missing_or_unknown"):
        run(world, stages={**stages, "P9.9": stages["P3.3"]})
    Path(stages["P3.4"].receipt).unlink()
    with pytest.raises(LinkRefused, match="evidence_path_symlink_or_unreadable"):
        run(world, stages=stages)


def test_negative_verdicts_are_reported_but_never_promoted(world):
    stages = world.stage_inputs(**{"P3.3": {"verdict": "NO-GO"}})
    report = run(world, stages=stages)
    assert report["stages"]["P3.3"]["outcome"] == "verified_no_go"
    assert report["selection"] == "REWORK" and report["read"] == "NO-GO"


def test_registry_and_ledger_are_never_created_by_the_pipeline(world, tmp_path):
    stages = world.stage_inputs()
    before = sorted(p.name for p in tmp_path.iterdir())
    run(world, stages=stages)
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert not (tmp_path / "state").exists()
