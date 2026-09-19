"""Subprocess boundary for the watchdog companion."""

import subprocess
from collections.abc import Callable

from binnacle import uplink

Run = Callable[..., "subprocess.CompletedProcess[str]"]


def _run(*args: str, timeout: float = 30.0) -> "subprocess.CompletedProcess[str]":
    """Run a command; a timeout is reported as exit 124 (like coreutils'
    `timeout`) so a hung NetworkManager degrades the observations instead
    of aborting the cycle.

    For `sudo ...` the timeout is enforced by coreutils `timeout` on sudo's far
    side -- see uplink.sudo_timeout_argv for why subprocess's own timeout
    cannot do it. CompletedProcess.args is reported as the ORIGINAL argv so
    callers and logs see what was asked for, not the wrapping.
    """
    argv = uplink.sudo_timeout_argv(args, timeout)
    wrapped = argv != list(args)
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout + 5 if wrapped else timeout,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            list(args), 124, stdout="", stderr=f"timed out after {timeout:.0f} s"
        )
    if wrapped:
        proc.args = list(args)
    return proc
