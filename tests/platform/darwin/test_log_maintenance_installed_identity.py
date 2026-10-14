"""Exact allowlisted native service identity preflight; never authorizes actions."""

from __future__ import annotations

import hashlib
import os
import plistlib
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from binnacle.platform.darwin import log_maintenance_installed_identity as manifest


@pytest.mark.parametrize(
    ("label", "name"),
    [
        ("com.binnacle.mcp", "mcp.stderr.log.0"),
        ("com.binnacle.mcp", "mcp.stdout.log.1"),
        ("com.binnacle.jobs", "com.binnacle.jobs.err.log.2"),
        ("com.binnacle.jobs", "com.binnacle.jobs.out.log.0"),
        ("com.binnacle.tunnel", "tunnel.stderr.log.0"),
        ("com.binnacle.service-watchdog", "service-watchdog.stderr.log.0"),
        ("com.binnacle.resource-monitor", "resource-monitor.stdout.log.0"),
    ],
)
def test_only_repository_owned_producers_are_allowed(label: str, name: str) -> None:
    expected = manifest._PORTS[label]
    assert manifest._names(label, name) == expected


@pytest.mark.parametrize(
    ("label", "name"),
    [
        ("com.binnacle.session-observability", "session-observability.log.0"),
        ("com.binnacle.other", "mcp.stderr.log.0"),
        ("com.binnacle.mcp", "com.binnacle.jobs.err.log.0"),
        ("com.binnacle.mcp", "mcp.stderr.log"),
        ("com.binnacle.mcp", "mcp.stderr.log.-1"),
        ("com.binnacle.mcp", "mcp.stderr.log.00"),
        ("com.binnacle.mcp", "mcp.stderr.log.1000"),
        ("com.binnacle.mcp", "mcp.stderr.log.0.bz2"),
        ("com.binnacle.mcp", "/tmp/mcp.stderr.log.0"),
    ],
)
def test_unknown_source_or_label_never_enters_preflight(
    label: str,
    name: str,
) -> None:
    with pytest.raises(manifest.InstalledIdentityRefused, match="unknown"):
        manifest._names(label, name)


def _plist(label: str, home: Path, *, user: str, **updates) -> bytes:
    error, output = manifest._PORTS[label]
    body = {
        "Label": label,
        "RunAtLoad": True,
        "KeepAlive": (
            {"SuccessfulExit": False}
            if label in ("com.binnacle.jobs", "com.binnacle.resource-monitor")
            else True
        ),
        "UserName": user,
        "GroupName": "staff",
        "ProgramArguments": [str(home / ".venv/bin/python"), "-m", "safe.module"],
        "StandardErrorPath": str(home / "Library/Logs/binnacle" / error),
        "StandardOutPath": str(home / "Library/Logs/binnacle" / output),
    }
    body.update(updates)
    return plistlib.dumps(body)


@pytest.mark.parametrize("label", tuple(manifest._PORTS))
def test_installed_plist_shape_verified_for_each_exact_service(
    tmp_path: Path,
    label: str,
) -> None:
    err, out = manifest._PORTS[label]
    manifest._verify_plist(
        _plist(label, tmp_path, user="fixture"),
        label=label,
        stderr_name=err,
        stdout_name=out,
        private_logs=tmp_path / "Library/Logs/binnacle",
        username="fixture",
    )


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"Label": "com.binnacle.other"}, "differs"),
        ({"RunAtLoad": False}, "differs"),
        ({"RunAtLoad": 1}, "differs"),
        ({"KeepAlive": False}, "differs"),
        ({"KeepAlive": {"SuccessfulExit": True}}, "differs"),
        ({"KeepAlive": {"SuccessfulExit": False}}, "differs"),
        ({"UserName": "root"}, "differs"),
        ({"GroupName": "wheel"}, "differs"),
        ({"StandardErrorPath": "/var/log/other"}, "differs"),
        ({"StandardOutPath": "/var/log/other"}, "differs"),
        ({"ProgramArguments": []}, "differs"),
        ({"ProgramArguments": ["relative/python"]}, "differs"),
        ({"ProgramArguments": ["/usr/bin/python3", 123]}, "differs"),
        ({"MachServices": {"secret": True}}, "activation"),
        ({"Sockets": {"listen": "/tmp/unsafe.sock"}}, "activation"),
        ({"QueueDirectories": ["/tmp/private"]}, "activation"),
    ],
)
def test_plist_modifications_refused_even_with_same_label(
    tmp_path: Path,
    updates: dict,
    reason: str,
) -> None:
    label = "com.binnacle.mcp"
    err, out = manifest._PORTS[label]
    with pytest.raises(manifest.InstalledIdentityRefused, match=reason):
        manifest._verify_plist(
            _plist(label, tmp_path, user="fixture", **updates),
            label=label,
            stderr_name=err,
            stdout_name=out,
            private_logs=tmp_path / "Library/Logs/binnacle",
            username="fixture",
        )


@pytest.mark.parametrize("body", [b"", b"not-plist", b"<xml", b"x" * 40000])
def test_bad_or_huge_plist_refused(tmp_path: Path, body: bytes) -> None:
    with pytest.raises(manifest.InstalledIdentityRefused):
        manifest._verify_plist(
            body,
            label="com.binnacle.mcp",
            stderr_name="mcp.stderr.log",
            stdout_name="mcp.stdout.log",
            private_logs=tmp_path,
            username="fixture",
        )


@pytest.fixture
def files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "user"
    logdir = home / "Library" / "Logs" / "binnacle"
    logdir.mkdir(parents=True, mode=0o700)
    logdir.chmod(0o700)
    raw = logdir / "mcp.stderr.log.0"
    raw.write_bytes(b"owned fixture raw bytes")
    raw.chmod(0o600)
    system = tmp_path / "root-install"
    system.mkdir(mode=0o700)
    path = system / "com.binnacle.mcp.plist"
    contents = _plist("com.binnacle.mcp", home, user="fixture")
    path.write_bytes(contents)
    path.chmod(0o644)
    monkeypatch.setattr(manifest, "_PLIST_DIR", system)
    monkeypatch.setattr(
        manifest.pwd,
        "getpwuid",
        lambda uid: SimpleNamespace(pw_dir=str(home), pw_name="fixture"),
    )
    # Testing the Darwin root-owned metadata boundary on Linux without
    # sudo/chowning a system file. The actual syscall remains in production.
    real_pinned = manifest._pinned_file

    def root_fixture(path: Path, *, root: bool, owner_uid: int):
        if root:
            data = path.read_bytes()
            info = path.lstat()
            st = SimpleNamespace(
                st_dev=info.st_dev,
                st_ino=info.st_ino,
                st_uid=0,
                st_gid=0,
                st_mode=stat.S_IFREG | 0o644,
                st_nlink=1,
                st_size=len(data),
                st_mtime_ns=info.st_mtime_ns,
                st_ctime_ns=info.st_ctime_ns,
            )
            return data, st
        return real_pinned(path, root=root, owner_uid=owner_uid)

    monkeypatch.setattr(manifest, "_pinned_file", root_fixture)
    return home, raw, path, contents


def _inspect(home: Path, contents: bytes) -> manifest.InstalledWriterIdentity:
    return manifest.inspect_installed_writer(
        label="com.binnacle.mcp",
        raw_name="mcp.stderr.log.0",
        approved_plist_sha256=hashlib.sha256(contents).hexdigest(),
        home=home,
    )


def test_full_identity_preflight_pins_digest_and_raw_inode_without_mutation(
    files,
) -> None:
    home, raw, plist, contents = files
    before = (raw.read_bytes(), raw.stat().st_mtime_ns)
    result = _inspect(home, contents)
    assert result.label == "com.binnacle.mcp"
    assert result.launchd_target == "system/com.binnacle.mcp"
    assert result.plist_path == plist
    assert result.plist_digest == hashlib.sha256(contents).hexdigest()
    assert (result.raw_device, result.raw_inode) == (
        raw.stat().st_dev,
        raw.stat().st_ino,
    )
    assert result.raw_size == len(before[0])
    assert not result.production_authorized
    assert (raw.read_bytes(), raw.stat().st_mtime_ns) == before


def test_wrong_pinned_digest_refused_before_raw_mutation(files) -> None:
    home, raw, _plist_path, _contents = files
    with pytest.raises(manifest.InstalledIdentityRefused, match="digest"):
        manifest.inspect_installed_writer(
            label="com.binnacle.mcp",
            raw_name=raw.name,
            approved_plist_sha256="0" * 64,
            home=home,
        )
    assert raw.read_bytes() == b"owned fixture raw bytes"


@pytest.mark.parametrize("digest", [None, False, 42, "A" * 64, "f" * 63])
def test_noncanonical_digest_never_allows_producer_inspection(
    files,
    digest: object,
) -> None:
    home, _raw, _plist_path, _contents = files
    with pytest.raises(manifest.InstalledIdentityRefused, match="fingerprint"):
        manifest.inspect_installed_writer(
            label="com.binnacle.mcp",
            raw_name="mcp.stderr.log.0",
            approved_plist_sha256=cast(str, digest),
            home=home,
        )


@pytest.mark.parametrize("violation", ["public", "symlink", "hardlink", "missing"])
def test_source_insecure_or_missing_refused(files, violation: str) -> None:
    home, raw, _plist_path, contents = files
    if violation == "public":
        raw.chmod(0o644)
    elif violation == "hardlink":
        os.link(raw, raw.with_name("alias"))
    elif violation == "symlink":
        backup = raw.with_name("backup")
        raw.rename(backup)
        raw.symlink_to(backup)
    else:
        raw.unlink()
    with pytest.raises(manifest.InstalledIdentityRefused):
        _inspect(home, contents)


def test_foreign_home_or_public_logdir_refused(files) -> None:
    home, raw, _p, contents = files
    with pytest.raises(manifest.InstalledIdentityRefused, match="home differs"):
        _inspect(home / "other", contents)
    raw.parent.chmod(0o755)
    with pytest.raises(manifest.InstalledIdentityRefused, match="private logs"):
        _inspect(home, contents)


def test_never_fabricate_production_authority_from_identity() -> None:
    with pytest.raises(ValueError, match="does not authorize"):
        manifest.InstalledWriterIdentity(
            "com.binnacle.mcp",
            "system/com.binnacle.mcp",
            Path("/Library/LaunchDaemons/com.binnacle.mcp.plist"),
            "a" * 64,
            1,
            2,
            Path("/tmp/source"),
            1,
            3,
            4,
            production_authorized=True,
        )


def test_native_syscall_refuses_fake_root_owned_plist(tmp_path: Path) -> None:
    path = tmp_path / "root.plist"
    path.write_bytes(b"never an actual root-owned service")
    path.chmod(0o644)
    with pytest.raises(manifest.InstalledIdentityRefused, match="owner/mode"):
        manifest._pinned_file(path, root=True, owner_uid=os.getuid())


def test_raw_metadata_read_is_non_destructive(tmp_path: Path) -> None:
    raw = tmp_path / "private-source.log.0"
    data = b"secret-but-test-owned contents"
    raw.write_bytes(data)
    raw.chmod(0o600)
    original = raw.stat()
    value, report = manifest._pinned_file(raw, root=False, owner_uid=os.getuid())
    assert value == b""
    assert report.st_ino == original.st_ino
    assert raw.read_bytes() == data
    assert raw.stat().st_mtime_ns == original.st_mtime_ns


@pytest.mark.parametrize(
    "violation", ["missing", "hardlink", "symlink", "public", "empty"]
)
def test_real_file_probe_fails_closed_for_unsafe_source(tmp_path: Path, violation: str):
    raw = tmp_path / "private-source.log.0"
    raw.write_bytes(b"some contents")
    raw.chmod(0o600)
    if violation == "missing":
        raw.unlink()
    elif violation == "hardlink":
        os.link(raw, tmp_path / "hardlink")
    elif violation == "symlink":
        target = tmp_path / "real"
        raw.rename(target)
        raw.symlink_to(target)
    elif violation == "public":
        raw.chmod(0o644)
    elif violation == "empty":
        raw.write_bytes(b"")
    with pytest.raises(manifest.InstalledIdentityRefused):
        manifest._pinned_file(raw, root=False, owner_uid=os.getuid())


def test_unknown_privileged_caller_never_creates_an_authority(
    files,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, _raw, _plist_path, contents = files
    with monkeypatch.context() as patch:
        patch.setattr(manifest.os, "getuid", lambda: 0)
        with pytest.raises(manifest.InstalledIdentityRefused, match="unprivileged"):
            _inspect(home, contents)


def test_direct_list_plist_payload_is_not_an_installed_service(
    tmp_path: Path,
) -> None:
    with pytest.raises(manifest.InstalledIdentityRefused, match="not an object"):
        manifest._verify_plist(
            plistlib.dumps(["not", "a", "service"]),
            label="com.binnacle.mcp",
            stderr_name="mcp.stderr.log",
            stdout_name="mcp.stdout.log",
            private_logs=tmp_path,
            username="fixture",
        )
