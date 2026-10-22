"""Independent-review negative controls: registry pin, refusal, and ledger durability.

All keys, files and payloads are synthetic and confined to pytest temp dirs.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from scripts import lsp_p36_link as link
from scripts.lsp_p36_link import LinkRefused
from scripts.lsp_p36_signed_review import (
    ReviewRefused,
    verify_signed_review,
)
from scripts.lsp_p36_trust_registry import FileReplayLedger, RegistryRefused, replay_key
from tests.fixtures.lsp.trust_chain import (
    COMMIT,
    PRODUCER,
    REGISTRY_ID,
    RUN_ID,
    STAGES,
    TARGET,
    World,
    process_owner_policy,
    write_private,
)
from tests.scripts.test_lsp_p36_link import run


@pytest.fixture
def world(tmp_path):
    item = World(tmp_path)
    item.publish_registry()
    return item


def _argv(world: World) -> list[str]:
    stages = world.stage_inputs()
    arguments = [
        "--registry",
        str(world.registry_path),
        "--registry-id",
        REGISTRY_ID,
        "--min-registry-serial",
        "3",
        "--registry-sha256",
        hashlib.sha256(world.registry_path.read_bytes()).hexdigest(),
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
        arguments.extend(
            [
                f"--{stage.lower().replace('.', '')}",
                entry.artifact,
                entry.evidence_sha256,
                entry.receipt,
            ]
        )
    return arguments


def test_same_serial_but_modified_registry_bytes_cannot_reuse_operator_pin(world):
    original = hashlib.sha256(world.registry_path.read_bytes()).hexdigest()
    altered = json.loads(world.registry_path.read_text())
    altered["issued_at_utc"] = "2026-10-02T00:00:00Z"
    write_private(world.registry_path, json.dumps(altered).encode())
    with pytest.raises(LinkRefused, match="operator_registry_sha256_mismatch"):
        run(world, expected_registry_sha256=original)
    assert original != hashlib.sha256(world.registry_path.read_bytes()).hexdigest()


@pytest.mark.parametrize("omitted", ["--min-registry-serial", "--registry-sha256"])
def test_cli_requires_out_of_band_registry_serial_and_digest(world, omitted):
    args = _argv(world)
    index = args.index(omitted)
    del args[index : index + 2]
    with pytest.raises(SystemExit) as error:
        link.main(args)
    assert error.value.code == 2


def test_invalid_calendar_timestamp_rejected_without_leaking_receipt(world):
    stages = world.stage_inputs(**{"P3.4": {"issued_at_utc": "2026-13-45T99:99:99Z"}})
    with pytest.raises(ReviewRefused, match="invalid_review_timestamp"):
        run(world, stages=stages)


def test_excessively_nested_json_refuses_in_both_signature_formats(world):
    args = world.stage_inputs()
    receipt = b"[" * 1400 + b"0" + b"]" * 1400
    write_private(Path(args["P3.4"].receipt), receipt)
    with pytest.raises(ReviewRefused, match="invalid_review_schema"):
        run(world, stages=args)
    public = b"p" * 32
    with pytest.raises(ReviewRefused, match="invalid_review_schema"):
        verify_signed_review(
            receipt,
            public_key=public,
            pinned_public_key_sha256=hashlib.sha256(public).hexdigest(),
            expected_reviewer="synthetic-only",
            expected_producer="producer-only",
            expected_stage="P3.4",
            expected_target_sha256=TARGET,
            expected_evidence_sha256=hashlib.sha256(b"e").hexdigest(),
            reviewed_artifact=b"synthetic-not-secret",
        )


def test_cli_runtime_failure_emits_non_authorizing_fixed_json(
    world, monkeypatch, capsys
):
    args = _argv(world)

    def sabotage(**kwargs):
        raise OSError("synthetic-private-token: should never print")

    monkeypatch.setattr(link, "link_stage_evidence", sabotage)
    assert link.main(args) == 2
    output = capsys.readouterr()
    obj = json.loads(output.out)
    assert obj["selection"] == obj["read"] == "NO-GO"
    assert obj["reason"] == "internal_error"
    assert obj["attestations_verified"] is False
    assert "synthetic-private-token" not in output.out + output.err


def test_ledger_never_implicitly_creates_fresh_replay_state(tmp_path):
    directory = tmp_path / "operator-state"
    directory.mkdir(mode=0o700)
    path = directory / "replay.ledger"
    ledger = FileReplayLedger(path, process_owner_policy())
    with pytest.raises(RegistryRefused, match="ledger_unreadable"):
        ledger.seen("0" * 64)
    with pytest.raises(RegistryRefused, match="ledger_unreadable"):
        ledger.record(["0" * 64])
    assert not path.exists()


def test_file_ledger_handles_multiple_partial_os_writes(tmp_path, monkeypatch):
    folder = tmp_path / "operator-state"
    folder.mkdir(mode=0o700)
    path = folder / "replay.ledger"
    path.touch(mode=0o600)
    ledger = FileReplayLedger(path, process_owner_policy())
    keys = [replay_key(REGISTRY_ID, RUN_ID, stage) for stage in STAGES]
    original = os.write
    counts = []

    def fragment(fd: int, data: bytes) -> int:
        if len(data) > 7:
            counts.append(len(data))
        return original(fd, data[:7])

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", fragment)
        ledger.record(keys)
    assert counts
    assert all(ledger.seen(key) for key in keys)
    assert path.read_bytes() == "".join(key + "\n" for key in keys).encode()


def test_corrupted_or_truncated_ledger_blocks_reuse(tmp_path):
    folder = tmp_path / "operator-state"
    folder.mkdir(mode=0o700)
    file = folder / "replay.ledger"
    file.write_bytes(b"a" * 64)
    file.chmod(0o600)
    ledger = FileReplayLedger(file, process_owner_policy())
    with pytest.raises(RegistryRefused, match="ledger_file_corrupt"):
        ledger.seen("a" * 64)


@pytest.mark.parametrize(
    "identity",
    [
        ("operator\x00alpha", "batch1", "P3.3"),
        ("operator", "batch\x00one", "P3.3"),
        ("operator", "batch1", "P3.3\x00P3.4"),
    ],
)
def test_replay_identity_cannot_embed_nul_separator(identity):
    from scripts.lsp_p36_trust_registry import replay_key

    with pytest.raises(RegistryRefused, match="replay_identity_invalid"):
        replay_key(*identity)
