"""Serve a ``DarwinJobManager`` over A3 for one manager process lifetime.

The jobs-dir writer lock spans recovery, serving and close. The sole reaper
thread must outlive serving; if it ends early the manager stops (non-zero), so
launchd restarts it and D-1 recovery applies.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
from pathlib import Path

from binnacle.platform.contracts.native_service_contracts import ServiceLease
from binnacle.platform.darwin.job_manager_service import (
    DarwinJobManager,
    jobs_dir_writer,
)

log = logging.getLogger("binnacle.job_manager")


def serve_job_manager(
    manager: DarwinJobManager,
    *,
    socket_path: Path,
    lease: ServiceLease,
    stop: threading.Event,
) -> int:
    """Serve until ``stop``; the jobs-dir writer lock spans recovery and close."""
    from binnacle.platform.darwin.ipc_transport import serve_authenticated

    if signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
        raise RuntimeError("darwin_exclusive_reaper_required")
    with jobs_dir_writer(manager.jobs_dir):
        recovered = manager.recover()
        log.info("event=job_manager_start pid=%d recovered=%d", os.getpid(), recovered)
        halt, died = threading.Event(), threading.Event()

        def reap() -> None:
            try:
                manager.reap_forever(halt)
            except Exception:
                log.exception("event=job_manager_reaper_error")
            finally:
                if not halt.is_set():  # never serve without a reaper (D-1 on restart)
                    log.error("event=job_manager_reaper_stopped")
                    died.set()
                    stop.set()

        reaper = threading.Thread(target=reap, name="job-manager-reaper")
        reaper.start()
        try:
            handler = manager.handle
            serve_authenticated(socket_path, lease=lease, handler=handler, stop=stop)
        finally:
            halt.set()
            reaper.join()
            manager.close()
    if died.is_set():
        raise RuntimeError("job_manager_reaper_stopped")  # exit non-zero; restart
    return recovered
