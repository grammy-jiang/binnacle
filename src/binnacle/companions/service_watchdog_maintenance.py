"""Opt-in watchdog restart fencing for *future* macOS log maintenance.

The deployed watchdog has no maintenance-fence flag. With explicit opt-in,
the watchdog and an out-of-band controller use the same private flock:
request creation is serialized against every watchdog restart attempt.

Acknowledgement is not maintenance authorization: this module does not
fence RPC/job admission, prove log FD closure or restore stopped services.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import stat
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger("binnacle.service_watchdog")
_NONCE = re.compile(r"^[0-9a-f]{32}$")
_MAX_BYTES = 512


class WatchdogPauseRefused(RuntimeError):
    """Unknown or unsafe maintenance pause state must block a restart."""


def _private(info: os.stat_result, *, regular: bool) -> None:
    kind = stat.S_ISREG if regular else stat.S_ISDIR
    if (
        not kind(info.st_mode)
        or info.st_uid != os.getuid()
        or (regular and (info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600))
        or (not regular and info.st_mode & 0o077)
    ):
        raise WatchdogPauseRefused("watchdog maintenance state not private")


@contextmanager
def _directory(root: Path) -> Iterator[int]:
    if not root.is_absolute():
        raise WatchdogPauseRefused("watchdog maintenance root not absolute")
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            opened, named = os.fstat(fd), root.lstat()
            _private(opened, regular=False)
            if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
                raise WatchdogPauseRefused("watchdog maintenance directory changed")
            yield fd
        finally:
            os.close(fd)
    except OSError as exc:
        raise WatchdogPauseRefused("watchdog maintenance root unavailable") from exc


@contextmanager
def _interlock(dfd: int, *, create: bool = True) -> Iterator[None]:
    """The SAME open-file-description lock spans pause check and restart."""
    try:
        fd = os.open(
            "restart.lock",
            os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0),
            0o600,
            dir_fd=dfd,
        )
    except OSError as exc:
        raise WatchdogPauseRefused("watchdog pause interlock inaccessible") from exc
    try:
        _private(os.fstat(fd), regular=True)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise WatchdogPauseRefused("watchdog pause interlock busy") from exc
        named = os.stat("restart.lock", dir_fd=dfd, follow_symlinks=False)
        opened = os.fstat(fd)
        if (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino):
            raise WatchdogPauseRefused("watchdog pause interlock replaced")
        yield
    except OSError as exc:
        raise WatchdogPauseRefused("watchdog pause interlock unverifiable") from exc
    finally:
        # Close only; LOCK_UN could unlock a fork-shared description.
        os.close(fd)


def _read_file(dfd: int, name: str) -> dict[str, object] | None:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise WatchdogPauseRefused("watchdog pause record inaccessible") from exc
    try:
        info = os.fstat(fd)
        _private(info, regular=True)
        if not 0 < info.st_size <= _MAX_BYTES:
            raise WatchdogPauseRefused("watchdog pause record size invalid")
        data = os.read(fd, _MAX_BYTES + 1)
        if len(data) != info.st_size:
            raise WatchdogPauseRefused("watchdog pause record changed during read")
        named = os.stat(name, dir_fd=dfd, follow_symlinks=False)
        if (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino):
            raise WatchdogPauseRefused("watchdog pause record inode changed")
    except OSError as exc:
        raise WatchdogPauseRefused("watchdog pause record read failed") from exc
    finally:
        os.close(fd)
    try:

        def unique(items: list[tuple[str, object]]) -> dict[str, object]:
            out: dict[str, object] = {}
            for key, value in items:
                if key in out:
                    raise ValueError("duplicate key")
                out[key] = value
            return out

        value = json.loads(data, object_pairs_hook=unique)
        if not isinstance(value, dict):
            raise TypeError("record not an object")
        return value
    except (ValueError, UnicodeDecodeError, TypeError) as exc:
        raise WatchdogPauseRefused("watchdog pause record is malformed") from exc


def _request(dfd: int) -> str | None:
    """A malformed/stale *existing* request MUST block restart, never allow."""
    value = _read_file(dfd, "request.json")
    if value is None:
        return None
    token = value.get("nonce")
    until = value.get("until")
    if (
        set(value) != {"version", "nonce", "scope", "until"}
        or type(value.get("version")) is not int
        or value.get("version") != 1
        or not isinstance(token, str)
        or _NONCE.fullmatch(token) is None
        or value.get("scope") != "all"
        or not isinstance(until, (float, int))
        or isinstance(until, bool)
        or not time.time() - 5 <= until <= time.time() + 180
    ):
        raise WatchdogPauseRefused("watchdog maintenance pause request invalid")
    return token


def _publish_ack(dfd: int, nonce: str) -> None:
    """Atomic 0600 acknowledgement from this watchdog incarnation only."""
    body = json.dumps(
        {"version": 1, "nonce": nonce, "watchdog_pid": os.getpid()},
        sort_keys=True,
    ).encode()
    previous = _read_file(dfd, "ack.json")
    if previous is not None and set(previous) != {"version", "nonce", "watchdog_pid"}:
        raise WatchdogPauseRefused("watchdog acknowledgement shape invalid")
    if (
        previous is not None
        and previous.get("nonce") == nonce
        and previous.get("watchdog_pid") == os.getpid()
    ):
        return
    _publish_private(dfd, "ack.json", body, prefix="ack")


def _publish_private(dfd: int, name: str, body: bytes, *, prefix: str) -> None:
    """Atomically publish one owned private file and never unlink a path swap."""
    if not 0 < len(body) <= _MAX_BYTES:
        raise WatchdogPauseRefused("watchdog maintenance payload too large")
    temp = "." + prefix + "-" + uuid.uuid4().hex + ".tmp"
    fd = -1
    created = False
    temp_identity: tuple[int, int] | None = None
    try:
        fd = os.open(
            temp,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=dfd,
        )
        created = True
        tstat = os.fstat(fd)
        temp_identity = (tstat.st_dev, tstat.st_ino)
        view = memoryview(body)
        while view:
            wrote = os.write(fd, view)
            if wrote <= 0:
                raise WatchdogPauseRefused("watchdog maintenance record short write")
            view = view[wrote:]
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(temp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
        os.fsync(dfd)
    except OSError as exc:
        raise WatchdogPauseRefused(
            "watchdog maintenance record publication failed"
        ) from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if created:
            # Another same-UID actor could swap a pathname; leave any
            # foreign replacement untouched rather than trusting its name.
            try:
                named: os.stat_result | None
                try:
                    named = os.stat(temp, dir_fd=dfd, follow_symlinks=False)
                except FileNotFoundError:
                    named = None
                if (
                    named is not None
                    and stat.S_ISREG(named.st_mode)
                    and (named.st_dev, named.st_ino) == temp_identity
                ):
                    os.unlink(temp, dir_fd=dfd)
            except OSError as exc:
                raise WatchdogPauseRefused(
                    "watchdog maintenance temporary cleanup unprovable"
                ) from exc


def request_pause(root: Path, *, nonce: str, until: float) -> None:
    """Controller-side *request only*, never maintenance authorization.

    Caller MUST first hold the separate J7 interlocks and have crash-durable
    service restoration ready. Acknowledgement is checked separately, with
    the exact watchdog launchd generation, before considering any stop.
    """
    now = time.time()
    if (
        not isinstance(nonce, str)
        or _NONCE.fullmatch(nonce) is None
        or not isinstance(until, (int, float))
        or isinstance(until, bool)
        or not now + 1 <= until <= now + 180
    ):
        raise WatchdogPauseRefused("watchdog maintenance request invalid")
    body = json.dumps(
        {"version": 1, "nonce": nonce, "scope": "all", "until": until},
        sort_keys=True,
    ).encode()
    with _directory(root) as dfd, _interlock(dfd):
        if _read_file(dfd, "request.json") is not None:
            raise WatchdogPauseRefused("existing watchdog pause request not released")
        _publish_private(dfd, "request.json", body, prefix="request")


def _unlink_verified(dfd: int, name: str, *, nonce: str) -> None:
    """Remove only the private record pinned and owned by this transaction."""
    fd = -1
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
        opened = os.fstat(fd)
        _private(opened, regular=True)
        named = os.stat(name, dir_fd=dfd, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            raise WatchdogPauseRefused("watchdog pause release inode changed")
        value = _read_file(dfd, name)
        if value is None or value.get("nonce") != nonce:
            raise WatchdogPauseRefused("watchdog pause release owner changed")
        os.unlink(name, dir_fd=dfd)
    except OSError as exc:
        raise WatchdogPauseRefused("watchdog pause release unprovable") from exc
    finally:
        if fd >= 0:
            os.close(fd)


def release_pause(root: Path, *, nonce: str) -> None:
    """Controller-side release; caller must FIRST restore writer/readiness.

    Release is under the same restart lock. If the request has expired,
    it is still only removable by the exact owner nonce. A bad or foreign
    ACK blocks cleanup. No job or launchd operation is performed here.
    """
    if not isinstance(nonce, str) or _NONCE.fullmatch(nonce) is None:
        raise WatchdogPauseRefused("watchdog pause release nonce invalid")
    with _directory(root) as dfd, _interlock(dfd):
        request = _read_file(dfd, "request.json")
        if (
            request is None
            or set(request) != {"version", "nonce", "scope", "until"}
            or type(request.get("version")) is not int
            or request.get("version") != 1
            or request.get("nonce") != nonce
            or request.get("scope") != "all"
        ):
            raise WatchdogPauseRefused("watchdog pause release request untrusted")
        ack = _read_file(dfd, "ack.json")
        if ack is not None:
            pid = ack.get("watchdog_pid")
            if (
                set(ack) != {"version", "nonce", "watchdog_pid"}
                or type(ack.get("version")) is not int
                or ack.get("version") != 1
                or ack.get("nonce") != nonce
                or not isinstance(pid, int)
                or isinstance(pid, bool)
                or pid <= 0
            ):
                raise WatchdogPauseRefused("watchdog pause release ACK untrusted")
            _unlink_verified(dfd, "ack.json", nonce=nonce)
        _unlink_verified(dfd, "request.json", nonce=nonce)


class WatchdogMaintenanceFence:
    """Opt-in watchdog side: nonblocking lock shared with controller request."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def poll(self) -> bool:
        """Publish an ACK to a valid request; refuse any unknown state."""
        with _directory(self.root) as dfd, _interlock(dfd):
            nonce = _request(dfd)
            if nonce is None:
                return False
            _publish_ack(dfd, nonce)
            return True

    def safely_paused(self) -> bool:
        """Never treat an unreadable maintenance record as permission to restart."""
        try:
            return self.poll()
        except WatchdogPauseRefused:
            log.error("event=service_watchdog_maintenance_pause_unknown")
            return True

    @contextmanager
    def action(self) -> Iterator[bool]:
        """Hold the interlock for the entire possible watchdog restart.

        The controller must acquire this SAME lock to publish a request.
        Thus it cannot treat a request/ACK as protected while an already
        in-progress watchdog restart is still executing.
        """
        with _directory(self.root) as dfd, _interlock(dfd):
            nonce = _request(dfd)
            if nonce is not None:
                _publish_ack(dfd, nonce)
                yield False
            else:
                yield True


def confirmed_ack(root: Path, *, nonce: str, watchdog_pid: int) -> bool:
    """Read-only check; never sufficient by itself to stop a producer."""
    if (
        not isinstance(nonce, str)
        or _NONCE.fullmatch(nonce) is None
        or type(watchdog_pid) is not int
        or watchdog_pid <= 0
    ):
        return False
    try:
        with _directory(root) as dfd, _interlock(dfd, create=False):
            if _request(dfd) != nonce:
                return False
            value = _read_file(dfd, "ack.json")
            return (
                value is not None
                and set(value) == {"version", "nonce", "watchdog_pid"}
                and value.get("version") == 1
                and value.get("nonce") == nonce
                and type(value.get("watchdog_pid")) is int
                and value["watchdog_pid"] == watchdog_pid
            )
    except WatchdogPauseRefused:
        return False
