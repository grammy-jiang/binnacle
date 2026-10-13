"""J7-compatible exclusive file locks for a future Darwin log controller.

No CLI, service lifecycle, log deletion, production auto-run, or RPC admission.
Acquiring BOTH locks only serializes with the existing J7 deploy/Jobs install
actors; it does NOT make a service safe to stop. Tests use temp directories.
"""

from __future__ import annotations

import fcntl
import os
import stat
from pathlib import Path


class J7InterlockRefused(RuntimeError):
    """An unknown/unsafe lock means the maintenance operation must not start."""


class J7InterlockBusy(J7InterlockRefused):
    """An existing deploy or Jobs upgrade owns one of the locks."""


def _owned_directory(info: os.stat_result, *, uid: int) -> None:
    # The existing production state root can be 0755. Other users may list
    # file names, but must never be able to replace lock-file entries.
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & 0o022:
        raise J7InterlockRefused("J7 state directory is not safely owned")


def _private_directory(info: os.stat_result, *, uid: int) -> None:
    _owned_directory(info, uid=uid)
    if info.st_mode & 0o077:
        raise J7InterlockRefused("J7 service-lock directory is not private")


def _private_lock(info: os.stat_result, *, uid: int) -> None:
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != uid
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise J7InterlockRefused("J7 lock is not a private single-link regular file")


def _stable(fd: int, name: str, parent_fd: int, *, directory: bool) -> None:
    try:
        handle = os.fstat(fd)
        path = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            handle.st_dev != path.st_dev
            or handle.st_ino != path.st_ino
            or handle.st_mode != path.st_mode
            or handle.st_uid != path.st_uid
            or handle.st_nlink != path.st_nlink
        ):
            raise J7InterlockRefused("J7 lock/directory was replaced")
        if directory:
            _private_directory(handle, uid=os.getuid())
        else:
            _private_lock(handle, uid=os.getuid())
    except OSError as exc:
        raise J7InterlockRefused("J7 lock identity could not be verified") from exc


class J7Interlocks:
    """Scoped fail-closed J7 flock lease, never a writer hold.

    Lock order mirrors the J7 gate: mac-deploy-gate.lock at the private
    state root, then j7/jobs-service.lock. A missing private state directory
    or j7 subdirectory refuses; only the two canonical lock files may be
    created, with 0600 and no symlink following.

    Use with a context manager, never manually unlock. Closing descriptors
    instead of LOCK_UN avoids a forked child unlocking the parent's lock.
    """

    def __init__(self, state_root: Path) -> None:
        self.state_root = state_root
        self._pid = 0
        self._root_fd = -1
        self._j7_fd = -1
        self._gate_fd = -1
        self._jobs_fd = -1

    @staticmethod
    def _claim(parent: int, name: str) -> int:
        try:
            fd = os.open(
                name,
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
        except OSError as exc:
            raise J7InterlockRefused("J7 lock could not be opened") from exc
        try:
            _private_lock(os.fstat(fd), uid=os.getuid())
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, PermissionError) as exc:
                raise J7InterlockBusy(
                    "another J7 writer holds an exclusive lock"
                ) from exc
            _stable(fd, name, parent, directory=False)
            return fd
        except BaseException:
            os.close(fd)
            raise

    def __enter__(self) -> J7Interlocks:  # noqa: PYI034 - Python 3.10 floor
        if self._pid or self._root_fd >= 0:
            raise J7InterlockRefused("nested or shared lock ownership refused")
        if not self.state_root.is_absolute() or os.getuid() == 0:
            raise J7InterlockRefused("J7 lease needs an absolute user-owned root")
        try:
            self._root_fd = os.open(
                self.state_root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
            _owned_directory(os.fstat(self._root_fd), uid=os.getuid())
            self._j7_fd = os.open(
                "j7",
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=self._root_fd,
            )
            _private_directory(os.fstat(self._j7_fd), uid=os.getuid())
            # The existing deploy gate owns mac-deploy-gate.lock first.
            self._gate_fd = self._claim(self._root_fd, "mac-deploy-gate.lock")
            self._jobs_fd = self._claim(self._j7_fd, "jobs-service.lock")
            self._pid = os.getpid()
            self.verify()
            return self
        except OSError as exc:
            self._close()
            raise J7InterlockRefused("private J7 directory unavailable") from exc
        except BaseException:
            self._close()
            raise

    def verify(self) -> None:
        """Verify the same two acquired inodes and parent directories still hold."""
        if not self._pid or self._pid != os.getpid():
            raise J7InterlockRefused("J7 lock owner generation unknown")
        if min(self._root_fd, self._j7_fd, self._gate_fd, self._jobs_fd) < 0:
            raise J7InterlockRefused("J7 lock descriptor unavailable")
        root = os.stat(self.state_root, follow_symlinks=False)
        own = os.fstat(self._root_fd)
        if (root.st_dev, root.st_ino) != (own.st_dev, own.st_ino):
            raise J7InterlockRefused("J7 root identity changed")
        _owned_directory(own, uid=os.getuid())
        _stable(self._j7_fd, "j7", self._root_fd, directory=True)
        _stable(self._gate_fd, "mac-deploy-gate.lock", self._root_fd, directory=False)
        _stable(self._jobs_fd, "jobs-service.lock", self._j7_fd, directory=False)

    def _close(self) -> None:
        # Do not unlock explicitly: flock belongs to the open file description.
        for name in ("_jobs_fd", "_gate_fd", "_j7_fd", "_root_fd"):
            fd = getattr(self, name)
            setattr(self, name, -1)
            if fd >= 0:
                os.close(fd)
        self._pid = 0

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._close()
