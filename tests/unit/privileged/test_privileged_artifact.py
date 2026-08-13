"""Exact installed-artifact identity and containment tests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from scripts.build_privileged_artifact_manifest import build_staging_manifest

from binnacle.privileged_broker.artifact import (
    PRIVILEGED_ARTIFACT_MANIFEST,
    PrivilegedArtifactError,
    PrivilegedArtifactFile,
    PrivilegedArtifactManifest,
    PrivilegedArtifactVerificationSettings,
    verify_privileged_artifact,
    write_privileged_artifact_manifest,
)


def _install_fixture(root: Path) -> tuple[PrivilegedArtifactManifest, Path]:
    (root / "bin").mkdir(parents=True)
    (root / "lib/binnacle").mkdir(parents=True)
    root.chmod(0o755)
    (root / "bin").chmod(0o755)
    (root / "lib").chmod(0o755)
    (root / "lib/binnacle").chmod(0o755)
    executable = root / "bin/binnacle-privileged-broker"
    module = root / "lib/binnacle/runtime.py"
    executable.write_bytes(b"#!/bin/sh\nexit 1\n")
    module.write_bytes(b"VALUE = 1\n")
    executable.chmod(0o755)
    module.chmod(0o644)
    manifest = PrivilegedArtifactManifest(
        format_version="binnacle-privileged-artifact-v1",
        directories=("bin", "lib", "lib/binnacle"),
        files=(
            _file(executable, root, "0755"),
            _file(module, root, "0644"),
        ),
    )
    document = {
        "directories": list(manifest.directories),
        "files": [
            {
                "byte_count": item.byte_count,
                "mode": item.mode,
                "path": item.path,
                "sha256": item.sha256,
            }
            for item in manifest.files
        ],
        "format_version": manifest.format_version,
    }
    manifest_path = root / PRIVILEGED_ARTIFACT_MANIFEST
    manifest_path.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    manifest_path.chmod(0o644)
    return manifest, executable


def _file(path: Path, root: Path, mode: str) -> PrivilegedArtifactFile:
    content = path.read_bytes()
    return PrivilegedArtifactFile(
        path=path.relative_to(root).as_posix(),
        mode=mode,
        byte_count=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _settings(root: Path) -> PrivilegedArtifactVerificationSettings:
    return PrivilegedArtifactVerificationSettings(
        root=root,
        expected_owner_uid=os.geteuid(),
        expected_owner_gid=os.getegid(),
        require_fixed_root=False,
    )


def test_artifact_manifest_binds_exact_tree_bytes_modes_and_build_digest(tmp_path: Path) -> None:
    root = tmp_path / "installed"
    manifest, _ = _install_fixture(root)

    observed = verify_privileged_artifact(
        expected_build_sha256=manifest.build_sha256,
        settings=_settings(root),
    )

    assert observed == manifest


def test_staging_manifest_writer_creates_one_verifiable_canonical_manifest(
    tmp_path: Path,
) -> None:
    root = tmp_path / "staging"
    (root / "bin").mkdir(parents=True)
    root.chmod(0o755)
    (root / "bin").chmod(0o755)
    executable = root / "bin/binnacle-privileged-broker"
    executable.write_bytes(b"#!/bin/sh\nexit 1\n")
    executable.chmod(0o755)

    result = build_staging_manifest(root)
    observed = verify_privileged_artifact(
        expected_build_sha256=str(result["build_sha256"]),
        settings=_settings(root),
    )

    assert result == {
        "build_sha256": observed.build_sha256,
        "directory_count": 1,
        "file_count": 1,
        "format_version": "binnacle-privileged-artifact-v1",
    }
    assert (root / PRIVILEGED_ARTIFACT_MANIFEST).stat().st_mode & 0o777 == 0o644


def test_staging_manifest_writer_refuses_republication_and_authoritative_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "staging"
    root.mkdir(mode=0o755)
    settings = _settings(root)

    write_privileged_artifact_manifest(settings=settings)
    with pytest.raises(PrivilegedArtifactError, match="already exists"):
        write_privileged_artifact_manifest(settings=settings)

    with pytest.raises(PrivilegedArtifactError, match="self-blessed"):
        write_privileged_artifact_manifest(settings=PrivilegedArtifactVerificationSettings())


def test_staging_manifest_generator_rejects_protected_host_roots() -> None:
    with pytest.raises(PrivilegedArtifactError, match="protected host state"):
        build_staging_manifest(Path("/opt"))


def test_artifact_verification_rejects_tamper_extra_entry_and_symlink(tmp_path: Path) -> None:
    root = tmp_path / "installed"
    manifest, executable = _install_fixture(root)
    executable.write_bytes(b"tampered\n")
    with pytest.raises(PrivilegedArtifactError, match=r"identity differs|digest differs"):
        verify_privileged_artifact(
            expected_build_sha256=manifest.build_sha256,
            settings=_settings(root),
        )

    executable.write_bytes(b"#!/bin/sh\nexit 1\n")
    extra = root / "unexpected"
    extra.write_text("extra", encoding="utf-8")
    extra.chmod(0o644)
    with pytest.raises(PrivilegedArtifactError, match="file set differs"):
        verify_privileged_artifact(
            expected_build_sha256=manifest.build_sha256,
            settings=_settings(root),
        )

    extra.unlink()
    (root / "link").symlink_to(executable)
    with pytest.raises(PrivilegedArtifactError, match="symlink"):
        verify_privileged_artifact(
            expected_build_sha256=manifest.build_sha256,
            settings=_settings(root),
        )


def test_artifact_verification_rejects_noncanonical_manifest_and_wrong_build(
    tmp_path: Path,
) -> None:
    root = tmp_path / "installed"
    manifest, _ = _install_fixture(root)
    manifest_path = root / PRIVILEGED_ARTIFACT_MANIFEST
    canonical = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(canonical.rstrip(), encoding="utf-8")
    with pytest.raises(PrivilegedArtifactError, match="not canonical"):
        verify_privileged_artifact(
            expected_build_sha256=manifest.build_sha256,
            settings=_settings(root),
        )

    manifest_path.write_text(canonical, encoding="utf-8")
    with pytest.raises(PrivilegedArtifactError, match="build digest differs"):
        verify_privileged_artifact(
            expected_build_sha256="f" * 64,
            settings=_settings(root),
        )


@pytest.mark.parametrize("path", ("../escape", "/absolute", "bad/../path", ""))
def test_artifact_manifest_rejects_noncanonical_paths(path: str) -> None:
    with pytest.raises(PrivilegedArtifactError, match="path"):
        PrivilegedArtifactFile(path=path, mode="0644", byte_count=0, sha256="a" * 64)
