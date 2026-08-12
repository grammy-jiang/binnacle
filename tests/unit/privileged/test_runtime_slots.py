"""Read-only complete runtime-slot and selector verification tests."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from binnacle.domain.privileged_observation import RuntimeSlotRole, RuntimeSlotState
from binnacle.privileged_broker.runtime_slots import (
    RUNTIME_SLOT_MANIFEST,
    FilesystemRuntimeSlotInspector,
    RuntimeSlotFile,
    RuntimeSlotInspectionSettings,
    RuntimeSlotManifest,
    RuntimeSlotVerificationError,
    canonical_runtime_slot_manifest_bytes,
)

NOW = datetime(2026, 8, 13, 2, 3, 4, 567890, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _settings(root: Path, *, retained: int = 3) -> RuntimeSlotInspectionSettings:
    return RuntimeSlotInspectionSettings(
        runtime_root=root,
        expected_owner_uid=os.geteuid(),
        expected_group_gid=os.getegid(),
        maximum_slot_bytes=1_048_576,
        maximum_slot_inodes=1_000,
        maximum_retained_slots=retained,
        require_fixed_root=False,
    )


def _install_root(root: Path) -> None:
    (root / "slots").mkdir(parents=True)
    root.chmod(0o750)
    (root / "slots").chmod(0o750)


def _install_slot(
    root: Path,
    *,
    slot_id: str = "slot-0001",
    generation: int = 1,
    role: RuntimeSlotRole = RuntimeSlotRole.LKG,
    state: RuntimeSlotState = RuntimeSlotState.LKG,
) -> tuple[RuntimeSlotManifest, Path]:
    slot = root / "slots" / slot_id
    (slot / "bin").mkdir(parents=True)
    (slot / "lib/binnacle").mkdir(parents=True)
    executable = slot / "bin/binnacle"
    module = slot / "lib/binnacle/runtime.py"
    executable.write_bytes(b"#!/bin/sh\nexit 1\n")
    module.write_bytes(b"VALUE = 1\n")
    executable.chmod(0o550)
    module.chmod(0o440)
    files = (
        _file(executable, slot, "0550"),
        _file(module, slot, "0440"),
    )
    manifest = RuntimeSlotManifest(
        format_version="binnacle-runtime-slot-v1",
        slot_id=slot_id,
        slot_generation=generation,
        role=role,
        state=state,
        source_sha256=SHA_A,
        environment_sha256=SHA_B,
        config_sha256=SHA_C,
        policy_sha256=SHA_A,
        manifest_sha256=SHA_B,
        service_definition_sha256=SHA_C,
        deployed_peer_set_sha256=SHA_A,
        migration_heads_sha256=SHA_B,
        layout_sha256=SHA_C,
        completed_at=NOW,
        directories=("bin", "lib", "lib/binnacle"),
        files=files,
    )
    manifest_path = slot / RUNTIME_SLOT_MANIFEST
    manifest_path.write_bytes(canonical_runtime_slot_manifest_bytes(manifest))
    manifest_path.chmod(0o440)
    for directory in (slot / "bin", slot / "lib/binnacle", slot / "lib", slot):
        directory.chmod(0o550)
    return manifest, executable


def _file(path: Path, root: Path, mode: str) -> RuntimeSlotFile:
    content = path.read_bytes()
    return RuntimeSlotFile(
        path=path.relative_to(root).as_posix(),
        mode=mode,
        byte_count=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _rewrite_manifest(
    root: Path,
    mutate: Callable[[dict[str, object]], object],
) -> None:
    path = root / "slots/slot-0001" / RUNTIME_SLOT_MANIFEST
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    mutate(document)
    path.chmod(0o640)
    path.write_text(
        json.dumps(document, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o440)


@pytest.mark.anyio
async def test_runtime_slot_current_and_lkg_are_verified_from_exact_manifest(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    _install_root(root)
    manifest, _ = _install_slot(root)
    (root / "current").symlink_to("slots/slot-0001")
    inspector = FilesystemRuntimeSlotInspector(_settings(root))

    direct = await inspector.inspect("slot-0001")
    current = await inspector.current()
    lkg = await inspector.lkg()

    assert direct == current == lkg
    assert direct is not None
    assert direct.complete_manifest_sha256 == manifest.complete_manifest_sha256
    assert direct.byte_count == manifest.byte_count
    assert direct.inode_count == manifest.inode_count


@pytest.mark.anyio
async def test_runtime_slot_inspection_rejects_tamper_extra_and_symlink(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    _install_root(root)
    _, executable = _install_slot(root)
    inspector = FilesystemRuntimeSlotInspector(_settings(root))

    executable.chmod(0o750)
    with pytest.raises(RuntimeSlotVerificationError, match="identity differs"):
        await inspector.inspect("slot-0001")

    executable.chmod(0o750)
    executable.write_bytes(b"tampered\n")
    executable.chmod(0o550)
    with pytest.raises(RuntimeSlotVerificationError, match=r"identity differs|digest differs"):
        await inspector.inspect("slot-0001")

    executable.chmod(0o750)
    executable.write_bytes(b"#!/bin/sh\nexit 1\n")
    executable.chmod(0o550)
    slot = root / "slots/slot-0001"
    slot.chmod(0o750)
    extra = slot / "extra"
    extra.write_text("unexpected", encoding="utf-8")
    extra.chmod(0o440)
    slot.chmod(0o550)
    with pytest.raises(RuntimeSlotVerificationError, match="file set differs"):
        await inspector.inspect("slot-0001")

    slot.chmod(0o750)
    extra.unlink()
    (slot / "link").symlink_to("bin/binnacle")
    slot.chmod(0o550)
    with pytest.raises(RuntimeSlotVerificationError, match="symlink"):
        await inspector.inspect("slot-0001")


@pytest.mark.anyio
async def test_runtime_selector_is_relative_owned_and_optional(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    _install_root(root)
    _install_slot(root)
    inspector = FilesystemRuntimeSlotInspector(_settings(root))

    assert await inspector.current() is None
    (root / "current").symlink_to("/srv/binnacle-runtime/slots/slot-0001")
    with pytest.raises(RuntimeSlotVerificationError, match="target is invalid"):
        await inspector.current()


@pytest.mark.anyio
async def test_runtime_slot_rejects_noncanonical_manifest_and_identity(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    _install_root(root)
    _, _ = _install_slot(root)
    manifest_path = root / "slots/slot-0001" / RUNTIME_SLOT_MANIFEST
    manifest_path.chmod(0o640)
    inspector = FilesystemRuntimeSlotInspector(_settings(root))
    with pytest.raises(RuntimeSlotVerificationError, match="manifest is unsafe"):
        await inspector.inspect("slot-0001")

    manifest_path.chmod(0o640)
    raw = manifest_path.read_bytes()
    manifest_path.write_bytes(raw.rstrip(b"\n"))
    manifest_path.chmod(0o440)
    with pytest.raises(RuntimeSlotVerificationError, match="not canonical"):
        await inspector.inspect("slot-0001")


@pytest.mark.anyio
async def test_runtime_slot_lkg_scan_is_bounded_and_unique(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    _install_root(root)
    _install_slot(root, slot_id="slot-0001", generation=1)
    _install_slot(root, slot_id="slot-0002", generation=2)
    inspector = FilesystemRuntimeSlotInspector(_settings(root))

    with pytest.raises(RuntimeSlotVerificationError, match="multiple complete LKG"):
        await inspector.lkg()

    _install_slot(
        root,
        slot_id="slot-0003",
        generation=3,
        role=RuntimeSlotRole.PRIOR,
        state=RuntimeSlotState.PRIOR,
    )
    _install_slot(
        root,
        slot_id="slot-0004",
        generation=4,
        role=RuntimeSlotRole.PRIOR,
        state=RuntimeSlotState.PRIOR,
    )
    with pytest.raises(RuntimeSlotVerificationError, match="retained runtime slot ceiling"):
        await inspector.lkg()


@pytest.mark.parametrize("slot_id", ("../escape", "bad/slot", "bad..slot", "UPPER"))
@pytest.mark.anyio
async def test_runtime_slot_rejects_untrusted_slot_identifiers(
    tmp_path: Path,
    slot_id: str,
) -> None:
    root = tmp_path / "runtime"
    _install_root(root)
    inspector = FilesystemRuntimeSlotInspector(_settings(root))

    with pytest.raises(RuntimeSlotVerificationError, match="identity"):
        await inspector.inspect(slot_id)


@pytest.mark.parametrize(
    "factory,match",
    (
        (
            lambda: RuntimeSlotFile("bin/tool", "0640", 1, SHA_A),
            "mode",
        ),
        (
            lambda: RuntimeSlotFile("bin/tool", "0440", 2_147_483_649, SHA_A),
            "size",
        ),
        (
            lambda: RuntimeSlotFile("../tool", "0440", 1, SHA_A),
            "path",
        ),
        (
            lambda: RuntimeSlotFile("bin/tool", "0440", 1, "bad"),
            "digest",
        ),
    ),
)
def test_runtime_slot_file_contract_rejects_unsafe_values(
    factory: Callable[[], object],
    match: str,
) -> None:
    with pytest.raises(RuntimeSlotVerificationError, match=match):
        factory()


def test_runtime_slot_manifest_contract_is_closed(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    _install_root(root)
    manifest, _ = _install_slot(root)
    invalid: tuple[tuple[Callable[[], object], str], ...] = (
        (lambda: replace(manifest, format_version="future"), "format"),
        (lambda: replace(manifest, slot_generation=0), "generation"),
        (
            lambda: replace(manifest, completed_at=NOW.replace(tzinfo=None)),
            "completion time",
        ),
        (lambda: replace(manifest, directories=("lib", "bin")), "directories"),
        (lambda: replace(manifest, directories=("bin", "bin")), "directories"),
        (lambda: replace(manifest, directories=("../escape",)), "path"),
        (lambda: replace(manifest, files=tuple(reversed(manifest.files))), "files"),
        (
            lambda: replace(
                manifest,
                directories=tuple(sorted((*manifest.directories, manifest.files[0].path))),
            ),
            "two kinds",
        ),
        (
            lambda: replace(
                manifest,
                files=(
                    *manifest.files,
                    RuntimeSlotFile(RUNTIME_SLOT_MANIFEST, "0440", 1, SHA_A),
                ),
            ),
            "inventory itself",
        ),
    )
    for factory, match in invalid:
        with pytest.raises(RuntimeSlotVerificationError, match=match):
            factory()


@pytest.mark.parametrize(
    "kwargs",
    (
        {"runtime_root": Path("relative")},
        {"expected_owner_uid": -1},
        {"maximum_slot_bytes": 1_048_575},
        {"maximum_slot_inodes": 999},
        {"maximum_retained_slots": 2},
    ),
)
def test_runtime_slot_settings_reject_unbounded_profiles(
    tmp_path: Path,
    kwargs: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "runtime_root": tmp_path / "runtime",
        "require_fixed_root": False,
    }
    values.update(kwargs)
    with pytest.raises(RuntimeSlotVerificationError, match="settings"):
        RuntimeSlotInspectionSettings(**values)  # type: ignore[arg-type]


def test_runtime_slot_settings_require_the_fixed_root() -> None:
    with pytest.raises(RuntimeSlotVerificationError, match="protected path"):
        RuntimeSlotInspectionSettings(runtime_root=Path("/srv/other"))


@pytest.mark.anyio
async def test_runtime_slot_rejects_unsafe_roots_slot_and_directory(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    _install_root(root)
    _install_slot(root)
    inspector = FilesystemRuntimeSlotInspector(_settings(root))

    root.chmod(0o770)
    with pytest.raises(RuntimeSlotVerificationError, match="runtime root ownership or mode"):
        await inspector.inspect("slot-0001")
    root.chmod(0o750)

    slot = root / "slots/slot-0001"
    slot.chmod(0o750)
    with pytest.raises(RuntimeSlotVerificationError, match="slot ownership or mode"):
        await inspector.inspect("slot-0001")
    slot.chmod(0o550)

    nested = slot / "lib"
    nested.chmod(0o750)
    with pytest.raises(RuntimeSlotVerificationError, match="directory ownership or mode"):
        await inspector.inspect("slot-0001")


@pytest.mark.anyio
async def test_runtime_slot_rejects_manifest_identity_and_resource_ceiling(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    _install_root(root)
    manifest, _ = _install_slot(root)
    inspector = FilesystemRuntimeSlotInspector(_settings(root))
    path = root / "slots/slot-0001" / RUNTIME_SLOT_MANIFEST

    wrong_identity = replace(manifest, slot_id="slot-other")
    path.chmod(0o640)
    path.write_bytes(canonical_runtime_slot_manifest_bytes(wrong_identity))
    path.chmod(0o440)
    with pytest.raises(RuntimeSlotVerificationError, match="identity differs"):
        await inspector.inspect("slot-0001")

    oversized = replace(
        manifest,
        files=(replace(manifest.files[0], byte_count=1_048_577), manifest.files[1]),
    )
    path.chmod(0o640)
    path.write_bytes(canonical_runtime_slot_manifest_bytes(oversized))
    path.chmod(0o440)
    with pytest.raises(RuntimeSlotVerificationError, match="byte ceiling"):
        await inspector.inspect("slot-0001")

    too_many = replace(
        manifest,
        directories=tuple(f"d{index:04d}" for index in range(1_001)),
    )
    path.chmod(0o640)
    path.write_bytes(canonical_runtime_slot_manifest_bytes(too_many))
    path.chmod(0o440)
    with pytest.raises(RuntimeSlotVerificationError, match="inode ceiling"):
        await inspector.inspect("slot-0001")


@pytest.mark.parametrize(
    "mutate,match",
    (
        (lambda value: value.pop("policy_sha256"), "fields are not exact"),
        (lambda value: value.__setitem__("directories", "bin"), "shape"),
        (lambda value: value.__setitem__("slot_generation", True), "shape"),
        (
            lambda value: value["files"][0].pop("mode"),
            "file fields",
        ),
        (
            lambda value: value["files"][0].__setitem__("byte_count", True),
            "file size",
        ),
        (
            lambda value: value["files"][0].__setitem__("mode", 440),
            "file value",
        ),
        (lambda value: value.__setitem__("source_sha256", 1), "manifest value"),
        (lambda value: value.__setitem__("role", "unknown"), "enum or time"),
        (
            lambda value: value.__setitem__("completed_at", "2026-08-13T02:03:04.56789+00:00"),
            "not canonical",
        ),
    ),
)
@pytest.mark.anyio
async def test_runtime_slot_rejects_malformed_manifest_shapes(
    tmp_path: Path,
    mutate: Callable[[dict[str, object]], object],
    match: str,
) -> None:
    root = tmp_path / "runtime"
    _install_root(root)
    _install_slot(root)
    _rewrite_manifest(root, mutate)

    with pytest.raises(RuntimeSlotVerificationError, match=match):
        await FilesystemRuntimeSlotInspector(_settings(root)).inspect("slot-0001")


@pytest.mark.anyio
async def test_runtime_slot_rejects_duplicate_invalid_and_unavailable_manifest(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    _install_root(root)
    _install_slot(root)
    inspector = FilesystemRuntimeSlotInspector(_settings(root))
    path = root / "slots/slot-0001" / RUNTIME_SLOT_MANIFEST

    raw = path.read_text(encoding="utf-8")
    path.chmod(0o640)
    path.write_text(raw.replace('{"completed_at":', '{"completed_at":"x","completed_at":', 1))
    path.chmod(0o440)
    with pytest.raises(RuntimeSlotVerificationError, match="invalid JSON"):
        await inspector.inspect("slot-0001")

    path.chmod(0o640)
    path.write_bytes(b"\xff")
    path.chmod(0o440)
    with pytest.raises(RuntimeSlotVerificationError, match="invalid JSON"):
        await inspector.inspect("slot-0001")

    slot = path.parent
    slot.chmod(0o750)
    path.unlink()
    slot.chmod(0o550)
    with pytest.raises(RuntimeSlotVerificationError, match="unavailable"):
        await inspector.inspect("slot-0001")


@pytest.mark.anyio
async def test_runtime_slot_rejects_unsupported_entry_and_selector_shapes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    _install_root(root)
    _install_slot(root)
    inspector = FilesystemRuntimeSlotInspector(_settings(root))
    slot = root / "slots/slot-0001"

    slot.chmod(0o750)
    os.mkfifo(slot / "pipe", 0o440)
    slot.chmod(0o550)
    with pytest.raises(RuntimeSlotVerificationError, match="entry type"):
        await inspector.inspect("slot-0001")
    slot.chmod(0o750)
    (slot / "pipe").unlink()
    slot.chmod(0o550)

    selector = root / "current"
    selector.write_text("slots/slot-0001", encoding="utf-8")
    with pytest.raises(RuntimeSlotVerificationError, match="identity is unsafe"):
        await inspector.current()
    selector.unlink()
    selector.symlink_to("slots/UPPER")
    with pytest.raises(RuntimeSlotVerificationError, match="identity"):
        await inspector.current()


@pytest.mark.anyio
async def test_runtime_slot_lkg_none_and_scan_rejects_non_slot_entry(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    _install_root(root)
    _install_slot(
        root,
        role=RuntimeSlotRole.PRIOR,
        state=RuntimeSlotState.PRIOR,
    )
    inspector = FilesystemRuntimeSlotInspector(_settings(root))
    assert await inspector.lkg() is None

    unexpected = root / "slots/not-a-slot.txt"
    unexpected.write_text("bad", encoding="utf-8")
    with pytest.raises(RuntimeSlotVerificationError, match="entry type"):
        await inspector.lkg()


@pytest.mark.anyio
async def test_runtime_slot_translates_domain_role_state_contradiction(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    _install_root(root)
    _install_slot(root, role=RuntimeSlotRole.LKG, state=RuntimeSlotState.PRIOR)

    with pytest.raises(RuntimeSlotVerificationError, match="manifest is contradictory"):
        await FilesystemRuntimeSlotInspector(_settings(root)).inspect("slot-0001")
