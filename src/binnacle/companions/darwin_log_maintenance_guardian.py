"""Isolated macOS launchd writer crash-recovery guardian (fixture labels only).

This is NOT a production daemon, scheduler, maintenance command, or general
launchctl wrapper.  A separate launchd fixture runs this process to prove an
out-of-band actor can restore an unloaded synthetic producer after the test
controller dies and releases its OS-held maintenance lock.
"""

from __future__ import annotations

import argparse
import fcntl
import grp
import hashlib
import json
import os
import platform
import plistlib
import pwd
import stat
import sys
import time
from pathlib import Path
from typing import Any

from binnacle.companions.darwin_log_archive_finalize import ArchiveFinalizeRefused
from binnacle.companions.darwin_log_writer_hold import (
    _FIXTURE_LABEL,
    _loaded,
    _run,
    _running_pid,
)

MAX_RECORD_BYTES = 4096
TICK_S = 0.1
# Only the disposable test writer's exact command is permitted.
# This guardian must never serve as an arbitrary launchd bootstrap wrapper.
FIXTURE_PROGRAM_ARGS = [
    sys.executable,
    "-u",
    "-c",
    "import os,time;os.write(2,b'fixture started\\n');time.sleep(120)",
]
_FIXTURE_PLIST_KEYS = frozenset(
    {
        "Label",
        "UserName",
        "GroupName",
        "ProgramArguments",
        "RunAtLoad",
        "KeepAlive",
        "Umask",
        "ThrottleInterval",
        "StandardOutPath",
        "StandardErrorPath",
    }
)


def _read_verified(path: Path) -> dict[str, Any]:
    try:
        root = path.parent
        ds = root.lstat()
        if (
            not stat.S_ISDIR(ds.st_mode)
            or ds.st_uid != os.getuid()
            or ds.st_mode & 0o077
        ):
            raise ArchiveFinalizeRefused("unsafe guardian state directory")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            st = os.fstat(fd)
            if (
                not stat.S_ISREG(st.st_mode)
                or st.st_uid != os.getuid()
                or st.st_nlink != 1
                or stat.S_IMODE(st.st_mode) != 0o600
                or not 0 < st.st_size <= MAX_RECORD_BYTES
            ):
                raise ArchiveFinalizeRefused("unsafe guardian record")
            data = os.read(fd, MAX_RECORD_BYTES + 1)
        finally:
            os.close(fd)
        record = json.loads(data)
        if not isinstance(record, dict):
            raise ArchiveFinalizeRefused("invalid guardian record")
        return record
    except (OSError, ValueError, TypeError) as exc:
        raise ArchiveFinalizeRefused("guardian record cannot be trusted") from exc


def _policy(record: dict[str, Any], base: Path) -> tuple[str, Path]:
    if os.getuid() == 0 or os.geteuid() != os.getuid():
        raise ArchiveFinalizeRefused("fixture guardian must be unprivileged")
    if record.get("version") != 1 or record.get("state") not in {
        "armed",
        "disarmed",
        "recovered",
    }:
        raise ArchiveFinalizeRefused("unknown recovery state")
    label = record.get("label")
    if not isinstance(label, str) or not _FIXTURE_LABEL.fullmatch(label):
        raise ArchiveFinalizeRefused("guardian may only restore an archive fixture")
    plist = Path("/private/tmp") / f"{label}.plist"
    if record.get("plist") != str(plist):
        raise ArchiveFinalizeRefused("foreign fixture plist path")
    if record.get("lock") != str(base / "lease.lock"):
        raise ArchiveFinalizeRefused("foreign maintenance lock")
    if record.get("previous_pid") is None or not (
        type(record["previous_pid"]) is int and record["previous_pid"] > 0
    ):
        raise ArchiveFinalizeRefused("previous producer generation unknown")
    identity = record.get("nonce")
    if (
        not isinstance(identity, str)
        or len(identity) != 32
        or not all(c in "0123456789abcdef" for c in identity)
    ):
        raise ArchiveFinalizeRefused("malformed transaction identity")
    try:
        info = plist.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or (info.st_uid, info.st_gid, info.st_nlink) != (0, 0, 1)
            or stat.S_IMODE(info.st_mode) != 0o644
        ):
            raise ArchiveFinalizeRefused("guardian fixture plist ownership invalid")
        raw = plist.read_bytes()
        if hashlib.sha256(raw).hexdigest() != record.get("plist_sha256"):
            raise ArchiveFinalizeRefused("guardian fixture plist digest changed")
        parsed = plistlib.loads(raw)
        root_value = record.get("log_root")
        if not isinstance(root_value, str) or not root_value.startswith("/"):
            raise ArchiveFinalizeRefused("fixture log root is not authenticated")
        log_root = Path(root_value)
        root_info = log_root.lstat()
        if (
            log_root.name != "private-logs"
            or not stat.S_ISDIR(root_info.st_mode)
            or root_info.st_uid != os.getuid()
            or root_info.st_mode & 0o077
        ):
            raise ArchiveFinalizeRefused("unsafe test-owned fixture log root")
        if (
            set(parsed) != _FIXTURE_PLIST_KEYS
            or parsed.get("Label") != label
            or parsed.get("UserName") != pwd.getpwuid(os.getuid()).pw_name
            or parsed.get("GroupName") != grp.getgrgid(os.getgid()).gr_name
            or parsed.get("ProgramArguments") != FIXTURE_PROGRAM_ARGS
            or parsed.get("RunAtLoad") is not True
            or parsed.get("KeepAlive") is not True
            or parsed.get("Umask") != 0o077
            or parsed.get("ThrottleInterval") != 1
            or parsed.get("StandardErrorPath") != str(log_root / "mcp.stderr.log")
            or parsed.get("StandardOutPath") != str(log_root / "mcp.stdout.log")
        ):
            raise ArchiveFinalizeRefused("guardian fixture plist plan invalid")
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException) as exc:
        raise ArchiveFinalizeRefused("guardian fixture plist unreadable") from exc
    return f"system/{label}", plist


def _write_record(path: Path, record: dict[str, Any]) -> None:
    base = path.parent
    temp = base / f".guardian-{os.getpid():d}.tmp"
    data = json.dumps(record, sort_keys=True).encode("utf-8")
    if len(data) > MAX_RECORD_BYTES:
        raise ArchiveFinalizeRefused("guardian record too large")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(data)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise ArchiveFinalizeRefused("guardian record short write")
            view = view[count:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temp, path)
    dirfd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(dirfd)
    finally:
        os.close(dirfd)


def _ready(base: Path, token: str) -> None:
    # An earlier guardian may have been SIGKILLed after announcing readiness.
    # Replace its exact private receipt with the new incarnation's PID.
    path = base / ("ready-" + token)
    if path.exists() or path.is_symlink():
        prior = path.lstat()
        if (
            not stat.S_ISREG(prior.st_mode)
            or prior.st_uid != os.getuid()
            or prior.st_nlink != 1
            or stat.S_IMODE(prior.st_mode) != 0o600
        ):
            raise ArchiveFinalizeRefused("foreign guardian readiness receipt")
    temp = base / f".ready-{os.getpid()}.tmp"
    fd = os.open(temp, os.O_WRONLY | os.O_EXCL | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temp, path)
    dirfd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(dirfd)
    finally:
        os.close(dirfd)


def supervise(path: Path, *, max_wait_s: float = 20.0) -> str:
    """Restore the exact synthetic producer if the separate controller dies.

    The controller holds an exclusive flock across its entire writer stop and
    finalization.  A SIGKILL releases that lock; this independent process
    acquires it before restoring.  During a live held transaction, bootstrap
    is forbidden even when the nominal lease deadline is reached.

    The production unresolved case is a live *hung* controller holding flock:
    this fixture never kills processes to force that gate. Production therefore
    still requires a separately reviewed bounded lease-break protocol.
    """
    if platform.system() != "Darwin" or not 0 < max_wait_s <= 120:
        raise ArchiveFinalizeRefused("native fixture guardian only")
    record = _read_verified(path)
    target, plist = _policy(record, path.parent)
    lock = path.parent / "lease.lock"
    fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        ls = os.fstat(fd)
        if (
            not stat.S_ISREG(ls.st_mode)
            or ls.st_uid != os.getuid()
            or ls.st_nlink != 1
            or stat.S_IMODE(ls.st_mode) != 0o600
        ):
            raise ArchiveFinalizeRefused("invalid guardian maintenance lock")
        if not _loaded(target):
            # Only a previously armed, independently acknowledged fixture
            # can resume when its producer has been booted out.
            prior = path.parent / ("ready-" + record["nonce"])
            if record["state"] != "armed" or not prior.exists():
                raise ArchiveFinalizeRefused("cannot arm after writer is already gone")
            prior_st = prior.lstat()
            if (
                not stat.S_ISREG(prior_st.st_mode)
                or prior_st.st_uid != os.getuid()
                or prior_st.st_nlink != 1
                or stat.S_IMODE(prior_st.st_mode) != 0o600
            ):
                raise ArchiveFinalizeRefused("previous guardian receipt untrusted")
        _ready(path.parent, record["nonce"])
        deadline = time.monotonic() + max_wait_s
        while time.monotonic() < deadline:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                time.sleep(TICK_S)
                continue
            current = _read_verified(path)
            _policy(current, path.parent)
            if current["nonce"] != record["nonce"]:
                raise ArchiveFinalizeRefused("fixture transaction changed")
            if current["state"] in ("disarmed", "recovered"):
                return current["state"]
            if _loaded(target):
                now = _running_pid(target)
                if now == current["previous_pid"]:
                    # The test controller exited before bootout. No producer
                    # interruption occurred, so finish with an explicit
                    # durable no-op rather than a crash-looping guardian.
                    current["state"] = "disarmed"
                    current["outcome"] = "producer-never-stopped"
                    current["restored_pid"] = now
                    _write_record(path, current)
                    return "disarmed"
                outcome = "already-running"
            else:
                response = _run(
                    [
                        "/usr/bin/sudo",
                        "-n",
                        "/bin/launchctl",
                        "bootstrap",
                        "system",
                        str(plist),
                    ]
                )
                if response.returncode != 0:
                    raise ArchiveFinalizeRefused("guardian could not restore writer")
                until = time.monotonic() + 6
                while True:
                    try:
                        now = _running_pid(target)
                        if now != current["previous_pid"]:
                            break
                    except ArchiveFinalizeRefused:
                        pass
                    if time.monotonic() >= until:
                        raise ArchiveFinalizeRefused("restored writer not ready")
                    time.sleep(TICK_S)
                outcome = "bootstrapped"
            current["state"] = "recovered"
            current["restored_pid"] = now
            current["outcome"] = outcome
            _write_record(path, current)
            return "recovered"
        raise ArchiveFinalizeRefused("guardian deadline elapsed without lock release")
    finally:
        os.close(fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-state", type=Path, required=True)
    parser.add_argument("--max-wait-s", type=float, default=20.0)
    options = parser.parse_args(argv)
    try:
        state = supervise(options.fixture_state, max_wait_s=options.max_wait_s)
    except ArchiveFinalizeRefused as exc:
        print(f"test guardian refused: {exc}", file=sys.stderr)
        return 2
    print("test guardian outcome: " + state, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
