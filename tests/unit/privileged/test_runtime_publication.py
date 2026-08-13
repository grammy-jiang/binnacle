"""Atomic immutable runtime-slot publication and selector-CAS tests."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from binnacle.domain.privileged_observation import (
    RuntimeSlotRole,
    RuntimeSlotState,
    VerifiedRuntimeSlot,
)
from binnacle.privileged_broker.runtime_publication import (
    FilesystemRuntimeSlotPublisher,
    RuntimeSelectorActivationRequest,
    RuntimeSelectorConflict,
    RuntimeSelectorPublicationUncertain,
    RuntimeSlotPublicationError,
    RuntimeSlotPublicationRequest,
    RuntimeSlotPublicationSettings,
    RuntimeSlotPublicationUncertain,
    runtime_selector_intent_sha256,
)
from binnacle.privileged_broker.runtime_slots import (
    FilesystemRuntimeSlotMaterialInspector,
    RuntimeSlotFile,
    RuntimeSlotInspectionSettings,
    RuntimeSlotManifest,
)

NOW = datetime(2026, 8, 13, 9, 10, 11, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _install_roots(tmp_path: Path) -> tuple[Path, Path]:
    runtime = tmp_path / "runtime"
    export = tmp_path / "export"
    (runtime / "slots").mkdir(parents=True)
    (runtime / ".staging").mkdir()
    (export / "bin").mkdir(parents=True)
    (export / "lib/binnacle").mkdir(parents=True)
    executable = export / "bin/binnacle"
    module = export / "lib/binnacle/runtime.py"
    executable.write_bytes(b"#!/bin/sh\nexit 1\n")
    module.write_bytes(b"VALUE = 1\n")
    executable.chmod(0o550)
    module.chmod(0o440)
    for directory in (export / "lib/binnacle", export / "lib", export / "bin", export):
        directory.chmod(0o550)
    runtime.chmod(0o750)
    (runtime / "slots").chmod(0o750)
    (runtime / ".staging").chmod(0o700)
    return runtime, export


def _manifest(
    export: Path,
    *,
    slot_id: str = "slot-0001",
    generation: int = 1,
) -> RuntimeSlotManifest:
    files = tuple(
        _file(export, path, mode)
        for path, mode in (
            ("bin/binnacle", "0550"),
            ("lib/binnacle/runtime.py", "0440"),
        )
    )
    return RuntimeSlotManifest(
        format_version="binnacle-runtime-slot-v1",
        slot_id=slot_id,
        slot_generation=generation,
        role=RuntimeSlotRole.CANDIDATE,
        state=RuntimeSlotState.COMPLETE,
        source_sha256=SHA_A,
        environment_sha256=SHA_B,
        config_sha256=SHA_C,
        policy_sha256=SHA_A,
        manifest_sha256=SHA_B,
        service_definition_sha256=SHA_C,
        deployed_peer_set_sha256=SHA_A,
        migration_heads_sha256=SHA_B,
        layout_sha256=SHA_C,
        candidate_verification_sha256=SHA_A,
        completed_at=NOW - timedelta(minutes=1),
        directories=("bin", "lib", "lib/binnacle"),
        files=files,
    )


def _file(root: Path, relative: str, mode: str) -> RuntimeSlotFile:
    content = (root / relative).read_bytes()
    return RuntimeSlotFile(
        path=relative,
        mode=mode,
        byte_count=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _settings(runtime: Path, export: Path) -> RuntimeSlotPublicationSettings:
    return RuntimeSlotPublicationSettings(
        export_root=export,
        expected_export_owner_uid=os.geteuid(),
        expected_export_group_gid=os.getegid(),
        runtime_root=runtime,
        expected_runtime_owner_uid=os.geteuid(),
        expected_runtime_group_gid=os.getegid(),
        expected_staging_group_gid=os.getegid(),
        maximum_slot_bytes=1_048_576,
        maximum_slot_inodes=1_000,
        maximum_retained_slots=3,
        require_fixed_runtime_root=False,
    )


def _publisher(tmp_path: Path) -> tuple[FilesystemRuntimeSlotPublisher, Path, Path]:
    runtime, export = _install_roots(tmp_path)
    return FilesystemRuntimeSlotPublisher(_settings(runtime, export)), runtime, export


def _request(manifest: RuntimeSlotManifest) -> RuntimeSlotPublicationRequest:
    return RuntimeSlotPublicationRequest(
        manifest=manifest,
        expected_complete_manifest_sha256=manifest.complete_manifest_sha256,
        requested_at=NOW,
    )


def _activation_request(
    *,
    selector_generation: int,
    operation_id: str | None,
    initial_bootstrap: bool,
    expected_current_slot_id: str | None,
    target_slot_id: str,
    target_slot_identity_sha256: str,
) -> RuntimeSelectorActivationRequest:
    intent = runtime_selector_intent_sha256(
        selector_generation=selector_generation,
        operation_id=operation_id,
        initial_bootstrap=initial_bootstrap,
        expected_current_slot_id=expected_current_slot_id,
        target_slot_id=target_slot_id,
        target_slot_identity_sha256=target_slot_identity_sha256,
        requested_at=NOW,
    )
    return RuntimeSelectorActivationRequest(
        selector_generation=selector_generation,
        operation_id=operation_id,
        initial_bootstrap=initial_bootstrap,
        expected_current_slot_id=expected_current_slot_id,
        target_slot_id=target_slot_id,
        target_slot_identity_sha256=target_slot_identity_sha256,
        retained_intent_sha256=intent,
        requested_at=NOW,
    )


def _inspect(runtime: Path, slot_id: str) -> VerifiedRuntimeSlot:
    return FilesystemRuntimeSlotMaterialInspector(
        RuntimeSlotInspectionSettings(
            runtime_root=runtime,
            expected_owner_uid=os.geteuid(),
            expected_group_gid=os.getegid(),
            maximum_slot_bytes=1_048_576,
            maximum_slot_inodes=1_000,
            maximum_retained_slots=3,
            require_fixed_root=False,
        )
    ).inspect_sync(slot_id)


def test_materialize_candidate_is_exact_durable_and_idempotent(tmp_path: Path) -> None:
    publisher, runtime, export = _publisher(tmp_path)
    manifest = _manifest(export)

    receipt = publisher.materialize_candidate(_request(manifest))
    replay = publisher.materialize_candidate(_request(manifest))
    observed = _inspect(runtime, manifest.slot_id)

    assert receipt.already_published is False
    assert replay.already_published is True
    assert receipt.slot_identity_sha256 == observed.slot_identity_sha256
    assert observed.candidate_verification_sha256 == SHA_A
    assert receipt.complete_manifest_sha256 == manifest.complete_manifest_sha256
    assert len(receipt.receipt_sha256) == 64
    assert not tuple((runtime / ".staging").iterdir())
    assert (runtime / "slots/slot-0001/bin/binnacle").read_bytes().startswith(b"#!")


def test_materialize_seals_private_stage_only_after_atomic_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher, runtime, export = _publisher(tmp_path)
    manifest = _manifest(export)
    rename_noreplace = publisher._rename_noreplace

    def verify_stage_then_rename(
        *,
        source_parent: Path,
        source_name: str,
        target_parent: Path,
        target_name: str,
    ) -> None:
        source_mode = stat.S_IMODE((source_parent / source_name).stat().st_mode)
        assert source_mode == 0o700
        rename_noreplace(
            source_parent=source_parent,
            source_name=source_name,
            target_parent=target_parent,
            target_name=target_name,
        )

    monkeypatch.setattr(publisher, "_rename_noreplace", verify_stage_then_rename)

    publisher.materialize_candidate(_request(manifest))

    assert stat.S_IMODE((runtime / "slots" / manifest.slot_id).stat().st_mode) == 0o550


def test_materialize_rejects_tamper_extra_symlink_and_wrong_mode(tmp_path: Path) -> None:
    publisher, _runtime, export = _publisher(tmp_path)
    manifest = _manifest(export)

    executable = export / "bin/binnacle"
    executable.chmod(0o750)
    with pytest.raises(RuntimeSlotPublicationError, match="identity differs"):
        publisher.materialize_candidate(_request(manifest))
    executable.chmod(0o550)

    export.chmod(0o750)
    extra = export / "extra"
    extra.write_text("unexpected", encoding="utf-8")
    extra.chmod(0o440)
    export.chmod(0o550)
    with pytest.raises(RuntimeSlotPublicationError, match="tree differs"):
        publisher.materialize_candidate(_request(manifest))
    export.chmod(0o750)
    extra.unlink()
    (export / "link").symlink_to("bin/binnacle")
    export.chmod(0o550)
    with pytest.raises(RuntimeSlotPublicationError, match="symlink"):
        publisher.materialize_candidate(_request(manifest))


def test_materialize_rejects_conflicting_slot_or_generation(tmp_path: Path) -> None:
    publisher, runtime, export = _publisher(tmp_path)
    first = _manifest(export)
    publisher.materialize_candidate(_request(first))

    conflicting = replace(first, candidate_verification_sha256=SHA_B)
    with pytest.raises(RuntimeSlotPublicationError, match="conflicts"):
        publisher.materialize_candidate(_request(conflicting))

    same_generation = _manifest(export, slot_id="slot-0002")
    with pytest.raises(RuntimeSlotPublicationError, match="generation is already used"):
        publisher.materialize_candidate(_request(same_generation))
    assert tuple(path.name for path in (runtime / "slots").iterdir()) == ("slot-0001",)


def test_materialize_cleans_private_stage_on_copy_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher, runtime, export = _publisher(tmp_path)
    manifest = _manifest(export)

    def fail_allocate(_descriptor: int, _offset: int, _length: int) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "posix_fallocate", fail_allocate)
    with pytest.raises(RuntimeSlotPublicationError, match="copy failed"):
        publisher.materialize_candidate(_request(manifest))
    assert not tuple((runtime / ".staging").iterdir())
    assert not tuple((runtime / "slots").iterdir())


def test_post_rename_sync_failure_is_uncertain_and_preserves_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher, runtime, export = _publisher(tmp_path)
    manifest = _manifest(export)
    real_fsync = os.fsync
    calls = 0

    def fail_last_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls >= 8:
            raise OSError("sync lost")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_last_fsync)
    with pytest.raises(RuntimeSlotPublicationUncertain):
        publisher.materialize_candidate(_request(manifest))
    assert (runtime / "slots/slot-0001").is_dir()


def test_selector_initial_publish_replay_and_compare_and_swap(tmp_path: Path) -> None:
    publisher, runtime, export = _publisher(tmp_path)
    first_manifest = _manifest(export)
    publisher.materialize_candidate(_request(first_manifest))
    first = _inspect(runtime, "slot-0001")
    initial = _activation_request(
        selector_generation=1,
        operation_id=None,
        initial_bootstrap=True,
        expected_current_slot_id=None,
        target_slot_id=first.slot_id,
        target_slot_identity_sha256=first.slot_identity_sha256,
    )

    receipt = publisher.activate_complete_slot(initial, observed_at=NOW)
    replay = publisher.activate_complete_slot(initial, observed_at=NOW)

    assert receipt.selector_changed is True
    assert replay.selector_changed is False
    assert os.readlink(runtime / "current") == "slots/slot-0001"
    assert len(receipt.receipt_sha256) == 64

    second_manifest = _manifest(export, slot_id="slot-0002", generation=2)
    publisher.materialize_candidate(_request(second_manifest))
    second = _inspect(runtime, "slot-0002")
    update = _activation_request(
        selector_generation=2,
        operation_id="operation-0002",
        initial_bootstrap=False,
        expected_current_slot_id=first.slot_id,
        target_slot_id=second.slot_id,
        target_slot_identity_sha256=second.slot_identity_sha256,
    )
    changed = publisher.activate_complete_slot(update, observed_at=NOW)

    assert changed.previous_slot_id == first.slot_id
    assert os.readlink(runtime / "current") == "slots/slot-0002"
    assert publisher.activate_complete_slot(update, observed_at=NOW).selector_changed is False
    stale = _activation_request(
        selector_generation=3,
        operation_id="operation-0003",
        initial_bootstrap=False,
        expected_current_slot_id=first.slot_id,
        target_slot_id=first.slot_id,
        target_slot_identity_sha256=first.slot_identity_sha256,
    )
    with pytest.raises(RuntimeSelectorConflict, match="preimage changed"):
        publisher.activate_complete_slot(stale, observed_at=NOW)


def test_selector_rejects_target_mismatch_and_restricted_slot(tmp_path: Path) -> None:
    publisher, _runtime, export = _publisher(tmp_path)
    manifest = _manifest(export)
    publisher.materialize_candidate(_request(manifest))
    target = _inspect(_runtime, manifest.slot_id)
    request = _activation_request(
        selector_generation=1,
        operation_id=None,
        initial_bootstrap=True,
        expected_current_slot_id=None,
        target_slot_id=target.slot_id,
        target_slot_identity_sha256=SHA_B,
    )
    with pytest.raises(RuntimeSelectorConflict, match="identity changed"):
        publisher.activate_complete_slot(request, observed_at=NOW)


def test_selector_post_replace_verification_failure_is_uncertain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher, runtime, export = _publisher(tmp_path)
    manifest = _manifest(export)
    publisher.materialize_candidate(_request(manifest))
    target = _inspect(runtime, manifest.slot_id)
    request = _activation_request(
        selector_generation=1,
        operation_id=None,
        initial_bootstrap=True,
        expected_current_slot_id=None,
        target_slot_id=target.slot_id,
        target_slot_identity_sha256=target.slot_identity_sha256,
    )
    real_fsync = os.fsync
    calls = 0

    def fail_after_replace(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("selector sync lost")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_after_replace)
    with pytest.raises(RuntimeSelectorPublicationUncertain):
        publisher.activate_complete_slot(request, observed_at=NOW)
    assert os.readlink(runtime / "current") == "slots/slot-0001"


@pytest.mark.parametrize(
    "factory,match",
    (
        (
            lambda manifest: RuntimeSlotPublicationRequest(
                manifest=manifest,
                expected_complete_manifest_sha256=SHA_B,
                requested_at=NOW,
            ),
            "digest differs",
        ),
        (
            lambda _manifest: RuntimeSelectorActivationRequest(
                selector_generation=1,
                operation_id="operation-1",
                initial_bootstrap=True,
                expected_current_slot_id=None,
                target_slot_id="slot-1",
                target_slot_identity_sha256=SHA_A,
                retained_intent_sha256=SHA_B,
                requested_at=NOW,
            ),
            "contradictory",
        ),
        (
            lambda _manifest: RuntimeSelectorActivationRequest(
                selector_generation=1,
                operation_id=None,
                initial_bootstrap=True,
                expected_current_slot_id=None,
                target_slot_id="slot-1",
                target_slot_identity_sha256=SHA_A,
                retained_intent_sha256=SHA_B,
                requested_at=NOW,
            ),
            "retained intent differs",
        ),
    ),
)
def test_publication_requests_reject_contradictory_authority(
    tmp_path: Path,
    factory: Callable[[RuntimeSlotManifest], object],
    match: str,
) -> None:
    _runtime, export = _install_roots(tmp_path)
    with pytest.raises(RuntimeSlotPublicationError, match=match):
        factory(_manifest(export))


def test_publication_settings_reject_overlap_and_noncanonical_root(tmp_path: Path) -> None:
    with pytest.raises(RuntimeSlotPublicationError, match="overlaps"):
        RuntimeSlotPublicationSettings(
            export_root=tmp_path / "runtime/export",
            expected_export_owner_uid=os.geteuid(),
            expected_export_group_gid=os.getegid(),
            runtime_root=tmp_path / "runtime",
            require_fixed_runtime_root=False,
        )
