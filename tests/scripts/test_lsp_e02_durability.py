"""E2 atomic, fsync and idempotent manifest handoff regression tests."""

from __future__ import annotations

import os

import pytest

from scripts import lsp_e02_private as storage


def test_retry_after_failed_directory_fsync_never_false_succeeds(tmp_path, monkeypatch):
    root = tmp_path / "private"
    document = b'{"synthetic":"complete"}\n'
    with storage._owned_directory(root) as directory:
        real_fsync = storage.os.fsync
        failures = []

        def fail_directory_only(fd):
            if fd == directory:
                failures.append(fd)
                raise OSError("injected directory fsync failure")
            return real_fsync(fd)

        monkeypatch.setattr(storage.os, "fsync", fail_directory_only)
        with pytest.raises(OSError, match="injected directory fsync"):
            storage._atomic_publish(
                directory, "batch.json", document, allow_existing=True
            )
        assert (root / "batch.json").read_bytes() == document
        # Before the fix, the second attempt incorrectly bypassed fsync.
        with pytest.raises(OSError, match="injected directory fsync"):
            storage._atomic_publish(
                directory, "batch.json", document, allow_existing=True
            )
        assert len(failures) == 2
        assert not list(root.glob(".e02-part-*"))

        monkeypatch.setattr(storage.os, "fsync", real_fsync)
        storage._atomic_publish(directory, "batch.json", document, allow_existing=True)
        assert (root / "batch.json").read_bytes() == document


def test_concurrent_conflicting_batch_never_replaces_published_file(tmp_path):
    root = tmp_path / "private"
    with storage._owned_directory(root) as directory:
        storage._atomic_publish(directory, "same.json", b"first", allow_existing=True)
        with pytest.raises(FileExistsError):
            storage._atomic_publish(
                directory, "same.json", b"second", allow_existing=True
            )
    assert (root / "same.json").read_bytes() == b"first"
    assert not list(root.glob(".e02-part-*"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor test")
def test_symlink_as_private_batch_is_never_read_or_overwritten(tmp_path):
    root = tmp_path / "private"
    outside = tmp_path / "outside"
    outside.write_bytes(b"unchanged synthetic content")
    with storage._owned_directory(root) as directory:
        (root / "victim.json").symlink_to(outside)
        with pytest.raises(OSError):
            storage._atomic_publish(
                directory, "victim.json", b"new", allow_existing=True
            )
    assert outside.read_bytes() == b"unchanged synthetic content"
    assert not list(root.glob(".e02-part-*"))


def test_private_key_is_only_reused_after_complete_publication(tmp_path):
    root = tmp_path / "private"
    payload = {
        "cases": [
            {
                "_host_private_lookup_material": [
                    ["observer", "synthetic-group"],
                    ["gen", "synthetic-call"],
                ]
            }
        ]
    }
    storage.write_document(root, "batch1", payload)
    previous_key = (root / "e02-local-key.bin").read_bytes()
    previous = (root / "batch1.json").read_bytes()
    storage.write_document(
        root,
        "batch2",
        {
            "cases": [
                {
                    "_host_private_lookup_material": [
                        ["observer", "synthetic-group"],
                        ["gen", "synthetic-call"],
                    ]
                }
            ]
        },
    )
    assert (root / "e02-local-key.bin").read_bytes() == previous_key
    assert (root / "batch1.json").read_bytes() == previous
    assert not list(root.glob(".e02-part-*"))


def test_new_private_directory_fsyncs_parent_before_ready(tmp_path, monkeypatch):
    import stat

    parent = tmp_path / "existing"
    parent.mkdir(mode=0o700)
    destination = parent / "new"
    real_fsync = storage.os.fsync
    observed = []

    def track(fd):
        status = os.fstat(fd)
        if stat.S_ISDIR(status.st_mode):
            observed.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(storage.os, "fsync", track)
    with storage._owned_directory(destination) as child_fd:
        assert os.fstat(child_fd).st_mode & 0o077 == 0
        # Creation barrier is completed before the caller receives a child FD.
        assert observed
    assert destination.is_dir()


def test_failed_parent_directory_fsync_does_not_publish_manifest(tmp_path, monkeypatch):
    import stat

    destination = tmp_path / "new-private"
    original = storage.os.fsync

    def refuse_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("synthetic parent durability failure")
        return original(fd)

    monkeypatch.setattr(storage.os, "fsync", refuse_directory)
    with pytest.raises(OSError, match="parent durability"):
        storage.write_document(destination, "batch", {"cases": []})
    assert not (destination / "batch.json").exists()

    monkeypatch.setattr(storage.os, "fsync", original)
    storage.write_document(destination, "batch", {"cases": []})
    assert (destination / "batch.json").exists()


def test_parent_fsync_is_retried_when_private_directory_already_visible(
    tmp_path, monkeypatch
):
    parent = tmp_path / "existing"
    parent.mkdir(mode=0o700)
    root = parent / "private-e2"
    original = storage.os.fsync
    parent_stat = parent.stat()
    blocked = []

    def refuse_parent_sync(fd):
        st = os.fstat(fd)
        if st.st_ino == parent_stat.st_ino and st.st_dev == parent_stat.st_dev:
            blocked.append(fd)
            raise OSError("synthetic missing parent persistence barrier")
        return original(fd)

    monkeypatch.setattr(storage.os, "fsync", refuse_parent_sync)
    for _ in range(2):
        with pytest.raises(OSError, match="missing parent persistence"):
            storage.write_document(root, "batch", {"cases": []})
        assert root.is_dir()
        assert not (root / "batch.json").exists()
    assert len(blocked) == 2

    monkeypatch.setattr(storage.os, "fsync", original)
    storage.write_document(root, "batch", {"cases": []})
    assert (root / "batch.json").is_file()


def test_private_output_does_not_create_missing_ancestors(tmp_path):
    root = tmp_path / "missing-parent" / "private-leaf"
    with pytest.raises(ValueError, match="parent must already exist"):
        storage.write_document(root, "batch", {"cases": []})
    assert not (tmp_path / "missing-parent").exists()


def test_parent_fsync_failure_closes_newly_opened_child_descriptor(
    tmp_path, monkeypatch
):
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o700)
    private = parent / "private"
    open_orig = storage.os.open
    fsync_orig = storage.os.fsync
    seen_children = []
    parent_meta = parent.stat()

    def record_open(name, flags, *args, **kwargs):
        fd = open_orig(name, flags, *args, **kwargs)
        ancestor = kwargs.get("dir_fd")
        if name == "private" and ancestor is not None:
            anchor = os.fstat(ancestor)
            if (
                anchor.st_ino == parent_meta.st_ino
                and anchor.st_dev == parent_meta.st_dev
            ):
                seen_children.append(fd)
        return fd

    def fail_parent_fsync(fd):
        info = os.fstat(fd)
        if info.st_ino == parent_meta.st_ino and info.st_dev == parent_meta.st_dev:
            raise OSError("synthetic parent sync failure")
        return fsync_orig(fd)

    monkeypatch.setattr(storage.os, "open", record_open)
    monkeypatch.setattr(storage.os, "fsync", fail_parent_fsync)
    with pytest.raises(OSError, match="parent sync failure"):
        storage.write_document(private, "batch", {"cases": []})
    assert len(seen_children) == 1
    with pytest.raises(OSError):
        os.fstat(seen_children[0])
