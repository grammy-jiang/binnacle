"""Independent Linux test-only controller-crash recovery, no launchctl/systemd."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

from binnacle.platform.darwin.log_maintenance_observer import (
    inspect_unowned_transaction,
)
from binnacle.platform.darwin.log_maintenance_transaction import (
    MaintenanceJournalRefused,
)

_ROOT = re.compile(r"^issue30-fixture-e2e-[0-9a-f]{32}$")


def _secure_root(root: Path) -> bool:
    if (
        sys.platform != "linux"
        or os.getuid() == 0
        or os.geteuid() != os.getuid()
        or not root.is_absolute()
        or _ROOT.fullmatch(root.name) is None
        or root.resolve() != root
    ):
        return False
    try:
        info = root.lstat()
        return (
            stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700
        )
    except OSError:
        return False


def _record(root: Path, *, state: str, pid: int | None = None) -> None:
    value = json.dumps({"state": state, "pid": pid}, sort_keys=True).encode()
    target = root / "guardian-outcome.json"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, value)
        os.fsync(fd)
    finally:
        os.close(fd)
    dfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def _fixture_original_alive(pid: int) -> bool:
    """Observe only the test's pinned Linux PID; uncertainty means still live."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    try:
        # A child whose stdin pipe closed after controller SIGKILL can be
        # reparented and transiently become a zombie. That is no live writer.
        data = (Path("/proc") / str(pid) / "stat").read_text()
        state = data.rsplit(")", 1)[1].strip().split(" ", 1)[0]
        return state not in {"Z", "X"}
    except (OSError, ValueError, IndexError):
        return True


def _known_active_pid(root: Path) -> int | None:
    """Read only a fixture-owned PID witness; unknown never means absent."""
    path = root / "active-writer.json"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or not 0 < info.st_size <= 256
        ):
            raise ValueError("untrusted fixture active writer witness")
        doc = json.loads(os.read(fd, 257))
        if (
            not isinstance(doc, dict)
            or set(doc) != {"pid", "nonce"}
            or type(doc["pid"]) is not int
            or doc["pid"] <= 0
            or doc["nonce"] != root.name[-32:]
        ):
            raise ValueError("wrong fixture active writer incarnation")
        return doc["pid"]
    finally:
        os.close(fd)


def _restart_fixture(root: Path) -> int:
    # The restored fixture gets a NEW active pathname, never the held raw
    # generation. We do not overwrite an existing "active" file.
    destination = root / "private-logs" / "mcp.stderr.log"
    try:
        fd = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
    except FileExistsError as exc:
        # A controller may have started the new test writer and crashed
        # before recording producer_restored. Preserve its active inode,
        # never truncate/recreate it or reopen the rotated raw filename.
        fd = os.open(destination, os.O_RDONLY | os.O_NOFOLLOW)
        stat_fd = os.fstat(fd)
        if (
            not stat.S_ISREG(stat_fd.st_mode)
            or stat_fd.st_uid != os.getuid()
            or stat.S_IMODE(stat_fd.st_mode) != 0o600
            or stat_fd.st_nlink != 1
        ):
            os.close(fd)
            raise ValueError("foreign active fixture log cannot be reopened") from exc
    os.close(fd)
    # The ONLY allowed command is our own test worker on its exact private
    # fixture root. No shell, service control, arbitrary commands or paths.
    args = [
        sys.executable,
        "-m",
        "tests.issue30_e2e_writer_fixture",
        str(root),
        "guardian-active",
    ]
    worker = subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        close_fds=True,
    )
    try:
        if worker.stdout is None:
            raise RuntimeError("fixture worker readiness pipe unavailable")
        ready = worker.stdout.readline().strip()
        if ready != f"READY {worker.pid} guardian-active":
            raise RuntimeError("fixture recovery writer not ready")
        # Release the guardian, not the already independent writer. The
        # test-owned writer expires or exits on its private stop marker.
        _record(root, state="restarted", pid=worker.pid)
        return worker.pid
    except BaseException:
        worker.terminate()  # Only the child this test guardian created.
        worker.wait(timeout=3)
        raise
    finally:
        if worker.stdout is not None:
            worker.stdout.close()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        return 64
    root = Path(args[0])
    if not _secure_root(root):
        return 64
    txn = root / ("txn-" + root.name.removeprefix("issue30-fixture-e2e-"))
    if not txn.is_dir():
        return 64
    print(f"READY {os.getpid()}", flush=True)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            snapshot = inspect_unowned_transaction(txn)
        except MaintenanceJournalRefused:
            time.sleep(0.04)
            continue
        # Owner released the kernel lock: the most recent durable phase
        # controls this independent fixture decision. Never resume deletion.
        if snapshot.phase == "complete":
            _record(root, state="not-needed")
            return 0
        if not snapshot.producer_may_be_stopped:
            _record(root, state="stopped-before-bootout")
            return 0
        if (root / "guardian-disarm").exists():
            _record(root, state="already-restored")
            return 0
        active_path = root / "private-logs" / "mcp.stderr.log"
        try:
            active_pid = _known_active_pid(root)
        except (OSError, ValueError, TypeError):
            _record(root, state="active-incarnation-unknown")
            return 75
        if active_pid is None and active_path.exists():
            # A newly reopened active file without independent PID witness
            # cannot justify either a duplicate restart or log mutation.
            _record(root, state="active-incarnation-unknown")
            return 75
        if active_pid is not None:
            wait_active = time.monotonic() + 3
            while _fixture_original_alive(active_pid):
                if time.monotonic() >= wait_active:
                    _record(root, state="already-restored")
                    return 0
                time.sleep(0.05)
        # After controller SIGKILL, the fixture's original pipe may only
        # just have closed. Wait briefly for the old test writer to release
        # its inherited raw FD; never create a second active writer while
        # the original worker is still live or its PID state is unknown.
        wait_old = time.monotonic() + 3
        while _fixture_original_alive(snapshot.producer_pid):
            if time.monotonic() >= wait_old:
                _record(root, state="original-still-live")
                return 75
            time.sleep(0.05)
        _restart_fixture(root)
        return 0
    _record(root, state="refused-timeout")
    return 75


if __name__ == "__main__":
    sys.exit(main())
