"""FDW-6: classify ELOOP/ENOTDIR using only a held parent FD.

These are diagnostic-only distinctions. Both must remain fail-closed with
identical outward UnsafePath code, even if the failed component changes.
"""

import errno
import os

import pytest

from binnacle.platform.contracts.capability_contracts import UnsafePath
from binnacle.platform.darwin import file_traversal as traversal


@pytest.mark.parametrize(
    ("kind", "kernel_errno", "classified"),
    [
        ("link", errno.ENOTDIR, errno.ELOOP),
        ("file", errno.ELOOP, errno.ENOTDIR),
    ],
)
def test_misleading_open_errno_is_reclassified_relative_to_held_fd(
    tmp_path, monkeypatch, kind, kernel_errno, classified
):
    root = tmp_path / "root"
    root.mkdir()
    (root / "real").mkdir()
    name = "entry"
    if kind == "link":
        (root / name).symlink_to("real", target_is_directory=True)
    else:
        (root / name).write_text("ordinary")
    base_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    original_open = os.open
    original_stat = os.stat
    examined = []

    def open_misreports(path, flags, *args, **kwargs):
        if path == name and kwargs.get("dir_fd") is not None:
            raise OSError(kernel_errno, os.strerror(kernel_errno))
        return original_open(path, flags, *args, **kwargs)

    def stat_held(path, *args, **kwargs):
        if path == name:
            examined.append((path, kwargs.get("dir_fd"), kwargs.get("follow_symlinks")))
            assert kwargs.get("dir_fd") is not None
            assert kwargs.get("follow_symlinks") is False
        return original_stat(path, *args, **kwargs)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(traversal.os, "open", open_misreports)
            patch.setattr(traversal.os, "stat", stat_held)
            with (
                pytest.raises(OSError) as exc,
                traversal.directory_at(base_fd, (name,)),
            ):
                pytest.fail("unsafe traversal unexpectedly succeeded")
            assert exc.value.errno == classified
            assert len(examined) == 1
            # The user-facing refusal remains a shared code, never weakened.
            with (
                pytest.raises(UnsafePath) as outer,
                traversal.native_errors(),
                traversal.directory_at(base_fd, (name,)),
            ):
                pytest.fail("unsafe traversal unexpectedly succeeded")
            assert outer.value.code == "symlink_or_wrong_path_type"
    finally:
        os.close(base_fd)


def test_missing_entry_after_failed_open_keeps_original_refusal(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "entry").symlink_to("gone")
    base_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    real_open = os.open

    def vanished(path, flags, *args, **kwargs):
        if path == "entry" and kwargs.get("dir_fd") is not None:
            (root / "entry").unlink()
            raise OSError(errno.ENOTDIR, os.strerror(errno.ENOTDIR))
        return real_open(path, flags, *args, **kwargs)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(traversal.os, "open", vanished)
            with (
                pytest.raises(OSError) as exc,
                traversal.directory_at(base_fd, ("entry",)),
            ):
                pytest.fail("unsafe traversal unexpectedly succeeded")
            assert exc.value.errno == errno.ENOTDIR
            assert not (root / "entry").exists()
    finally:
        os.close(base_fd)


@pytest.mark.parametrize("probe_errno", [errno.ENOENT, errno.EACCES, errno.EIO])
def test_diagnostic_stat_failure_preserves_original_refusal(
    tmp_path, monkeypatch, probe_errno
):
    root = tmp_path / "root"
    root.mkdir()
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    original_open = os.open
    original_stat = os.stat
    probes = []
    opens = []

    def refused_open(path, flags, *args, **kwargs):
        if path == "entry" and kwargs.get("dir_fd") is not None:
            opens.append(kwargs["dir_fd"])
            raise OSError(errno.ENOTDIR, "refused")
        return original_open(path, flags, *args, **kwargs)

    def failed_probe(path, *args, **kwargs):
        if path == "entry":
            probes.append(kwargs)
            raise OSError(probe_errno, "stat raced or denied")
        return original_stat(path, *args, **kwargs)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(traversal.os, "open", refused_open)
            patch.setattr(traversal.os, "stat", failed_probe)
            with pytest.raises(OSError) as exc, traversal.directory_at(fd, ("entry",)):
                pytest.fail("refusal must not become a successful directory")
        assert exc.value.errno == errno.ENOTDIR
        assert len(opens) == 1
        assert len(probes) == 1
        assert probes[0]["dir_fd"] == opens[0]
        assert probes[0]["follow_symlinks"] is False
    finally:
        os.close(fd)


@pytest.mark.parametrize(
    "refusal",
    [errno.EACCES, errno.EPERM, errno.EMFILE, errno.ENFILE, errno.EIO, errno.EINVAL],
)
def test_other_open_failures_are_not_probed_or_reclassified(
    tmp_path, monkeypatch, refusal
):
    root = tmp_path / "root"
    root.mkdir()
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    original_open = os.open
    original_stat = os.stat
    opens = []
    probes = []

    def refused_open(path, flags, *args, **kwargs):
        if path == "entry" and kwargs.get("dir_fd") is not None:
            opens.append(path)
            raise OSError(refusal, "refused")
        return original_open(path, flags, *args, **kwargs)

    def counted_stat(path, *args, **kwargs):
        if path == "entry":
            probes.append(path)
        return original_stat(path, *args, **kwargs)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(traversal.os, "open", refused_open)
            patch.setattr(traversal.os, "stat", counted_stat)
            with pytest.raises(OSError) as exc, traversal.directory_at(fd, ("entry",)):
                pytest.fail("refusal must not become a successful directory")
        assert exc.value.errno == refusal
        assert opens == ["entry"]
        assert probes == []
    finally:
        os.close(fd)


@pytest.mark.parametrize("refusal", [errno.ELOOP, errno.ENOTDIR])
def test_directory_still_present_preserves_original_refusal(
    tmp_path, monkeypatch, refusal
):
    root = tmp_path / "root"
    (root / "parent" / "entry").mkdir(parents=True)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    original_open = os.open
    original_stat = os.stat
    probes = []

    def refused_open(path, flags, *args, **kwargs):
        if path == "entry" and kwargs.get("dir_fd") is not None:
            raise OSError(refusal, "inconsistent open")
        return original_open(path, flags, *args, **kwargs)

    def held_parent_stat(path, *args, **kwargs):
        if path == "entry":
            parent_fd = kwargs["dir_fd"]
            assert kwargs["follow_symlinks"] is False
            assert os.fstat(parent_fd).st_ino == (root / "parent").stat().st_ino
            probes.append(parent_fd)
        return original_stat(path, *args, **kwargs)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(traversal.os, "open", refused_open)
            patch.setattr(traversal.os, "stat", held_parent_stat)
            with (
                pytest.raises(OSError) as exc,
                traversal.directory_at(root_fd, ("parent", "entry")),
            ):
                pytest.fail("refusal must not become a successful directory")
        assert exc.value.errno == refusal
        assert len(probes) == 1
    finally:
        os.close(root_fd)
