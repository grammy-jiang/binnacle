"""FD-anchored, owner-private atomic E2 evidence manifests (Linux and Darwin).

Protect against intermediate symlink replacement and torn final publication.
Do not store raw historic commands, paths or original request identifiers.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import secrets
import stat
from collections.abc import Iterator
from pathlib import Path

DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


@contextlib.contextmanager
def _owned_directory(path: Path) -> Iterator[int]:
    """Walk directory descriptors from /, rejecting untrusted write parents.

    Sticky root-owned temp directories are safe for our own child in standard
    POSIX semantics. No plaintext path or error message leaves this boundary.
    """
    path = path.expanduser()
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("E2 private directory must be absolute without traversal")
    parent = os.open("/", DIR_FLAGS)
    try:
        components = path.parts[1:]
        for index, component in enumerate(components):
            is_private_leaf = index == len(components) - 1
            info = os.fstat(parent)
            if info.st_mode & 0o022 and not (
                info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            ):
                raise PermissionError("E2 parent directory is untrusted")
            try:
                old = os.stat(component, dir_fd=parent, follow_symlinks=False)
                if stat.S_ISLNK(old.st_mode):
                    raise ValueError("E2 output directory symlink refused")
            except FileNotFoundError:
                pass
            try:
                current = os.open(component, DIR_FLAGS, dir_fd=parent)
            except FileNotFoundError:
                # All ancestors must preexist: this bounds the durability
                # contract to one final owner-private directory entry.
                if not is_private_leaf:
                    raise ValueError("E2 private parent must already exist") from None
                try:
                    os.mkdir(component, mode=0o700, dir_fd=parent)
                except FileExistsError:
                    pass
                current = os.open(component, DIR_FLAGS, dir_fd=parent)
            # Always sync the parent of the final directory, even on a
            # retry after a previous failed sync or a concurrent creator.
            try:
                if is_private_leaf:
                    os.fsync(parent)
            except BaseException:
                # current is open but not yet transferred to parent; do not
                # leak it when durability confirmation fails.
                os.close(current)
                raise
            os.close(parent)
            parent = current
        info = os.fstat(parent)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
        ):
            raise PermissionError("E2 output directory must be owned/private")
        yield parent
    finally:
        os.close(parent)


def _read_owned_file(dir_fd: int, name: str, *, max_bytes: int) -> bytes:
    fd = os.open(name, READ_FLAGS, dir_fd=dir_fd)
    try:
        st = os.fstat(fd)
        if (
            not stat.S_ISREG(st.st_mode)
            or st.st_uid != os.geteuid()
            or st.st_mode & 0o077
        ):
            raise PermissionError("E2 private file ownership/mode invalid")
        content = b""
        while len(content) <= max_bytes:
            part = os.read(fd, min(8192, max_bytes + 1 - len(content)))
            if not part:
                break
            content += part
        if len(content) > max_bytes:
            raise ValueError("E2 private file over size bound")
        return content
    finally:
        os.close(fd)


def _atomic_publish(
    dir_fd: int,
    name: str,
    data: bytes,
    *,
    allow_existing: bool,
) -> None:
    """Complete+fsync temporary data, then hardlink final only if absent.

    A process crash before link leaves at most an unused temp file. A
    successful final link is complete, never half-written. Final creation is
    atomic and cannot overwrite a concurrent writer. Idempotent retries may
    use the existing file only if the contents are identical.
    """
    if not name or "/" in name or name.startswith("."):
        raise ValueError("invalid private filename")
    temporary = f".e02-part-{secrets.token_hex(16)}"
    fd = os.open(temporary, WRITE_FLAGS, 0o600, dir_fd=dir_fd)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(fd)
        try:
            os.link(
                temporary,
                name,
                src_dir_fd=dir_fd,
                dst_dir_fd=dir_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            if not allow_existing:
                raise
            try:
                existing = _read_owned_file(dir_fd, name, max_bytes=len(data))
            except ValueError:
                raise FileExistsError("E2 batch differs from existing") from None
            if not hmac.compare_digest(existing, data):
                raise FileExistsError("E2 batch differs from existing") from None
        # An identical retry still has to establish the directory durability
        # barrier: a prior publish may have failed just after the hardlink.
        os.fsync(dir_fd)
    finally:
        os.close(fd)
        os.unlink(temporary, dir_fd=dir_fd)


def _secret(dir_fd: int) -> bytes:
    name = "e02-local-key.bin"
    try:
        return _valid_secret(_read_owned_file(dir_fd, name, max_bytes=32))
    except FileNotFoundError:
        # A concurrent writer may win. Atomic publish of an entirely formed
        # random key prevents observing a partial key on another reader.
        raw = secrets.token_bytes(32)
        try:
            _atomic_publish(dir_fd, name, raw, allow_existing=False)
        except FileExistsError:
            pass
        return _valid_secret(_read_owned_file(dir_fd, name, max_bytes=32))


def _valid_secret(data: bytes) -> bytes:
    if len(data) != 32:
        raise ValueError("E2 key invalid; manual recovery needed")
    return data


def write_document(private_dir: Path, batch: str, document: dict) -> None:
    """Atomically store an opaque local E2 sample and stable lookup key."""
    with _owned_directory(private_dir) as dir_fd:
        secret = _secret(dir_fd)
        cases = document["cases"]
        for entry in cases:
            # Consume only server-generation/call/group identity inside the
            # fd-anchored writer; raw identity never survives serialization.
            raw_ref = entry.pop("_host_private_lookup_material")
            raw_wire = json.dumps(raw_ref, separators=(",", ":")).encode("utf-8")
            entry["host_local_lookup"] = hmac.new(
                secret, raw_wire, hashlib.sha256
            ).hexdigest()[:32]
        serialized = (
            json.dumps(
                document, sort_keys=True, ensure_ascii=True, separators=(",", ":")
            )
            + "\n"
        ).encode("utf-8")
        _atomic_publish(dir_fd, f"{batch}.json", serialized, allow_existing=True)
