"""Advisory-only Issue #30 lsof census with a same-call writable-FD canary.

Pure parsing and identity comparison: this module NEVER invokes lsof,
acquires privileges, closes FDs, signals services or deletes a raw log.
In particular a canary passed here is an untrusted statement until the
separate privileged controller verifies its own live file descriptors.
Even a perfect-looking lsof transcript NEVER authorizes source pruning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_MAX_OUTPUT = 256 * 1024
_P = re.compile(r"^[1-9][0-9]*$")
_F = re.compile(r"^(0|[1-9][0-9]*)$")
_D = re.compile(r"^(0x[0-9a-fA-F]+|[1-9][0-9]*)$")
_I = re.compile(r"^[1-9][0-9]*$")
_FIELDS = ("a", "D", "i", "n")


class FDCensusRefused(RuntimeError):
    """Malformed, incomplete or unverified FD scan; no safety conclusion."""


def _valid_path(path: Path) -> None:
    rendered = str(path)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or "\x00" in rendered
        or "\n" in rendered
        or "\r" in rendered
        or not rendered.startswith("/")
    ):
        raise FDCensusRefused("invalid pinned lsof path")


def _positive(value: object) -> bool:
    return type(value) is int and value > 0


@dataclass(frozen=True)
class FDIdentity:
    """Caller-supplied identity; NOT independently authenticated by this type."""

    path: Path
    device: int
    inode: int

    def __post_init__(self) -> None:
        _valid_path(self.path)
        if not _positive(self.device) or not _positive(self.inode):
            raise FDCensusRefused("invalid pinned source identity")


@dataclass(frozen=True)
class WritableCanary(FDIdentity):
    """Privileged caller must independently prove it currently owns this FD."""

    pid: int
    fd: int

    def __post_init__(self) -> None:
        super().__post_init__()
        if not _positive(self.pid) or type(self.fd) is not int or self.fd < 0:
            raise FDCensusRefused("untrusted lsof canary PID/FD")


@dataclass(frozen=True)
class FDCensusEvidence:
    """Read-only diagnostic; NO outcome can grant production delete authority."""

    source: FDIdentity
    canary: WritableCanary
    observed_readers: tuple[tuple[int, int], ...]
    observed_writers: tuple[tuple[int, int], ...]
    diagnostic: str
    manual_review_required: bool = True
    complete_privileged_fd_census: bool = False
    production_authorized: bool = False

    def __post_init__(self) -> None:
        if (
            not self.manual_review_required
            or self.complete_privileged_fd_census
            or self.production_authorized
        ):
            raise ValueError("FD census transcript cannot grant raw-log authority")


@dataclass(frozen=True)
class _FDRecord:
    pid: int
    fd: int
    access: str
    device: int
    inode: int
    name: str


def _parse(raw: str) -> tuple[_FDRecord, ...]:
    """Exact -F pafDin newline fields; any parser ambiguity refuses."""

    if (
        not isinstance(raw, str)
        or not raw
        or len(raw.encode("utf-8")) > _MAX_OUTPUT
        or not raw.endswith("\n")
        or "\x00" in raw
    ):
        raise FDCensusRefused("lsof transcript incomplete or oversized")

    rows: list[_FDRecord] = []
    pid: int | None = None
    opened = False
    fields: dict[str, str] = {}
    seen: set[tuple[int, int]] = set()
    for line in raw.splitlines():
        if not line:
            raise FDCensusRefused("blank lsof field")
        tag, value = line[0], line[1:]
        if tag == "p":
            if (
                fields
                or (pid is not None and not opened)
                or _P.fullmatch(value) is None
            ):
                raise FDCensusRefused("invalid lsof process boundary")
            pid = int(value)
            opened = False
        elif tag == "f":
            if pid is None or fields or _F.fullmatch(value) is None:
                raise FDCensusRefused("invalid lsof FD boundary")
            fields = {"f": value}
            opened = True
        else:
            if not fields or tag != _FIELDS[len(fields) - 1]:
                raise FDCensusRefused("unexpected lsof field order")
            fields[tag] = value
            if tag != "n":
                continue
            if (
                fields["a"] not in ("r", "w", "u")
                or _D.fullmatch(fields["D"]) is None
                or _I.fullmatch(fields["i"]) is None
                or not fields["n"].startswith("/")
            ):
                raise FDCensusRefused("lsof FD identity or access untrusted")
            fd = int(fields["f"])
            if pid is None:
                raise FDCensusRefused("missing lsof PID for FD record")
            ident = pid, fd
            if ident in seen:
                raise FDCensusRefused("duplicate lsof process/FD")
            seen.add(ident)
            rows.append(
                _FDRecord(
                    pid,
                    fd,
                    fields["a"],
                    int(fields["D"], 0),
                    int(fields["i"]),
                    fields["n"],
                )
            )
            fields = {}
    if fields or not rows or not opened:
        raise FDCensusRefused("truncated or empty lsof transcript")
    return tuple(rows)


def lsof_readonly_argv(source: FDIdentity, canary: WritableCanary) -> tuple[str, ...]:
    """Construct one fixed two-path census; does not run a subprocess."""
    if source.path == canary.path or (source.device, source.inode) == (
        canary.device,
        canary.inode,
    ):
        raise FDCensusRefused("source and positive control must be distinct")
    return (
        "/usr/sbin/lsof",
        "-nP",
        "-F",
        "pafDin",
        "--",
        str(source.path),
        str(canary.path),
    )


def classify_lsof_census(
    *,
    stdout: str,
    stderr: str,
    returncode: int,
    source: FDIdentity,
    canary: WritableCanary,
) -> FDCensusEvidence:
    """Refuse uncertain stdout, require one real-looking writable canary.

    Only the caller can establish actual privileges, independent process/FD
    identity, lsof executable provenance, launchd generation, elapsed quiet
    window and post-scan source-inode stability; this pure function cannot.
    The report therefore always requires human verification and is NEVER
    an adequate precondition for unlink.
    """
    lsof_readonly_argv(source, canary)
    if (
        type(returncode) is not int
        or returncode not in (0, 1)
        or not isinstance(stderr, str)
        or stderr
    ):
        raise FDCensusRefused("lsof execution or stderr untrusted")
    records = _parse(stdout)
    canary_seen = False
    readers: list[tuple[int, int]] = []
    writers: list[tuple[int, int]] = []
    for row in records:
        if row.name == str(source.path):
            if (row.device, row.inode) != (source.device, source.inode):
                raise FDCensusRefused("source inode changed during lsof scan")
            if row.access == "r":
                readers.append((row.pid, row.fd))
            else:
                writers.append((row.pid, row.fd))
        elif row.name == str(canary.path):
            if (row.device, row.inode) != (canary.device, canary.inode):
                raise FDCensusRefused("canary inode changed during lsof scan")
            if (row.pid, row.fd) == (canary.pid, canary.fd):
                if row.access not in ("w", "u"):
                    raise FDCensusRefused("positive control was not writable")
                canary_seen = True
        else:
            raise FDCensusRefused("unexpected lsof file record")
    if not canary_seen:
        raise FDCensusRefused("writable positive-control FD was not observed")
    if returncode == 1 and (readers or writers):
        # Even a positive-control lsof can exit 1 when one operand has
        # no matching FDs; with source matches, that code is ambiguous.
        raise FDCensusRefused("lsof partial-scan exit cannot be reconciled")
    diagnostic = (
        "source_absent_or_scan_incomplete_advisory_only"
        if returncode == 1
        else (
            "writable_source_fds_observed"
            if writers
            else "no_source_writer_observed_advisory_only"
        )
    )
    return FDCensusEvidence(
        source=source,
        canary=canary,
        observed_readers=tuple(sorted(readers)),
        observed_writers=tuple(sorted(writers)),
        diagnostic=diagnostic,
    )
