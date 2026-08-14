"""Platform qualification for the Phase 6 no-xattr mutation profile."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from binnacle.adapters.workspace import LinuxWorkspace, WorkspaceEffectNotStarted
from binnacle.domain.workspace import WorkspaceObjectKind
from binnacle.ports.workspace import WorkspaceCreateIntent

PROFILE_SHA256 = "a" * 64


def _workspace(root: Path) -> LinuxWorkspace:
    return LinuxWorkspace(
        root=root,
        workspace_id="binnacle-source",
        profile_sha256=PROFILE_SHA256,
    )


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    return root


@pytest.mark.anyio
async def test_host_xattr_profile_is_reported_during_mutation_readiness(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    attributes = os.listxattr(root)
    workspace = _workspace(root)
    await workspace.initialize()
    try:
        readiness = await workspace.mutation_readiness()
        assert readiness.available == (not attributes)
        assert readiness.reason_code == (None if not attributes else "workspace_xattrs_unsupported")
    finally:
        await workspace.close()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "attribute",
    ["security.selinux", "security.capability", "system.posix_acl_access", "user.note"],
)
async def test_every_xattr_uses_one_stable_capability_disabled_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
) -> None:
    root = _root(tmp_path)
    monkeypatch.setattr(os, "listxattr", lambda _descriptor: [attribute])
    workspace = _workspace(root)
    identity = await workspace.initialize()
    try:
        readiness = await workspace.mutation_readiness()
        assert not readiness.available
        assert readiness.reason_code == "workspace_xattrs_unsupported"
        with pytest.raises(WorkspaceEffectNotStarted) as captured:
            await workspace.create(
                WorkspaceCreateIntent(
                    operation_id="blocked-create",
                    relative_path="blocked",
                    kind=WorkspaceObjectKind.REGULAR_FILE,
                    content=b"blocked",
                    mode=0o644,
                    expected_root_identity_sha256=identity.identity_sha256,
                    expected_mount_identity_sha256=identity.mount.digest_sha256,
                )
            )
        assert captured.value.reason_code == "workspace_xattrs_unsupported"
        assert not (root / "blocked").exists()
    finally:
        await workspace.close()


@pytest.mark.anyio
async def test_unavailable_xattr_inspection_disables_mutation_at_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)

    def unavailable(_descriptor: int) -> list[str]:
        raise OSError("xattr inspection unavailable")

    monkeypatch.setattr(os, "listxattr", unavailable)
    workspace = _workspace(root)
    await workspace.initialize()
    try:
        readiness = await workspace.mutation_readiness()
        assert not readiness.available
        assert readiness.reason_code == "workspace_xattr_check_unavailable"
    finally:
        await workspace.close()


@pytest.mark.anyio
async def test_new_root_xattrs_latch_mutation_closed_until_reinitialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    attributes: list[str] = []
    monkeypatch.setattr(os, "listxattr", lambda _descriptor: list(attributes))
    workspace = _workspace(root)
    await workspace.initialize()
    try:
        assert (await workspace.mutation_readiness()).available
        attributes.append("security.selinux")
        assert (await workspace.mutation_readiness()).reason_code == (
            "workspace_xattrs_unsupported"
        )
        attributes.clear()
        assert (await workspace.mutation_readiness()).reason_code == (
            "workspace_xattrs_unsupported"
        )
    finally:
        await workspace.close()

    await workspace.initialize()
    try:
        assert (await workspace.mutation_readiness()).available
    finally:
        await workspace.close()
