"""Darwin boot identity and fenced process-group listing for the job manager.

Split from ``job_manager_entry`` (MS1); behavior unchanged.
"""

from __future__ import annotations

import ctypes
import re
import sys
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress

BOOT_SESSION = re.compile(r"[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}")
GROUP_LISTING_ATTEMPTS = 3  # PRE-J1g-F5: then [] (no listing), as before


def boot_id() -> str:
    """``kern.bootsessionuuid``: a public sysctl, new per boot, fixed within one.

    STEER-10: ``kern.boottime`` moves whenever the wall clock is set, so it
    cannot prove a reboot (``prior_boot``); ``kern.uuid`` is the kernel build.
    It is never process authority. The J1 owner is composed with this same id.
    """
    libc = ctypes.CDLL(None, use_errno=True)

    def sysctl(name: str, size: int) -> bytes:
        value, length = ctypes.create_string_buffer(size), ctypes.c_size_t(size)
        if libc.sysctlbyname(name.encode(), value, ctypes.byref(length), None, 0):
            raise OSError(ctypes.get_errno(), f"sysctl {name} failed")
        return value.raw[: length.value]

    session = sysctl("kern.bootsessionuuid", 64).rstrip(b"\0").decode("ascii")
    if not BOOT_SESSION.fullmatch(session.upper()):
        raise OSError("darwin_boot_identity_unavailable")
    return session.upper()


def prior_boot(meta: Mapping[str, object], current: str) -> bool:
    """STEER-10: the record's ``boot_id`` is provably an earlier boot's.

    Both ids must be boot sessions and differ. An absent, unreadable or
    other-format id proves nothing: the record stays UNKNOWN (fail closed).
    """
    ids = (meta.get("boot_id"), current)
    known = all(isinstance(i, str) and BOOT_SESSION.fullmatch(i) for i in ids)
    return known and ids[0] != ids[1]


# SD-59: only p_stat values with one Linux letter. SRUN is kept by XNU for a
# sleeping process too (R or S needs libproc thread states) and SIDL has no
# Linux state, so both stay unknown; SSTOP of a traced process may be Linux t.
_STATE_LETTERS = {3: "S", 4: "T", 5: "Z"}  # SSLEEP, SSTOP, SZOMB
_UNKNOWN_STATE = "?"  # D-2: not a state letter, never invented
_P_TRACED = 0x800  # kinfo_proc p_flag (offset 32)


def _sysctl(mib: Sequence[int], limit: int) -> bytes:
    """Public sysctl(3) read (KERN_PROC_PGRP / KERN_PROCARGS2); never libproc."""
    query = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True).sysctl
    query.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_uint, ctypes.c_void_p]
    query.argtypes += [
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    query.restype = ctypes.c_int
    names, size = (ctypes.c_int * len(mib))(*mib), ctypes.c_size_t()
    if query(names, len(mib), None, ctypes.byref(size), None, 0) != 0:
        raise OSError(ctypes.get_errno(), "sysctl size failed")
    if size.value > limit:
        raise OSError("sysctl size over limit")
    buffer = ctypes.create_string_buffer(size.value + 648 * 4)
    size.value = len(buffer)
    if query(names, len(mib), buffer, ctypes.byref(size), None, 0) != 0:
        raise OSError(ctypes.get_errno(), "sysctl read failed")
    return buffer.raw[: min(size.value, len(buffer))]


def command_line(pid: int, max_cmd_chars: int) -> str | None:
    """argv ONLY from KERN_PROCARGS2, like Linux /proc/<pid>/cmdline (PRE-J1g-F1).

    Layout: int argc, exec path, NUL padding to an 8-byte boundary, argv[argc],
    then envp, which is never read. Empty argv fields are kept and exactly
    argc are taken. Any doubt (short buffer, padding that does not match the
    aligned start, e.g. an empty argv[0], too few fields, undecodable bytes)
    returns None so the caller falls back to comm: fail closed.
    """
    try:
        data = _sysctl((1, 49, pid), 1 << 20)
    except OSError:
        return None
    argc = int.from_bytes(data[:4], sys.byteorder) if len(data) >= 4 else 0
    end = data.find(b"\0", 4)
    if argc <= 0 or end < 0:
        return None
    start = 4 + ((end - 4 + 1 + 7) & ~7)  # exec path + NUL, 8-byte aligned
    skipped = end
    while skipped < len(data) and data[skipped] == 0:
        skipped += 1
    if skipped != start:
        return None
    fields = data[start:].split(b"\0", argc)  # [argc fields..., rest: envp]
    if len(fields) <= argc:  # argv[argc - 1] not NUL-terminated: truncated
        return None
    try:
        argv = [field.decode("utf-8") for field in fields[:argc]]
    except UnicodeDecodeError:
        return None
    return " ".join(argv)[:max_cmd_chars]  # bounded after the join


def _state_letter(entry: bytes, state: int) -> str:
    """The Linux /proc state letter kinfo_proc determines, else ``?``."""
    if state == 4 and int.from_bytes(entry[32:36], sys.byteorder) & _P_TRACED:
        return _UNKNOWN_STATE
    return _STATE_LETTERS.get(state, _UNKNOWN_STATE)


def group_listing(pgid: int, max_cmd_chars: int) -> list[dict]:
    """JCRP-F6 (Linux job_processes shape): pid, state, etime_s and cmd.

    ``etime_s`` is the age from kinfo_proc p_starttime, rounded like Linux.
    ``cmd`` is the KERN_PROCARGS2 argv bounded by ``max_cmd_chars``, else the
    kinfo_proc comm when PROCARGS2 is denied, else empty like an empty Linux
    cmdline: never invented. ``cpu_s`` has no public per-process source here
    (SD-59 ruling 2 is pending). The owner calls this only for its verified
    group; it grants no signal right.
    """
    from binnacle.platform.darwin.process_authority import _decode_process_records

    raw = b""  # PRE-J1g-F5: a forking group races the size + read pair (ENOMEM)
    for _ in range(GROUP_LISTING_ATTEMPTS):
        with suppress(OSError):
            raw = _sysctl((1, 14, 2, pgid), 648 * 65536)
            break
    listing: list[dict] = []
    now = time.time()  # p_starttime is wall clock (microtime at fork)
    for offset in range(0, len(raw) - len(raw) % 648, 648):
        entry = raw[offset : offset + 648]
        try:
            (member,) = _decode_process_records(entry)
        except OSError:
            continue
        if member.group != pgid:
            continue
        cmd = command_line(member.pid, max_cmd_chars)
        if cmd is None:  # p_comm (MAXCOMLEN + 1) at kinfo_proc offset 243
            cmd = entry[243:260].split(b"\0", 1)[0].decode(errors="replace")
        started = member.birth[0] + member.birth[1] / 1_000_000
        listing.append(
            {
                "pid": member.pid,
                "state": _state_letter(entry, member.state),
                "etime_s": round(max(now - started, 0.0), 1),
                "cmd": cmd[:max_cmd_chars],
            }
        )
    return sorted(listing, key=lambda item: int(item["pid"]))
