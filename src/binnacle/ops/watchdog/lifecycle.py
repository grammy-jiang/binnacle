"""Long-running watchdog lifecycle and worker supervision."""

import json
import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from binnacle import uplink
from binnacle.ops.watchdog.command import Run, _run
from binnacle.ops.watchdog.config import DEFAULT_POLICY, Policy
from binnacle.ops.watchdog.cycle import cycle
from binnacle.ops.watchdog.fast import fast_loop, supervise_fast_path
from binnacle.ops.watchdog.inventory import versions
from binnacle.ops.watchdog.model import State

log = logging.getLogger("binnacle.watchdog")


def run_forever(
    state_file: Path,
    interval_s: float = 30.0,
    policy: Policy = DEFAULT_POLICY,
    host: str = uplink.UPSTREAM_HOST,
    timeout: float = 3.0,
    run: Run = _run,
    sleep: Callable[[float], None] = time.sleep,
    max_cycles: int | None = None,
    exit_fn: Callable[[int], None] = os._exit,
    *,
    cycle_fn: Callable[..., object] = cycle,
) -> None:
    """Probe forever. `max_cycles` bounds the loop for tests.

    Each cycle runs in a worker thread with `policy.cycle_timeout_s` as the
    deadline: a hung cycle (a subprocess that never returns, a kernel call
    that blocks) would otherwise leave the watchdog alive and useless --
    the exact shape of the outage it exists for. On a hang the process
    exits and systemd (Restart=always) starts a fresh one; the persisted
    state carries the demotions and counters across.

    The fast path's thread is supervised the same way from here: a dead
    thread is started again, a stalled heartbeat is logged, a hung one
    (older than the cycle timeout) exits the process.
    """
    state = State.load(state_file)
    log.info(
        "event=watchdog_start interval_s=%s host=%s state_file=%s cycle=%s demoted=%s "
        "counters=usb%s/prefer%s/level%s/reload%s versions=%s policy=%s",
        interval_s,
        host,
        state_file,
        state.cycle_n,
        sorted(state.demoted),
        json.dumps(state.usb_attempts),
        json.dumps(state.prefer_attempts),
        json.dumps(state.usb_speed_attempts),
        json.dumps(state.reload_attempts),
        json.dumps(versions(run)),
        json.dumps(asdict(policy), default=str),
    )
    stopping: list[str] = []

    def on_signal(signum: int, _frame: object) -> None:
        stopping.append(signal.Signals(signum).name)

    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, on_signal)
            except (ValueError, OSError):  # not the main thread, or embedded
                pass

    stop_fast = threading.Event()
    fast_thread: threading.Thread | None = None

    def start_fast() -> threading.Thread:
        thread = threading.Thread(
            target=fast_loop,
            args=(state, policy, run, stop_fast, host),
            name="watchdog-fast",
            daemon=True,
        )
        thread.start()
        return thread

    if policy.fast_interval_s > 0 and max_cycles is None:
        fast_thread = start_fast()
        log.info(
            "event=fast_path_start interval_s=%s failures_before_action=%s timeout_s=%s",
            policy.fast_interval_s,
            policy.fast_failures_before_action,
            policy.fast_timeout_s,
        )
    count = 0
    while max_cycles is None or count < max_cycles:
        if stopping:
            break

        def one_cycle() -> None:
            try:
                cycle_fn(state, policy, state_file, host=host, timeout=timeout, run=run)
            except Exception:  # keep the loop alive; a probe bug must not blind us
                log.exception("event=watchdog_cycle_error cycle=%s", state.cycle_n)

        worker = threading.Thread(target=one_cycle, name="watchdog-cycle", daemon=True)
        worker.start()
        worker.join(policy.cycle_timeout_s)
        if worker.is_alive():
            log.error(
                "event=watchdog_cycle_hung timeout_s=%s; exiting for systemd to restart",
                policy.cycle_timeout_s,
            )
            for handler in log.handlers or logging.getLogger().handlers:
                handler.flush()
            sys.stdout.flush()
            exit_fn(3)
            return
        if fast_thread is not None:
            fast_thread, hung = supervise_fast_path(
                state, policy, fast_thread, start_fast, exit_fn
            )
            if hung:
                return
        count += 1
        if stopping:
            break
        if max_cycles is None or count < max_cycles:
            sleep(interval_s)
    stop_fast.set()
    if stopping:
        log.warning(
            "event=watchdog_stop signal=%s cycle=%s demoted=%s",
            stopping[0],
            state.cycle_n,
            sorted(state.demoted) or "-",
        )
