"""Launchd writer-lifecycle proof, limited to isolated system-domain fixtures.

This adapter exercises a real test-owned launchd bootout/bootstrap and the
macOS lsof fd-access probe. It deliberately refuses every production label:
neither a CLI nor unattended production pruning is permitted in this stage.
The production adapter additionally needs an external controller, exclusive
maintenance/admission barrier and crash-durable service restoration.
"""

from __future__ import annotations

import grp
import os
import plistlib
import pwd
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

from binnacle.companions.darwin_log_archive_finalize import ArchiveFinalizeRefused

_FIXTURE_LABEL = re.compile(r"com\.binnacle\.archivefixture\.[a-z0-9]{8,24}")
_ABSENT_RC = 113


def _run(argv: list[str], timeout: float = 12.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ArchiveFinalizeRefused("launchd or FD inspector unavailable") from exc


def _loaded(target: str) -> bool:
    result = _run(["/bin/launchctl", "print", target])
    if result.returncode == 0:
        # An installed label with no PID remains loaded and may relaunch.
        return True
    if result.returncode == _ABSENT_RC and "Could not find service" in (
        result.stderr + result.stdout
    ):
        return False
    raise ArchiveFinalizeRefused("launchd label state unprovable")


def _running_pid(target: str) -> int:
    """Require a singular live launchd generation, not just a loaded label."""
    result = _run(["/bin/launchctl", "print", target])
    if result.returncode != 0:
        raise ArchiveFinalizeRefused("writer launchd process unavailable")
    matches = re.findall(r"^\s+pid = ([1-9][0-9]*)$", result.stdout, re.MULTILINE)
    if len(matches) != 1:
        raise ArchiveFinalizeRefused("launchd writer generation unprovable")
    return int(matches[0])


def _no_writer_fds(path: Path) -> None:
    """Check every observable FD of the named *inode*, including descendants.

    An r-only descriptor held by the finalizer is permitted. Missing lsof
    access classifications, inspection errors, and writable/unknown FDs
    all refuse. The producer must separately be barred from restarting.
    """
    result = _run(["/usr/sbin/lsof", "-nP", "-F", "pafn", "--", str(path)])
    if result.returncode == 1 and not result.stdout and not result.stderr:
        return
    if result.returncode != 0 or result.stderr or not result.stdout:
        raise ArchiveFinalizeRefused("open-file descriptor census unprovable")
    pid = ""
    access: str | None = None
    matched = 0
    for line in result.stdout.splitlines():
        if not line:
            continue
        field, value = line[0], line[1:]
        if field == "p":
            if not value.isdecimal():
                raise ArchiveFinalizeRefused("invalid lsof process identity")
            pid = value
        elif field == "f":
            if not pid or not value:
                raise ArchiveFinalizeRefused("invalid lsof descriptor")
            access = None
        elif field == "a":
            if access is not None or value not in ("r", "w", "u"):
                raise ArchiveFinalizeRefused("unknown lsof access mode")
            access = value
        elif field == "n":
            if not pid or access != "r" or not value:
                raise ArchiveFinalizeRefused("log inode still writable or unknown")
            matched += 1
        else:
            raise ArchiveFinalizeRefused("unexpected lsof format")
    if matched == 0 or access is None:
        raise ArchiveFinalizeRefused("descriptor census incomplete")


class LaunchdFixtureWriterHold:
    """Real, native system-domain writer hold for *test-owned* launchd labels.

    The fixture owns the plist and no production service. A successful bootout
    unloads the label (including KeepAlive), and every verification checks
    both the continued unloaded state and the original inode's open FDs.
    __exit__ restores the original launchd fixture even after an exception.

    Never construct this class for any production launchd label: production
    requires an independent out-of-band controller, J7 lock and durable
    recovery process before its privileged analogue can exist.
    """

    def __init__(
        self,
        *,
        label: str,
        plist: Path,
        log_root: Path,
        name: str,
        producer: str = "system/com.binnacle.mcp",
        wait_s: float = 8.0,
    ) -> None:
        self.producer = producer
        self.label = label
        self.target = f"system/{label}"
        self.plist = plist
        self.root = log_root
        self.name = name
        self.wait_s = wait_s
        self._launchctl = ["/usr/bin/sudo", "-n", "/bin/launchctl"]
        self._held = False
        self._booted_out = False
        self._previous_pid = 0
        if (
            sys.platform != "darwin"
            or not _FIXTURE_LABEL.fullmatch(label)
            or name != "mcp.stderr.log.0"
            or producer != "system/com.binnacle.mcp"
            or str(plist) != f"/private/tmp/{label}.plist"
            or not 0 < wait_s <= 60
        ):
            raise ArchiveFinalizeRefused("test-owned launchd fixture required")

    def _plist_identity(self) -> None:
        try:
            s = self.plist.lstat()
            if (
                not stat.S_ISREG(s.st_mode)
                or s.st_uid != 0
                or s.st_gid != 0
                or s.st_nlink != 1
                or stat.S_IMODE(s.st_mode) != 0o644
            ):
                raise ArchiveFinalizeRefused("unsafe fixture service definition")
            value = plistlib.loads(self.plist.read_bytes())
            if (
                value.get("Label") != self.label
                or value.get("StandardErrorPath") != str(self.root / "mcp.stderr.log")
                or value.get("StandardOutPath") != str(self.root / "mcp.stdout.log")
                or value.get("UserName") != pwd.getpwuid(os.getuid()).pw_name
                or value.get("GroupName") != grp.getgrgid(os.getgid()).gr_name
                or value.get("RunAtLoad") is not True
                or value.get("KeepAlive") is not True
                or not isinstance(value.get("ProgramArguments"), list)
            ):
                raise ArchiveFinalizeRefused("untrusted fixture writer plan")
        except (OSError, ValueError, TypeError, plistlib.InvalidFileException) as exc:
            raise ArchiveFinalizeRefused("unreadable fixture writer plan") from exc

    def _no_writers(self) -> None:
        if _loaded(self.target):
            raise ArchiveFinalizeRefused("launchd could reopen old writer generation")
        _no_writer_fds(self.root / self.name)

    def __enter__(self) -> LaunchdFixtureWriterHold:  # noqa: PYI034 - Python 3.10
        if self._held or self._booted_out:
            raise ArchiveFinalizeRefused("writer hold cannot be entered twice")
        self._plist_identity()
        if not _loaded(self.target):
            raise ArchiveFinalizeRefused("fixture producer was not running")
        self._previous_pid = _running_pid(self.target)
        result = _run([*self._launchctl, "bootout", self.target])
        if result.returncode != 0:
            # A launchctl failure can occur after the label was unloaded.
            # Restore that partially-changed state rather than stranding it.
            if not _loaded(self.target):
                self._booted_out = True
                self._restore()
            raise ArchiveFinalizeRefused("launchd refused producer bootout")
        self._booted_out = True
        try:
            deadline = time.monotonic() + self.wait_s
            while True:
                try:
                    self._no_writers()
                    break
                except ArchiveFinalizeRefused:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.1)
            self._held = True
            return self
        except BaseException:
            self._restore()
            raise

    def verify(self, source: str, info: os.stat_result) -> None:
        if source != self.name or not self._held or not self._booted_out:
            raise ArchiveFinalizeRefused("writer hold generation not owned")
        opened = os.stat(self.root / source, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise ArchiveFinalizeRefused("held archive inode changed")
        self._no_writers()

    def _restore(self) -> None:
        if not self._booted_out:
            return
        try:
            if _loaded(self.target):
                raise ArchiveFinalizeRefused("fixture label changed during hold")
            self._plist_identity()
            result = _run([*self._launchctl, "bootstrap", "system", str(self.plist)])
            if result.returncode != 0:
                raise ArchiveFinalizeRefused("fixture producer restoration failed")
            deadline = time.monotonic() + max(self.wait_s, 2.0)
            while True:
                try:
                    pid = _running_pid(self.target)
                    if pid != self._previous_pid:
                        break
                except ArchiveFinalizeRefused:
                    pass
                if time.monotonic() >= deadline:
                    raise ArchiveFinalizeRefused(
                        "restored writer process generation unprovable"
                    )
                time.sleep(0.1)
            self._booted_out = False
        finally:
            self._held = False

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._restore()
